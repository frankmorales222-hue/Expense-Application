"""F&M Finance update files (v0.10.1). Run on the build PC with the build's Python.

One time only (before building the first version that can install updates):
    python packaging\\make_update.py keygen
  - makes the PRIVATE signing key in %USERPROFILE%\\.fmfinance\\update_signing_key.pem (never shipped, never in the zip)
  - writes the matching PUBLIC key into backend\\app\\update_key.py (that file goes into every build from now on)
  Back up the private key file. Without it, installed copies can't take updates until one manual install
  of a build with a new key.

Every release, after building portable-output\\FMFinance.exe:
    python packaging\\make_update.py build --notes "What changed"
  - makes update-output\\FMFinance_Update_v<version>.fmupdate, signed with the private key

Check a file:
    python packaging\\make_update.py verify update-output\\FMFinance_Update_v0.10.1.fmupdate
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_MODULE = ROOT / "backend" / "app" / "update_key.py"
DEFAULT_KEY = Path(os.environ.get("USERPROFILE") or Path.home()) / ".fmfinance" / "update_signing_key.pem"


def app_version() -> str:
    text = (ROOT / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("Can't find __version__ in backend/app/__init__.py")
    return m.group(1)


def public_key_in_source() -> str | None:
    text = KEY_MODULE.read_text(encoding="utf-8") if KEY_MODULE.exists() else ""
    m = re.search(r'PUBLIC_KEY_PEM[^=]*=\s*"""(.*?)"""', text, re.S)
    return m.group(1).strip() if m else None


def write_key_module(public_pem: str) -> None:
    KEY_MODULE.write_text(
        '"""Public key that update files must be signed with (v0.10.1).\n\n'
        "Written by `packaging/make_update.py keygen` on the build PC. It is a PUBLIC key (safe to keep in the\n"
        "source); the matching private key stays on the build PC and is never shipped.\n"
        '"""\n\n'
        f'PUBLIC_KEY_PEM: str | None = """{public_pem.strip()}\n"""\n',
        encoding="utf-8",
    )


def load_private(path: Path):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    if not path.exists():
        raise SystemExit(f"No private key at {path}. Run: python packaging\\make_update.py keygen")
    return load_pem_private_key(path.read_bytes(), password=None)


def public_pem_of(private) -> str:
    from cryptography.hazmat.primitives import serialization

    return private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def cmd_keygen(args) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_path = Path(args.key)
    if key_path.exists():
        # Already have a key: just make sure the source carries its public half.
        private = load_private(key_path)
        pub = public_pem_of(private)
        if public_key_in_source() != pub.strip():
            write_key_module(pub)
            print(f"Existing key kept ({key_path}); public key written to {KEY_MODULE}")
        else:
            print(f"Existing key kept ({key_path}); the source already has its public key.")
        return 0
    existing = public_key_in_source()
    if existing and not args.force:
        raise SystemExit("The source already has a public key but the private key isn't on this PC "
                         f"({key_path}). Copy the private key here, or use --force to start a NEW key "
                         "(installed copies then need one manual install).")
    private = Ed25519PrivateKey.generate()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    write_key_module(public_pem_of(private))
    print(f"Private key: {key_path}   <-- keep it safe and back it up; never share or zip it")
    print(f"Public key written to {KEY_MODULE}")
    return 0


def cmd_build(args) -> int:
    exe = Path(args.exe)
    if not exe.exists():
        raise SystemExit(f"{exe} not found. Build the EXE first.")
    private = load_private(Path(args.key))
    pub = public_pem_of(private).strip()
    if public_key_in_source() != pub:
        raise SystemExit("backend/app/update_key.py doesn't match your private key. Run keygen, rebuild the EXE, "
                         "then build the update file.")
    version = args.version or app_version()
    digest = hashlib.sha256()
    with open(exe, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    notes = args.notes or ""
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    manifest = {
        "format": 1, "app": "fm-finance", "version": version, "min_version": args.min_version,
        "exe_sha256": digest.hexdigest(), "exe_size": exe.stat().st_size, "notes": notes.strip()[:5000],
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    sig = base64.b64encode(private.sign(manifest_bytes))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"FMFinance_Update_v{version}.fmupdate"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("manifest.sig", sig)
        zf.write(exe, "FMFinance.exe")
    print(f"Update file: {out}  ({out.stat().st_size / 1048576:.1f} MB)")
    print(f"Version {version}, program SHA-256 {manifest['exe_sha256'].upper()}")
    return 0


def cmd_verify(args) -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app import update_key, updates

    if not update_key.PUBLIC_KEY_PEM:
        raise SystemExit("backend/app/update_key.py has no public key yet.")
    with zipfile.ZipFile(args.file) as zf:
        manifest_bytes = zf.read("manifest.json")
        updates._verify_signature(manifest_bytes, zf.read("manifest.sig"))
        man = updates._read_manifest(manifest_bytes)
        h = hashlib.sha256()
        with zf.open("FMFinance.exe") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    if h.hexdigest() != man.exe_sha256:
        raise SystemExit("FAIL: the program inside doesn't match the signed details")
    print(f"OK: signed update for version {man.version} (needs {man.min_version} or newer)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--key", default=str(DEFAULT_KEY))
    k.add_argument("--force", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--exe", default=str(ROOT / "portable-output" / "FMFinance.exe"))
    b.add_argument("--key", default=str(DEFAULT_KEY))
    b.add_argument("--out", default=str(ROOT / "update-output"))
    b.add_argument("--notes", default="")
    b.add_argument("--notes-file", default="")
    b.add_argument("--min-version", default="0.10.1")
    b.add_argument("--version", default="", help="Only for testing the automatic roll-back. Normally omit.")
    v = sub.add_parser("verify")
    v.add_argument("file")
    args = p.parse_args()
    return {"keygen": cmd_keygen, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

"""v0.10.1 in-app updates: signed update files, checks, backup and the hand-over to the helper."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import __version__, updates
from app.config import get_settings

from .test_multicompany import login

EXE = b"MZ fake windows program " * 1000


def _pem(private) -> str:
    return private.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def package(private, version: str = "0.12.3", exe: bytes = EXE, *, min_version: str = "0.12.2",
            tamper_exe: bool = False, extra: bool = False) -> bytes:
    manifest = {"format": 1, "app": "fm-finance", "version": version, "min_version": min_version,
                "exe_sha256": hashlib.sha256(exe).hexdigest(), "exe_size": len(exe), "notes": "Fixes", "built_at": "x"}
    mb = json.dumps(manifest).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", mb)
        zf.writestr("manifest.sig", base64.b64encode(private.sign(mb)))
        zf.writestr("FMFinance.exe", (exe[:-1] + b"X") if tamper_exe else exe)
        if extra:
            zf.writestr("evil.dll", b"x")
    return buf.getvalue()


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(updates, "public_key_pem", lambda: _pem(key))
    monkeypatch.setattr(updates.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(updates, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(updates.paths, "config_file", lambda: tmp_path / ".env")
    exe = tmp_path / "FMFinance.exe"
    exe.write_bytes(b"old program")
    monkeypatch.setattr(updates, "exe_path", lambda: exe)
    monkeypatch.setattr(get_settings(), "DESKTOP_MODE", True)
    launched: list[Path] = []
    monkeypatch.setattr(updates, "_launch", lambda script: launched.append(script))
    return {"key": key, "dir": tmp_path, "launched": launched}


def upload(c: TestClient, data: bytes, name: str = "FMFinance_Update_v0.12.3.fmupdate"):
    return c.post("/api/updates/upload", files={"file": (name, data, "application/octet-stream")})


def test_version_probe_is_one_plain_line(client: TestClient) -> None:
    r = client.get("/api/health/version")
    assert r.status_code == 200 and r.text == f"fm-finance:{__version__}:ok"


def test_status_says_why_updates_are_off(auth_client: TestClient) -> None:
    s = auth_client.get("/api/updates").json()
    assert s["supported"] is False and "source" in s["reason"] and s["current_version"] == __version__


def test_only_the_platform_administrator(auth_client: TestClient, client: TestClient, setup) -> None:
    emp = auth_client.post("/api/members", json={"email": "own@example.com", "name": "Own", "role": "owner"}).json()
    login(client, "own@example.com", emp["temporary_password"])
    assert client.get("/api/updates").status_code == 403
    assert upload(client, package(setup["key"])).status_code == 403
    assert client.post("/api/updates/apply").status_code == 403


def test_good_update_is_checked_and_staged(auth_client: TestClient, setup) -> None:
    r = upload(auth_client, package(setup["key"]))
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["supported"] and st["staged"]["version"] == "0.12.3" and st["staged"]["kind"] == "upgrade"
    staged_exe = setup["dir"] / "updates" / "staged" / "FMFinance.new.exe"
    assert staged_exe.read_bytes() == EXE
    assert not (setup["dir"] / "updates" / "incoming.fmupdate").exists()
    assert auth_client.delete("/api/updates/staged").json()["staged"] is None


@pytest.mark.parametrize("make,msg", [
    (lambda k: package(Ed25519PrivateKey.generate()), "signed"),           # someone else's key
    (lambda k: package(k, tamper_exe=True), "damaged"),                  # program changed after signing
    (lambda k: package(k, version="0.11.9"), "older"),                    # going back
    (lambda k: package(k, version="0.13.0", min_version="0.12.5"), "needs version 0.12.5"),
    (lambda k: package(k, extra=True), "update file"),                    # anything extra inside
    (lambda k: b"not a zip at all", "update file"),
])
def test_bad_update_files_are_refused(auth_client: TestClient, setup, make, msg) -> None:
    r = upload(auth_client, make(setup["key"]))
    assert r.status_code == 422 and msg in r.json()["detail"], r.text
    assert auth_client.get("/api/updates").json()["staged"] is None
    assert not (setup["dir"] / "updates" / "staged" / "FMFinance.new.exe").exists()


def test_only_fmupdate_files(auth_client: TestClient, setup) -> None:
    assert upload(auth_client, package(setup["key"]), name="FMFinance.exe").status_code == 422


def test_same_version_is_a_reinstall(auth_client: TestClient, setup) -> None:
    st = upload(auth_client, package(setup["key"], version=__version__, min_version="0.0.0")).json()
    assert st["staged"]["kind"] == "reinstall"


def test_install_backs_up_and_hands_over(auth_client: TestClient, setup, monkeypatch) -> None:
    class FakeServer:
        should_exit = False

    auth_client.app.state.server = FakeServer()
    try:
        assert auth_client.post("/api/updates/apply").status_code == 409  # nothing uploaded yet
        upload(auth_client, package(setup["key"]))
        (setup["dir"] / ".env").write_text("JWT_SECRET=x\n")
        r = auth_client.post("/api/updates/apply")
        assert r.status_code == 202, r.text
        out = r.json()
        assert out["version"] == "0.12.3"
        folder = setup["dir"] / "backups" / out["backup"]
        assert (folder / ".env").read_text() == "JWT_SECRET=x\n"
        db = updates._sqlite_file()
        if db is not None:  # SQLite: a real, readable copy of the database
            copy = sqlite3.connect(str(folder / db.name))
            assert copy.execute("SELECT count(*) FROM users").fetchone()[0] >= 1
            copy.close()
        assert setup["launched"] == [setup["dir"] / "updates" / "apply_update.cmd"]
        script = setup["launched"][0].read_bytes().decode("ascii")
        assert f'set "EXE={setup["dir"] / "FMFinance.exe"}"' in script
        assert 'set "VERSION=0.12.3"' in script and "/api/health/version" in script
        assert 'findstr /x /c:"fm-finance:%VERSION%:ok"' in script
        assert ":rollback" in script and "FMFinance.previous.exe" in script
        assert "(" not in script.split("\r\n:rollback\r\n")[1].split("\r\n:notreplaced")[0]  # no blocks: paths may hold ()
        assert "\r\n" in script
    finally:
        auth_client.app.state.server = None


def test_backups_keep_the_last_five(setup) -> None:
    for i in range(7):
        (setup["dir"] / "backups" / f"before-v0.10.{i}-2026").mkdir(parents=True)
    updates.backup("0.10.9")
    names = [b["name"] for b in updates.backups()]
    assert len(names) == 5 and names[0].startswith("before-v0.10.9")


def test_result_of_the_last_update_is_shown(auth_client: TestClient, setup) -> None:
    (setup["dir"] / "updates").mkdir(exist_ok=True)
    (setup["dir"] / "updates" / "last_result.txt").write_text("status=rolled_back\nversion=0.10.2\nwhen=Sun 10/11\n")
    assert auth_client.get("/api/updates").json()["last_result"]["status"] == "rolled_back"


def test_after_start_tidies_an_installed_update(setup) -> None:
    staged = setup["dir"] / "updates" / "staged"
    staged.mkdir(parents=True)
    (staged / "manifest.json").write_text(json.dumps({"version": __version__}))
    updates.after_start()
    assert not staged.exists()


def test_make_update_tool_signs_what_the_app_accepts(tmp_path: Path, setup, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "make_update", Path(__file__).resolve().parents[2] / "packaging" / "make_update.py")
    mu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mu)  # type: ignore[union-attr]
    key_module = tmp_path / "update_key.py"
    monkeypatch.setattr(mu, "KEY_MODULE", key_module)
    key = tmp_path / "keys" / "k.pem"
    mu.cmd_keygen(type("A", (), {"key": str(key), "force": False})())
    assert key.exists() and "BEGIN PUBLIC KEY" in key_module.read_text()
    exe = tmp_path / "FMFinance.exe"
    exe.write_bytes(EXE)
    mu.cmd_build(type("A", (), {"exe": str(exe), "key": str(key), "out": str(tmp_path / "out"), "notes": "Hi",
                                "notes_file": "", "min_version": "0.12.1", "version": "0.12.2"})())
    built = tmp_path / "out" / "FMFinance_Update_v0.12.2.fmupdate"
    monkeypatch.setattr(updates, "public_key_pem", lambda: mu.public_key_in_source())
    info = updates.stage(built)
    assert info["version"] == "0.12.2" and info["notes"] == "Hi"

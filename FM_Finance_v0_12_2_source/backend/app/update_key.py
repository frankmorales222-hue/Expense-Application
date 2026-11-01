"""Public key that update files must be signed with (v0.10.1).

Written by `packaging/make_update.py keygen` on the build PC. It is a PUBLIC key (safe to keep in the
source); the matching private key stays on the build PC and is never shipped.
"""

PUBLIC_KEY_PEM: str | None = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAN0wOsF8dYcCDiEViVJHN3Mcc9NbO8Vyt1294ZPwq4dQ=
-----END PUBLIC KEY-----
"""

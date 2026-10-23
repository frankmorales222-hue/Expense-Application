"""Path resolution that works both in development and inside a PyInstaller build.

- app_dir():      folder that holds .env and logs. When frozen this is the folder
                  containing the .exe (NOT the working directory, because Windows
                  services start in C:\\Windows\\System32).
- resource_dir(): folder that holds bundled read-only resources (frontend build,
                  Alembic migrations). When frozen this is sys._MEIPASS.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _PROJECT_ROOT


def frontend_dist() -> Path:
    return resource_dir() / "frontend" / "dist"


def alembic_dir() -> Path:
    return resource_dir() / "backend" / "alembic"

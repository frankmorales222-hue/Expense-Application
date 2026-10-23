"""Administration > Updates (v0.10.1): install a signed update file from the browser. Platform administrator
only, portable desktop app only. See app/updates.py for how it works."""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from .. import __version__, audit, updates
from ..config import get_settings
from ..database import get_session_factory
from ..models import User
from ..security import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/updates", tags=["updates"])
MAX_UPLOAD = updates.MAX_EXE_BYTES + 50 * 1024 * 1024


def platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the administrator of this installation can install updates")
    return user


class UpdateStatus(BaseModel):
    current_version: str
    supported: bool
    reason: str
    exe_name: str
    folder: str
    staged: dict | None
    last_result: dict | None
    backups: list[dict]


def _status() -> UpdateStatus:
    ok, why = updates.supported()
    exe = updates.exe_path()
    return UpdateStatus(current_version=__version__, supported=ok, reason=why, exe_name=exe.name,
                        folder=str(updates.base_dir()), staged=updates.staged(), last_result=updates.last_result(),
                        backups=updates.backups())


def _audit(user: User, action: str, changes: dict) -> None:
    try:
        with get_session_factory()() as db:
            audit.record(db, entity_type="system", entity_id=user.id, action=action, user_id=user.id, changes=changes,
                         account_level=True)
            db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Could not record %s in the history", action, exc_info=True)


@router.get("", response_model=UpdateStatus)
def get_status(_: User = Depends(platform_admin)) -> UpdateStatus:
    return _status()


@router.post("/upload", response_model=UpdateStatus)
async def upload(file: UploadFile = File(...), user: User = Depends(platform_admin)) -> UpdateStatus:
    ok, why = updates.supported()
    if not ok:
        raise HTTPException(status.HTTP_409_CONFLICT, why)
    if not (file.filename or "").lower().endswith(".fmupdate"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an F&M Finance update file (.fmupdate)")
    updates.updates_dir().mkdir(parents=True, exist_ok=True)
    incoming = updates.updates_dir() / "incoming.fmupdate"
    size = 0
    try:
        with open(incoming, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The file is too large")
                out.write(chunk)
        info = updates.stage(incoming)
    except updates.UpdateError as exc:
        log.warning("Update file refused: %s", exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    finally:
        incoming.unlink(missing_ok=True)
    _audit(user, "update_uploaded", {"version": info["version"], "kind": info["kind"]})
    return _status()


@router.delete("/staged", response_model=UpdateStatus)
def discard(_: User = Depends(platform_admin)) -> UpdateStatus:
    updates.discard()
    return _status()


class ApplyOut(BaseModel):
    version: str
    backup: str


@router.post("/apply", response_model=ApplyOut, status_code=status.HTTP_202_ACCEPTED)
def apply(request: Request, user: User = Depends(platform_admin)) -> ApplyOut:
    """Back up, hand over to the helper, then stop so the program can be replaced."""
    server = getattr(request.app.state, "server", None)
    if server is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Updates can only be installed in the Windows app")
    try:
        out = updates.apply(get_settings().APP_PORT)
    except updates.UpdateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    _audit(user, "update_started", out)
    log.info("Stopping for the update to %s (requested by %s)", out["version"], user.email)
    threading.Timer(1.5, lambda: setattr(server, "should_exit", True)).start()
    return ApplyOut(**out)

"""Administration > Backups (v0.11.0)."""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from .. import audit, data_backups
from ..config import get_settings
from ..database import get_session_factory
from ..models import User
from ..security import current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backups", tags=["backups"])


def platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the administrator of this installation can manage full backups")
    return user


class BackupStatus(BaseModel):
    supported: bool
    reason: str
    folder: str
    backups: list[dict]
    last_result: dict | None


class RestoreIn(BaseModel):
    restore_settings: bool = True


class RestoreOut(BaseModel):
    backup: str
    version: str
    recovery_backup: str


def _status() -> BackupStatus:
    ok, why = data_backups.supported()
    return BackupStatus(supported=ok, reason=why, folder=str(data_backups.backup_dir()),
                        backups=data_backups.list_backups(), last_result=data_backups.last_result())


def _audit(user: User, action: str, changes: dict) -> None:
    try:
        with get_session_factory()() as db:
            audit.record(db, entity_type="system", entity_id=user.id, action=action, user_id=user.id,
                         changes=changes, account_level=True)
            db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Could not record %s in the history", action, exc_info=True)


@router.get("", response_model=BackupStatus)
def get_status(_: User = Depends(platform_admin)) -> BackupStatus:
    return _status()


@router.post("", response_model=BackupStatus, status_code=status.HTTP_201_CREATED)
def create(user: User = Depends(platform_admin)) -> BackupStatus:
    try:
        info = data_backups.create("manual")
    except data_backups.BackupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    _audit(user, "backup_created", {"name": info["name"]})
    return _status()


@router.post("/{name}/restore", response_model=RestoreOut, status_code=status.HTTP_202_ACCEPTED)
def restore(name: str, payload: RestoreIn, request: Request,
            user: User = Depends(platform_admin)) -> RestoreOut:
    server = getattr(request.app.state, "server", None)
    if server is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Restore is available in the Windows app")
    try:
        out = data_backups.begin_restore(name, restore_settings=payload.restore_settings,
                                         port=get_settings().APP_PORT)
    except data_backups.BackupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    _audit(user, "backup_restore_started", out)
    threading.Timer(1.5, lambda: setattr(server, "should_exit", True)).start()
    return RestoreOut(**out)

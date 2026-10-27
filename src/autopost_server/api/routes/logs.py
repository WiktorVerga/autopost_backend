"""Lettura dei log di esecuzione. Un log appartiene all'utente tramite il programma (e quindi il
suo account Instagram).

L'API è in sola lettura: i log li scrive il server tramite services/logs.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import InstagramAccount, Log, Program, User
from autopost_server.models.enums import LogStatus
from autopost_server.schemas.log import LogRead
from autopost_server.services.auth import get_current_user

router = APIRouter(prefix="/logs", tags=["logs"])


def _get_owned_or_404(db: Session, user: User, log_id: int) -> Log:
    log = db.get(Log, log_id)
    if log is None or log.program.instagram_account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log not found")
    return log


@router.get("", response_model=list[LogRead])
def list_logs(
    program_id: int | None = Query(None, description="Filtra per programma"),
    idea_id: int | None = Query(None, description="Filtra per idea"),
    log_status: LogStatus | None = Query(None, alias="status", description="Filtra per stato"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Log)
        .join(Log.program)
        .join(Program.instagram_account)
        .where(InstagramAccount.user_id == user.id)
    )
    if program_id is not None:
        stmt = stmt.where(Log.program_id == program_id)
    if idea_id is not None:
        stmt = stmt.where(Log.idea_id == idea_id)
    if log_status is not None:
        stmt = stmt.where(Log.status == log_status)
    # i più recenti per primi
    stmt = stmt.order_by(Log.created_at.desc(), Log.id.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{log_id}", response_model=LogRead)
def get_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, log_id)

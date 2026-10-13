"""CRUD dei programmi di pubblicazione. Un programma appartiene all'utente tramite il suo
account Instagram; la raccolta collegata deve essere dello stesso utente."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import IdeaCollection, InstagramAccount, Post, Program, User
from autopost_server.schemas.program import ProgramCreate, ProgramRead, ProgramUpdate
from autopost_server.services.auth import get_current_user

router = APIRouter(prefix="/programs", tags=["programs"])

# colonne che accettano un null esplicito in PATCH
_NULLABLE_FIELDS = {"idea_collection_id"}


def _get_owned_or_404(db: Session, user: User, program_id: int) -> Program:
    program = db.get(Program, program_id)
    if program is None or program.instagram_account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    return program


def _check_references(
    db: Session, user: User, instagram_account_id: int | None, idea_collection_id: int | None
) -> None:
    if instagram_account_id is not None:
        account = db.get(InstagramAccount, instagram_account_id)
        if account is None or account.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instagram account not found")
    if idea_collection_id is not None:
        collection = db.get(IdeaCollection, idea_collection_id)
        if collection is None or collection.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea collection not found")


def _check_active_has_collection(is_active: bool, idea_collection_id: int | None) -> None:
    # anticipa ck_program_active_needs_collection con un errore leggibile
    if is_active and idea_collection_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "An active program must have an idea collection"
        )


@router.get("", response_model=list[ProgramRead])
def list_programs(
    instagram_account_id: int | None = Query(None, description="Filtra per account Instagram"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Program).join(Program.instagram_account).where(InstagramAccount.user_id == user.id)
    if instagram_account_id is not None:
        stmt = stmt.where(Program.instagram_account_id == instagram_account_id)
    stmt = stmt.order_by(Program.id).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{program_id}", response_model=ProgramRead)
def get_program(
    program_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, program_id)


@router.post("", response_model=ProgramRead, status_code=status.HTTP_201_CREATED)
def create_program(
    payload: ProgramCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_references(db, user, payload.instagram_account_id, payload.idea_collection_id)
    _check_active_has_collection(payload.is_active, payload.idea_collection_id)
    program = Program(**payload.model_dump())
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


@router.patch("/{program_id}", response_model=ProgramRead)
def update_program(
    program_id: int,
    payload: ProgramUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = _get_owned_or_404(db, user, program_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field not in _NULLABLE_FIELDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{field}' cannot be null")
    _check_references(db, user, changes.get("instagram_account_id"), changes.get("idea_collection_id"))
    _check_active_has_collection(
        changes.get("is_active", program.is_active),
        changes.get("idea_collection_id", program.idea_collection_id),
    )
    for field, value in changes.items():
        setattr(program, field, value)
    db.commit()
    db.refresh(program)
    return program


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(
    program_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    program = _get_owned_or_404(db, user, program_id)
    # posts.program_id non ha ondelete: lo storico dei post blocca l'eliminazione
    has_posts = db.scalar(select(exists().where(Post.program_id == program.id)))
    if has_posts:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The program already has posts: deactivate it instead of deleting it"
        )
    db.delete(program)  # i log vengono eliminati a cascata
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

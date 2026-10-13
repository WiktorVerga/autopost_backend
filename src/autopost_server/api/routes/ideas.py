"""CRUD delle idee. Un'idea appartiene all'utente tramite la sua raccolta."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import Idea, IdeaCollection, Post, User
from autopost_server.schemas.idea import IdeaCreate, IdeaRead, IdeaUpdate
from autopost_server.services.auth import get_current_user

router = APIRouter(prefix="/ideas", tags=["ideas"])

# colonne che accettano un null esplicito in PATCH
_NULLABLE_FIELDS = {"category"}


def _get_owned_or_404(db: Session, user: User, idea_id: int) -> Idea:
    idea = db.get(Idea, idea_id)
    if idea is None or idea.collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea not found")
    return idea


def _check_collection_owned(db: Session, user: User, collection_id: int) -> None:
    collection = db.get(IdeaCollection, collection_id)
    if collection is None or collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea collection not found")


@router.get("", response_model=list[IdeaRead])
def list_ideas(
    idea_collection_id: int | None = Query(None, description="Filtra per raccolta"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Idea).join(Idea.collection).where(IdeaCollection.user_id == user.id)
    if idea_collection_id is not None:
        stmt = stmt.where(Idea.idea_collection_id == idea_collection_id)
    stmt = stmt.order_by(Idea.id).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{idea_id}", response_model=IdeaRead)
def get_idea(
    idea_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, idea_id)


@router.post("", response_model=IdeaRead, status_code=status.HTTP_201_CREATED)
def create_idea(
    payload: IdeaCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_collection_owned(db, user, payload.idea_collection_id)
    idea = Idea(**payload.model_dump())
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


@router.patch("/{idea_id}", response_model=IdeaRead)
def update_idea(
    idea_id: int,
    payload: IdeaUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idea = _get_owned_or_404(db, user, idea_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field not in _NULLABLE_FIELDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{field}' cannot be null")
    if "idea_collection_id" in changes:
        # spostare un'idea è consentito solo verso una raccolta dello stesso utente
        _check_collection_owned(db, user, changes["idea_collection_id"])
    for field, value in changes.items():
        setattr(idea, field, value)
    db.commit()
    db.refresh(idea)
    return idea


@router.delete("/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_idea(
    idea_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idea = _get_owned_or_404(db, user, idea_id)
    # posts.idea_id non ha ondelete: lo storico dei post blocca l'eliminazione
    has_posts = db.scalar(select(exists().where(Post.idea_id == idea.id)))
    if has_posts:
        raise HTTPException(status.HTTP_409_CONFLICT, "The idea already has associated posts")
    db.delete(idea)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""CRUD dei post. Un post appartiene all'utente tramite il programma (e quindi il suo account
Instagram); l'idea collegata deve essere dello stesso utente.

Lo stato e i dati di pubblicazione li gestisce la pipeline: il client crea post pending e può
ritoccarne testo e hashtag finché non sono pubblicati.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import Idea, InstagramAccount, Post, Program, User
from autopost_server.models.enums import PostStatus
from autopost_server.schemas.post import PostCreate, PostRead, PostUpdate
from autopost_server.services.auth import get_current_user

router = APIRouter(prefix="/posts", tags=["posts"])

# colonne che accettano un null esplicito in PATCH
_NULLABLE_FIELDS = {"caption"}


def _get_owned_or_404(db: Session, user: User, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None or post.program.instagram_account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return post


def _check_references(db: Session, user: User, program_id: int, idea_id: int) -> None:
    program = db.get(Program, program_id)
    if program is None or program.instagram_account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Program not found")
    idea = db.get(Idea, idea_id)
    if idea is None or idea.collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea not found")


def _check_not_published(post: Post) -> None:
    # un post pubblicato è già su Instagram: modificarlo o eliminarlo qui lo disallineerebbe
    if post.status == PostStatus.PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "The post is already published")


@router.get("", response_model=list[PostRead])
def list_posts(
    program_id: int | None = Query(None, description="Filtra per programma"),
    idea_id: int | None = Query(None, description="Filtra per idea"),
    post_status: PostStatus | None = Query(None, alias="status", description="Filtra per stato"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Post)
        .join(Post.program)
        .join(Program.instagram_account)
        .where(InstagramAccount.user_id == user.id)
    )
    if program_id is not None:
        stmt = stmt.where(Post.program_id == program_id)
    if idea_id is not None:
        stmt = stmt.where(Post.idea_id == idea_id)
    if post_status is not None:
        stmt = stmt.where(Post.status == post_status)
    # i più recenti per primi
    stmt = stmt.order_by(Post.created_at.desc(), Post.id.desc()).offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.get("/{post_id}", response_model=PostRead)
def get_post(
    post_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, post_id)


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_references(db, user, payload.program_id, payload.idea_id)
    post = Post(**payload.model_dump(), status=PostStatus.PENDING)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.patch("/{post_id}", response_model=PostRead)
def update_post(
    post_id: int,
    payload: PostUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = _get_owned_or_404(db, user, post_id)
    _check_not_published(post)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field not in _NULLABLE_FIELDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{field}' cannot be null")
    for field, value in changes.items():
        setattr(post, field, value)
    db.commit()
    db.refresh(post)
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = _get_owned_or_404(db, user, post_id)
    _check_not_published(post)
    db.delete(post)  # le slide vengono eliminate a cascata
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""CRUD delle raccolte di idee: è il modello da seguire per le altre risorse.

Convenzioni:
- un router per risorsa, con prefix e tag, registrato in main.py;
- schemi separati per Create / Update (parziale) / Read in schemas/<risorsa>.py;
- ogni endpoint richiede l'utente autenticato e lavora solo sulle sue risorse;
- una risorsa di un altro utente risponde 404, non 403, per non rivelarne l'esistenza;
- i controlli di integrità che il DB rifiuterebbe diventano errori HTTP espliciti (409).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from autopost_server.db import get_db
from autopost_server.models import IdeaCollection, Program, User
from autopost_server.schemas.idea_collection import (
    IdeaCollectionCreate,
    IdeaCollectionRead,
    IdeaCollectionUpdate,
)
from autopost_server.services.auth import get_current_user

router = APIRouter(prefix="/idea-collections", tags=["idea collections"])


def _get_owned_or_404(db: Session, user: User, collection_id: int) -> IdeaCollection:
    collection = db.get(IdeaCollection, collection_id)
    if collection is None or collection.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea collection not found")
    return collection


@router.get("", response_model=list[IdeaCollectionRead])
def list_collections(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(IdeaCollection)
        .where(IdeaCollection.user_id == user.id)
        .order_by(IdeaCollection.id)
        .offset(skip)
        .limit(limit)
    )
    return db.scalars(stmt).all()


@router.get("/{collection_id}", response_model=IdeaCollectionRead)
def get_collection(
    collection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, collection_id)


@router.post("", response_model=IdeaCollectionRead, status_code=status.HTTP_201_CREATED)
def create_collection(
    payload: IdeaCollectionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = IdeaCollection(**payload.model_dump(), user_id=user.id)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.patch("/{collection_id}", response_model=IdeaCollectionRead)
def update_collection(
    collection_id: int,
    payload: IdeaCollectionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = _get_owned_or_404(db, user, collection_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        # name è NOT NULL: un null esplicito non è un aggiornamento valido
        if value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{field}' cannot be null")
        setattr(collection, field, value)
    db.commit()
    db.refresh(collection)
    return collection


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(
    collection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = _get_owned_or_404(db, user, collection_id)
    # programs.idea_collection_id va a NULL, ma un programma attivo deve averne una
    in_use = db.scalar(
        select(exists().where(Program.idea_collection_id == collection.id, Program.is_active))
    )
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "The collection is used by an active program")
    db.delete(collection)  # le idee vengono eliminate a cascata
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

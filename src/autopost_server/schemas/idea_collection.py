from pydantic import BaseModel, ConfigDict, Field


class IdeaCollectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class IdeaCollectionCreate(IdeaCollectionBase):
    # niente user_id: il proprietario è sempre l'utente autenticato, mai il client
    name: str = Field(min_length=1, max_length=100)


class IdeaCollectionUpdate(BaseModel):
    """Aggiornamento parziale: solo i campi inviati vengono modificati."""

    name: str | None = Field(default=None, min_length=1, max_length=100)


class IdeaCollectionRead(IdeaCollectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int

from pydantic import BaseModel, ConfigDict, Field


class IdeaBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=100)
    idea_collection_id: int


class IdeaCreate(IdeaBase):
    pass


class IdeaUpdate(BaseModel):
    """Aggiornamento parziale: solo i campi inviati vengono modificati."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, max_length=100)
    idea_collection_id: int | None = None


class IdeaRead(IdeaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int

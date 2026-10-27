from datetime import datetime

from pydantic import BaseModel, ConfigDict

from autopost_server.models.enums import PostStatus


class PostBase(BaseModel):
    caption: str | None = None
    idea_id: int
    program_id: int


class PostCreate(PostBase):
    # niente status: un post nasce sempre pending, l'avanzamento è compito dello scheduler
    pass


class PostUpdate(BaseModel):
    """Aggiornamento parziale: solo i campi inviati vengono modificati."""

    caption: str | None = None


class SlideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    public_url: str | None


class PostRead(PostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # gestiti dalla pipeline di generazione e pubblicazione, non modificabili dal client
    status: PostStatus
    content: dict | None
    container_id: str | None
    media_id: str | None
    permalink: str | None
    created_at: datetime
    published_at: datetime | None
    slides: list[SlideRead]


class PostContentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: PostStatus
    slides: list[SlideRead]

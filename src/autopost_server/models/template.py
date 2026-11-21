from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.enums import PostTypeName


class Template(Base):
    """Template di un utente: la definizione JSON inviata dal client e il template Jinja2 che il
    server ne genera a partire dalla base del suo tipo di post (services/templates.compile_definition)."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # la versione del tipo di post (una riga di post_types) da cui è stato generato jinja_content:
    # le righe di post_types non si eliminano finché un template le usa
    type_id: Mapped[int] = mapped_column(ForeignKey("post_types.id", ondelete="RESTRICT"), index=True)
    definition_json: Mapped[dict] = mapped_column(JSONB)
    jinja_content: Mapped[str] = mapped_column(Text)
    # prima slide con i dati d'esempio della base, come data URL JPEG (data:image/jpeg;base64,...)
    # generata a ogni nuova definizione; NULL se il rendering è fallito
    preview_image: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="templates")
    type: Mapped[PostType] = relationship(back_populates="templates")
    programs: Mapped[list[Program]] = relationship(back_populates="template")
    # passive_deletes="all": l'ORM non azzera posts.template_id eliminando il template, così
    # decide il vincolo RESTRICT del DB
    posts: Mapped[list[Post]] = relationship(back_populates="template", passive_deletes="all")

    @property
    def base_version(self) -> int:
        """La versione della base da cui è stato generato il template: quella del suo tipo."""
        return self.type.version

    @property
    def type_name(self) -> PostTypeName:
        return self.type.name

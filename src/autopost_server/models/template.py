from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.enums import BaseTemplate


class Template(Base):
    """Template di un utente: la definizione JSON inviata dal client e il template Jinja2 che il
    server ne genera a partire dal file HTML di base (services/templates.compile_definition)."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # salvato come testo ("plain"), non come enum PostgreSQL: aggiungere una base all'enum
    # non richiede una migrazione
    base_template: Mapped[BaseTemplate] = mapped_column(
        Enum(
            BaseTemplate,
            name="base_template",
            native_enum=False,
            length=50,
            values_callable=lambda e: [m.key for m in e],
        )
    )
    # versione della base (schema_version del suo schema) da cui è stato generato jinja_content
    base_version: Mapped[int]
    definition_json: Mapped[dict] = mapped_column(JSONB)
    jinja_content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="templates")
    programs: Mapped[list["Program"]] = relationship(back_populates="template")

from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from autopost_server.models.column_types import pg_enum
from sqlalchemy.orm import Mapped
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


from autopost_server.db import Base
from autopost_server.models.enums import TemplateFormat


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    format: Mapped[TemplateFormat] = mapped_column(
        pg_enum(TemplateFormat, "template_format"), default=TemplateFormat.CAROUSEL
    )
    html_content: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    width: Mapped[int] = mapped_column(server_default=text("1080"))
    height: Mapped[int] = mapped_column(server_default=text("1350"))
    version: Mapped[int] = mapped_column(server_default=text("1"))
    # soft delete: "cancellare" = is_active False, così i post vecchi restano coerenti
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    user: Mapped["User"] = relationship(back_populates="templates")

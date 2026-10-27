from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base
from autopost_server.models.column_types import pg_enum
from autopost_server.models.enums import PostStatus


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        # un solo post per idea e programma: un'esecuzione fallita riprende il post esistente
        UniqueConstraint("program_id", "idea_id", name="uq_post_program_idea"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[PostStatus] = mapped_column(
        pg_enum(PostStatus, "post_status"), default=PostStatus.PENDING
    )
    caption: Mapped[str | None] = mapped_column(Text)
    # contenuto generato da Claude (CarouselContent): salvato per non rigenerarlo dopo un errore
    content: Mapped[dict | None] = mapped_column(JSONB)
    container_id: Mapped[str | None] = mapped_column(String(64))
    media_id: Mapped[str | None] = mapped_column(String(64))
    permalink: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"))
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"))

    idea: Mapped["Idea"] = relationship(back_populates="posts")
    program: Mapped["Program"] = relationship(back_populates="posts")
    slides: Mapped[list["Slide"]] = relationship(
        back_populates="post",
        order_by="Slide.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Slide(Base):
    __tablename__ = "slides"
    __table_args__ = (UniqueConstraint("post_id", "position", name="uq_slide_post_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int]
    local_path: Mapped[str] = mapped_column(String(500))
    public_url: Mapped[str | None] = mapped_column(String(1000))
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))

    post: Mapped["Post"] = relationship(back_populates="slides")
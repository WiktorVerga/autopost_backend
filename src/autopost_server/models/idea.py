from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autopost_server.db import Base


class IdeaCollection(Base):
    __tablename__ = "idea_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    user: Mapped["User"] = relationship(back_populates="idea_collections")
    ideas: Mapped[list["Idea"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", passive_deletes=True
    )
    programs: Mapped[list["Program"]] = relationship(back_populates="idea_collection")


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    idea_collection_id: Mapped[int] = mapped_column(
        ForeignKey("idea_collections.id", ondelete="CASCADE")
    )

    collection: Mapped["IdeaCollection"] = relationship(back_populates="ideas")
    posts: Mapped[list["Post"]] = relationship(back_populates="idea")


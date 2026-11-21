"""Le basi dei tipi di post (tabella post_types, popolata da seed_post_types)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autopost_server.models import PostType
from autopost_server.models.enums import PostTypeName


def latest_post_type(db: Session, name: PostTypeName) -> PostType | None:
    """L'ultima versione della base di un tipo di post."""
    stmt = select(PostType).where(PostType.name == name).order_by(PostType.version.desc()).limit(1)
    return db.scalar(stmt)


def latest_post_types(db: Session) -> list[PostType]:
    """L'ultima versione di ogni tipo di post presente, in ordine di nome."""
    latest = (
        select(PostType.name, func.max(PostType.version).label("version"), )
        .group_by(PostType.name)
        .subquery()
    )
    stmt = (
        select(PostType)
        .join(latest, (PostType.name == latest.c.name) & (PostType.version == latest.c.version))
        .order_by(PostType.name)
    )
    return list(db.scalars(stmt))

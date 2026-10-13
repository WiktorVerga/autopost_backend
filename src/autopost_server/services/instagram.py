from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.config import settings
from autopost_server.integrations import instagram
from autopost_server.models import InstagramAccount, User


def link_instagram_account(
    db: Session, user: User, linked: instagram.LinkedInstagramAccount
) -> InstagramAccount:
    """Crea o aggiorna l'account Instagram dell'utente dopo il login Instagram.

    Ricollegare un proprio account ne aggiorna username e token; un account già collegato
    da un altro utente risponde 409.
    """
    account = db.scalar(select(InstagramAccount).where(InstagramAccount.ig_user_id == linked.ig_user_id))
    if account is not None and account.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Instagram account already linked to another user")
    if account is None:
        account = InstagramAccount(ig_user_id=linked.ig_user_id, user_id=user.id)
        db.add(account)
    account.handle = linked.username
    _store_token(account, linked.token)
    db.commit()
    db.refresh(account)
    return account


async def refresh_expiring_tokens(db: Session, within: timedelta = timedelta(days=7)) -> list[str]:
    """Rinnova i token che scadono entro `within`; pensato per un job periodico dello scheduler.

    Restituisce gli handle per cui il rinnovo è fallito (token già scaduto o revocato:
    serve un nuovo login dell'utente).
    """
    now = datetime.now(UTC)
    accounts = db.scalars(
        select(InstagramAccount).where(
            InstagramAccount.token_expires_at.is_not(None),
            InstagramAccount.token_expires_at > now,
            InstagramAccount.token_expires_at <= now + within,
            # Instagram rinnova solo token con almeno 24 ore
            InstagramAccount.updated_at <= now - timedelta(hours=24),
        )
    ).all()
    failed = []
    for account in accounts:
        try:
            token = await instagram.refresh_access_token(account.access_token)
        except instagram.InstagramError:
            failed.append(account.handle)
            continue
        _store_token(account, token)
        db.commit()
    return failed


def _store_token(account: InstagramAccount, token: instagram.InstagramToken) -> None:
    account.access_token = token.access_token
    account.token_expires_at = token.expires_at
    account.api_version = settings.instagram_graph_api_version

"""Account Instagram professionali collegati con il login di Instagram (Instagram API con
login di Instagram, graph.instagram.com).

Il collegamento non si crea a mano: il frontend chiede l'URL del dialog Instagram (autenticato),
ci manda il browser, e Instagram torna sul callback con code e state. Lo state firmato porta
l'id utente, perché il redirect del browser non ha l'header Authorization.
Il token di accesso è solo lato server: non esce mai nelle risposte.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from autopost_server.config import settings
from autopost_server.db import get_db
from autopost_server.integrations import instagram
from autopost_server.models import InstagramAccount, Program, User
from autopost_server.schemas.instagram_account import AuthorizationUrl, InstagramAccountRead
from autopost_server.services.auth import create_oauth_state, get_current_user, read_oauth_state
from autopost_server.services.instagram import link_instagram_account

router = APIRouter(prefix="/instagram-accounts", tags=["instagram accounts"])

_STATE_PURPOSE = "instagram_link"


def _get_owned_or_404(db: Session, user: User, account_id: int) -> InstagramAccount:
    account = db.get(InstagramAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instagram account not found")
    return account


def _redirect_uri(request: Request) -> str:
    # deve essere identico nel dialog e nello scambio del code
    return settings.instagram_redirect_uri or str(request.url_for("instagram_callback"))


def _require_instagram_configured() -> None:
    if not instagram.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Instagram integration not configured")


@router.get("/oauth/login", response_model=AuthorizationUrl)
def instagram_login(request: Request, user: User = Depends(get_current_user)):
    """URL del dialog di login Instagram: il frontend ci reindirizza il browser."""
    _require_instagram_configured()
    state = create_oauth_state(user.id, _STATE_PURPOSE)
    return AuthorizationUrl(authorization_url=instagram.authorization_url(_redirect_uri(request), state))


@router.get("/oauth/callback", name="instagram_callback", response_model=InstagramAccountRead)
async def instagram_callback(
    request: Request,
    state: str,
    code: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
):
    _require_instagram_configured()
    user = db.get(User, read_oauth_state(state, _STATE_PURPOSE))
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state")
    if code is None:
        # l'utente ha annullato o negato le autorizzazioni nel dialog
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Instagram login cancelled: {error_description or 'no code'}"
        )

    try:
        linked = await instagram.fetch_linked_account(code, _redirect_uri(request))
    except instagram.InstagramError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Instagram login failed: {e}")
    account = link_instagram_account(db, user, linked)

    if settings.frontend_url:
        fragment = urlencode({"instagram_account_id": account.id})
        return RedirectResponse(f"{settings.frontend_url}#{fragment}")
    return account


@router.get("", response_model=list[InstagramAccountRead])
def list_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(InstagramAccount)
        .where(InstagramAccount.user_id == user.id)
        .order_by(InstagramAccount.id)
        .offset(skip)
        .limit(limit)
    )
    return db.scalars(stmt).all()


@router.get("/{account_id}", response_model=InstagramAccountRead)
def get_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, user, account_id)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_owned_or_404(db, user, account_id)
    # programs.instagram_account_id non ha ondelete: i programmi vanno eliminati prima
    in_use = db.scalar(select(exists().where(Program.instagram_account_id == account.id)))
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "The account is used by one or more programs")
    db.delete(account)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

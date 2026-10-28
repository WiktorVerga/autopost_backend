from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopost_server.config import settings
from autopost_server.db import get_db
from autopost_server.models import User

_bearer = HTTPBearer(auto_error=False)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        domain=settings.frontend_domain
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.auth_cookie_name, httponly=True, secure=settings.auth_cookie_secure, samesite="lax"
    )


def _check_cookie_origin(request: Request) -> None:
    """Difesa CSRF per le richieste autenticate dal cookie, che il browser allega da solo.

    SameSite=Lax blocca già i siti esterni; qui si rifiutano anche le origini dello stesso sito
    (es. un'altra porta di localhost). Le richieste che modificano dati devono arrivare dal
    frontend o dal server stesso (Swagger).
    """
    if request.method in _SAFE_METHODS:
        return
    allowed = {f"{request.url.scheme}://{request.url.netloc}", settings.frontend_origin}
    if request.headers.get("origin") not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin not allowed")


def create_oauth_state(user_id: int, purpose: str) -> str:
    """State OAuth firmato che porta l'utente attraverso il redirect del provider.

    Serve quando l'utente è già autenticato: il redirect del browser verso il callback non
    porta l'header Authorization, quindi l'identità viaggia nello state.
    """
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "purpose": purpose, "iat": now, "exp": now + timedelta(minutes=10)}
    return jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)


def read_oauth_state(state: str, purpose: str) -> int:
    """Restituisce l'id utente dello state, o solleva 400 se non valido, scaduto o di altro scopo."""
    try:
        payload = jwt.decode(
            state, settings.jwt_secret_key.get_secret_value(), algorithms=[settings.jwt_algorithm]
        )
        if payload["purpose"] != purpose:
            raise ValueError
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state")


def upsert_google_user(db: Session, userinfo: dict) -> User:
    """Trova l'utente per google_sub (o per email, collegandolo) oppure lo crea."""
    sub = userinfo["sub"]
    email = userinfo["email"]
    name = userinfo.get("name") or email.split("@")[0]

    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name[:100])
        db.add(user)
    user.google_sub = sub
    user.email = email
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Utente del JWT nell'header Authorization (client API, Swagger) o nel cookie (browser)."""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get(settings.auth_cookie_name)
        if token is None:
            raise unauthorized
        _check_cookie_origin(request)
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    # uno state OAuth è firmato con la stessa chiave ma passa negli URL: non è un token di accesso
    if "purpose" in payload:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user

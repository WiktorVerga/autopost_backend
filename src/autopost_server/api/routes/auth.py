from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from autopost_server.config import settings
from autopost_server.db import get_db
from autopost_server.integrations.google import oauth
from autopost_server.models import User
from autopost_server.schemas.auth import TokenResponse, UserRead
from autopost_server.services.auth import (
    clear_auth_cookie,
    create_access_token,
    get_current_user,
    set_auth_cookie,
    upsert_google_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = settings.google_redirect_uri or str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback", response_model=TokenResponse)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Google login failed: {e.error}")

    userinfo = token.get("userinfo")
    if not userinfo or not userinfo.get("email_verified"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google email not verified")

    user = upsert_google_user(db, userinfo)
    access_token = create_access_token(user.id)

    # il token resta nel cookie HttpOnly: il JavaScript del frontend non lo vede mai
    if settings.frontend_url:
        response = RedirectResponse(settings.frontend_url)
        set_auth_cookie(response, access_token)
        return response
    # senza frontend (sviluppo) il token esce anche nel JSON, per usarlo come Bearer in Swagger
    response = JSONResponse(TokenResponse(access_token=access_token).model_dump())
    set_auth_cookie(response, access_token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout():
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookie(response)
    return response


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user

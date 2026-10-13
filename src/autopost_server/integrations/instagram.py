"""Instagram API con login di Instagram (graph.instagram.com), quanto basta per collegare
un account professionale e tenerne valido il token.

Giro completo:
1. dialog su instagram.com/oauth/authorize con gli scope instagram_business_*;
2. code -> token di breve durata (1 ora) su api.instagram.com;
3. token breve -> token di lunga durata (60 giorni) su graph.instagram.com;
4. /me restituisce user_id (l'ID dell'account professionale, quello usato per pubblicare) e username.
Il token di lunga durata va rinnovato prima della scadenza con refresh_access_token.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx2

from autopost_server.config import settings

_TIMEOUT = httpx2.Timeout(10.0)
_PUBLISH_SCOPE = "instagram_business_content_publish"


class InstagramError(Exception):
    """Risposta di errore delle API Instagram."""


@dataclass(frozen=True)
class InstagramToken:
    access_token: str
    expires_at: datetime


@dataclass(frozen=True)
class LinkedInstagramAccount:
    ig_user_id: str
    username: str
    token: InstagramToken


def is_configured() -> bool:
    return bool(settings.instagram_app_id and settings.instagram_app_secret)


def _graph_url(path: str) -> str:
    return f"https://graph.instagram.com/{settings.instagram_graph_api_version}/{path.lstrip('/')}"


def authorization_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.instagram_app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": settings.instagram_scopes,
        "state": state,
    }
    return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"


async def _request(client: httpx2.AsyncClient, method: str, url: str, **kwargs) -> dict:
    try:
        response = await client.request(method, url, **kwargs)
    except httpx2.HTTPError as e:
        raise InstagramError(f"Instagram API unreachable: {e}") from e
    try:
        data = response.json()
    except ValueError as e:
        raise InstagramError(f"Invalid response from Instagram API (HTTP {response.status_code})") from e
    if response.is_error or "error" in data or "error_message" in data:
        # graph.instagram.com usa {"error": {"message"}}, api.instagram.com {"error_message"}
        error = data.get("error")
        message = error.get("message") if isinstance(error, dict) else data.get("error_message")
        raise InstagramError(message or f"HTTP {response.status_code}")
    return data


def _long_lived(data: dict) -> InstagramToken:
    expires_at = datetime.now(UTC) + timedelta(seconds=int(data["expires_in"]))
    return InstagramToken(data["access_token"], expires_at)


async def fetch_linked_account(code: str, redirect_uri: str) -> LinkedInstagramAccount:
    """Scambia il code e restituisce l'account autorizzato con il suo token di lunga durata."""
    app_secret = settings.instagram_app_secret.get_secret_value()
    async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
        short_lived = await _request(
            client,
            "POST",
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.instagram_app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                # Instagram aggiunge "#_" in coda al code nel redirect
                "code": code.removesuffix("#_"),
            },
        )
        # la risposta è {"data": [{...}]}; versioni precedenti la davano senza involucro
        short_lived = short_lived.get("data", [short_lived])[0]
        permissions = short_lived.get("permissions")
        if permissions is not None and _PUBLISH_SCOPE not in permissions:
            raise InstagramError(f"Permission {_PUBLISH_SCOPE} not granted")

        token = _long_lived(
            await _request(
                client,
                "GET",
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": app_secret,
                    "access_token": short_lived["access_token"],
                },
            )
        )
        me = await _request(
            client,
            "GET",
            _graph_url("me"),
            params={"fields": "user_id,username", "access_token": token.access_token},
        )
    return LinkedInstagramAccount(str(me["user_id"]), me["username"], token)


async def refresh_access_token(access_token: str) -> InstagramToken:
    """Rinnova un token di lunga durata per altri 60 giorni.

    Il token deve avere almeno 24 ore e non essere scaduto: uno scaduto richiede un nuovo login.
    """
    async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
        data = await _request(
            client,
            "GET",
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": access_token},
        )
    return _long_lived(data)

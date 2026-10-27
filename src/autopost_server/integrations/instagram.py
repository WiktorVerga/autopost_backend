"""Instagram API con login di Instagram (graph.instagram.com), quanto basta per collegare
un account professionale, tenerne valido il token e pubblicarci i post.

Giro completo:
1. dialog su instagram.com/oauth/authorize con gli scope instagram_business_*;
2. code -> token di breve durata (1 ora) su api.instagram.com;
3. token breve -> token di lunga durata (60 giorni) su graph.instagram.com;
4. /me restituisce user_id (l'ID dell'account professionale, quello usato per pubblicare) e username.
Il token di lunga durata va rinnovato prima della scadenza con refresh_access_token.
"""

import asyncio
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


# --- Pubblicazione ---------------------------------------------------------------------------
# Un carosello si pubblica in tre passi: un container per immagine (is_carousel_item), il
# container del carosello con i figli e la caption, poi media_publish sul container pronto.
# Instagram scarica le immagini dagli URL: devono essere JPEG pubblici.

CAROUSEL_MAX_ITEMS = 10
_STATUS_POLL_SECONDS = 3
_STATUS_POLL_ATTEMPTS = 20


async def _create_container(
    client: httpx2.AsyncClient, ig_user_id: str, access_token: str, **fields
) -> str:
    data = await _request(
        client,
        "POST",
        _graph_url(f"{ig_user_id}/media"),
        data={**fields, "access_token": access_token},
    )
    return str(data["id"])


async def _wait_until_finished(
    client: httpx2.AsyncClient, container_id: str, access_token: str
) -> None:
    """Attende che Instagram abbia elaborato il container (status_code FINISHED)."""
    for _ in range(_STATUS_POLL_ATTEMPTS):
        data = await _request(
            client,
            "GET",
            _graph_url(container_id),
            params={"fields": "status_code,status", "access_token": access_token},
        )
        code = data.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Container {container_id} {code}: {data.get('status')}")
        await asyncio.sleep(_STATUS_POLL_SECONDS)
    raise InstagramError(f"Container {container_id} not ready after waiting")


async def create_post_container(
    ig_user_id: str, access_token: str, image_urls: list[str], caption: str | None
) -> str:
    """Crea il container del post, pronto da pubblicare: carosello o, con un'immagine, singolo."""
    if not image_urls:
        raise InstagramError("No images to publish")
    if len(image_urls) > CAROUSEL_MAX_ITEMS:
        raise InstagramError(f"A carousel has at most {CAROUSEL_MAX_ITEMS} images")

    caption_field = {"caption": caption} if caption else {}
    async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
        if len(image_urls) == 1:
            container_id = await _create_container(
                client, ig_user_id, access_token, image_url=image_urls[0], **caption_field
            )
        else:
            children = []
            for url in image_urls:
                child = await _create_container(
                    client, ig_user_id, access_token, image_url=url, is_carousel_item="true"
                )
                await _wait_until_finished(client, child, access_token)
                children.append(child)
            container_id = await _create_container(
                client,
                ig_user_id,
                access_token,
                media_type="CAROUSEL",
                children=",".join(children),
                **caption_field,
            )
        await _wait_until_finished(client, container_id, access_token)
    return container_id


async def publish_container(ig_user_id: str, access_token: str, container_id: str) -> str:
    """Pubblica il container e restituisce l'id del media pubblicato."""
    async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
        data = await _request(
            client,
            "POST",
            _graph_url(f"{ig_user_id}/media_publish"),
            data={"creation_id": container_id, "access_token": access_token},
        )
    return str(data["id"])


async def fetch_permalink(media_id: str, access_token: str) -> str:
    async with httpx2.AsyncClient(timeout=_TIMEOUT) as client:
        data = await _request(
            client,
            "GET",
            _graph_url(media_id),
            params={"fields": "permalink", "access_token": access_token},
        )
    return data["permalink"]

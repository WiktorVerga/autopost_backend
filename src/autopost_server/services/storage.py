"""Pubblicazione delle slide renderizzate su un URL pubblico, da cui Instagram le scarica.

Con Cloudflare R2 configurato (settings.r2_*) le immagini vengono caricate nel bucket sotto
posts/<post_id>/ e l'URL è {r2_public_url}/<chiave>. Altrimenti si ripiega sul server stesso,
che le serve da /media (vedi main.py) e richiede settings.public_base_url.

Il nome dell'oggetto contiene l'hash del file: un nuovo rendering produce URL nuovi, così né la
cache di Cloudflare né Instagram possono servire una versione vecchia della slide.

Funzioni sincrone: dal codice asincrono vanno chiamate con asyncio.to_thread.
"""

import hashlib
from functools import cache
from pathlib import Path
from urllib.parse import quote

import boto3

from autopost_server.config import settings


class StorageError(Exception):
    pass


@cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
        region_name="auto",
    )


def _prefix(post_id: int) -> str:
    return f"posts/{post_id}/"


def _key(post_id: int, path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"{_prefix(post_id)}{path.stem}-{digest}{path.suffix}"


def _local_url(path: Path) -> str | None:
    """URL di un file in settings.media_dir servito da /media; None senza public_base_url."""
    if not settings.public_base_url:
        return None
    relative = path.resolve().relative_to(settings.media_dir.resolve())
    return f"{settings.public_base_url.rstrip('/')}/media/{quote(relative.as_posix())}"


def upload_slide(post_id: int, path: Path) -> str | None:
    """Carica la slide del post e ne restituisce l'URL pubblico."""
    if not settings.r2_enabled:
        return _local_url(path)

    key = _key(post_id, path)
    try:
        _client().upload_file(
            str(path), settings.r2_bucket, key, ExtraArgs={"ContentType": "image/jpeg"}
        )
    except Exception as e:
        raise StorageError(f"Upload of {path.name} to R2 failed: {e}") from e
    return f"{settings.r2_public_url.rstrip('/')}/{quote(key)}"


def delete_old_slides(post_id: int, current: list[Path]) -> None:
    """Elimina dal bucket le slide del post che non sono tra quelle correnti."""
    if not settings.r2_enabled:
        return

    keep = {_key(post_id, path) for path in current}
    client = _client()
    try:
        listing = client.list_objects_v2(Bucket=settings.r2_bucket, Prefix=_prefix(post_id))
        old = [o["Key"] for o in listing.get("Contents", []) if o["Key"] not in keep]
        if old:
            client.delete_objects(
                Bucket=settings.r2_bucket,
                Delete={"Objects": [{"Key": k} for k in old], "Quiet": True},
            )
    except Exception as e:
        raise StorageError(f"Cleanup of old slides on R2 failed: {e}") from e

"""Archiviazione delle slide renderizzate su Amazon S3.

Il bucket (privato) prende il posto dei file salvati sul server: dopo il rendering ogni slide
viene caricata sotto posts/<post_id>/slide-<n>.jpg e nel DB si salva solo la chiave
(Slide.storage_key). Quando serve un URL, ad esempio per far scaricare l'immagine a Instagram
alla pubblicazione, se ne genera uno pre-firmato a scadenza (settings.s3_presigned_url_expires).

Funzioni sincrone (upload e cancellazione fanno richieste di rete): dal codice asincrono vanno
chiamate con asyncio.to_thread. presigned_url invece firma in locale, senza richieste.
"""

from functools import cache
from pathlib import Path

import boto3
from botocore.config import Config

from autopost_server.config import settings

# Instagram pubblica solo immagini JPEG
_CONTENT_TYPE = "image/jpeg"


class StorageError(Exception):
    pass


@cache
def _client():
    # senza credenziali in settings boto3 usa la propria catena (variabili AWS_*, ~/.aws, ruolo IAM)
    credentials = {}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        credentials = {
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key.get_secret_value(),
        }
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
        **credentials,
    )


def _bucket() -> str:
    if not settings.s3_bucket:
        raise StorageError("S3 is not configured: set S3_BUCKET")
    return settings.s3_bucket


def _prefix(post_id: int) -> str:
    return f"posts/{post_id}/"


def slide_key(post_id: int, position: int) -> str:
    """Chiave S3 della slide in posizione `position` (da 0), es. posts/123/slide-1.jpg."""
    return f"{_prefix(post_id)}slide-{position + 1}.jpg"


def upload_slide(post_id: int, position: int, path: Path) -> str:
    """Carica su S3 la slide del post e ne restituisce la chiave."""
    key = slide_key(post_id, position)
    try:
        _client().upload_file(str(path), _bucket(), key, ExtraArgs={"ContentType": _CONTENT_TYPE})
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Upload of {path.name} to S3 failed: {e}") from e
    return key


def delete_old_slides(post_id: int, current: list[str]) -> None:
    """Elimina dal bucket le slide del post che non sono tra le chiavi correnti.

    Un rendering precedente può aver avuto più slide: le sue chiavi in eccesso vanno rimosse.
    """
    keep = set(current)
    client = _client()
    try:
        listing = client.list_objects_v2(Bucket=_bucket(), Prefix=_prefix(post_id))
        old = [o["Key"] for o in listing.get("Contents", []) if o["Key"] not in keep]
        if old:
            client.delete_objects(
                Bucket=_bucket(),
                Delete={"Objects": [{"Key": k} for k in old], "Quiet": True},
            )
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Cleanup of old slides on S3 failed: {e}") from e


def presigned_url(key: str) -> str:
    """URL pre-firmato per scaricare l'oggetto, valido settings.s3_presigned_url_expires secondi."""
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": key},
            ExpiresIn=settings.s3_presigned_url_expires,
        )
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Signing the URL of {key} failed: {e}") from e

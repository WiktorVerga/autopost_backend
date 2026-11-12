"""Archiviazione delle slide renderizzate su Cloudflare R2.

Il bucket (privato) prende il posto dei file salvati sul server: dopo il rendering ogni slide
viene caricata sotto posts/<post_id>/slide-<n>.jpg e nel DB si salva solo la chiave
(Slide.storage_key). Quando serve un URL, per l'anteprima nel frontend o per far scaricare
l'immagine a Instagram alla pubblicazione, se ne genera uno pre-firmato a scadenza
(settings.r2_presigned_url_expires).

R2 espone un'API compatibile con S3, quindi si usa boto3 puntato all'endpoint dell'account.

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
    # le eccezioni non vengono messe in cache: se la configurazione manca si riprova alla
    # chiamata successiva
    if not (settings.r2_endpoint and settings.r2_access_key_id and settings.r2_secret_access_key):
        raise StorageError(
            "R2 is not configured: set R2_ACCOUNT_ID (or R2_ENDPOINT_URL), R2_ACCESS_KEY_ID "
            "and R2_SECRET_ACCESS_KEY"
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
        # R2 non ha regioni: "auto" è il valore richiesto per la firma
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            # checksum solo quando l'operazione li richiede, come consigliato da Cloudflare: i
            # checksum predefiniti dei boto3 recenti non sono supportati da R2 su tutte le API
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _bucket() -> str:
    if not settings.r2_bucket:
        raise StorageError("R2 is not configured: set R2_BUCKET")
    return settings.r2_bucket


def _prefix(post_id: int) -> str:
    return f"posts/{post_id}/"


def slide_key(post_id: int, position: int) -> str:
    """Chiave della slide in posizione `position` (da 0), es. posts/123/slide-1.jpg."""
    return f"{_prefix(post_id)}slide-{position + 1}.jpg"


def upload_slide(post_id: int, position: int, path: Path) -> str:
    """Carica su R2 la slide del post e ne restituisce la chiave."""
    key = slide_key(post_id, position)
    try:
        _client().upload_file(str(path), _bucket(), key, ExtraArgs={"ContentType": _CONTENT_TYPE})
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Upload of {path.name} to R2 failed: {e}") from e
    return key


def delete_old_slides(post_id: int, current: list[str]) -> None:
    """Elimina dal bucket le slide del post che non sono tra le chiavi correnti.

    Un rendering precedente può aver avuto più slide: le sue chiavi in eccesso vanno rimosse.
    """
    keep = set(current)
    try:
        client = _client()
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
        raise StorageError(f"Cleanup of old slides on R2 failed: {e}") from e


def presigned_url(key: str) -> str:
    """URL pre-firmato per scaricare l'oggetto, valido settings.r2_presigned_url_expires secondi."""
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": key},
            ExpiresIn=settings.r2_presigned_url_expires,
        )
    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Signing the URL of {key} failed: {e}") from e

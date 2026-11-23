import httpx2

from autopost_server.config import settings

_API_URL = "https://api.notion.com/v1/pages"
_NOTION_VERSION = "2025-09-03"
_TIMEOUT = httpx2.Timeout(10.0)

class NotionError(Exception):
    """Exception raised for the integration"""

def is_configured() -> bool:
    return settings.notion_api_key and settings.notion_source_id

def create_page(*, data_source_id: str, properies: dict) -> str:

    if not is_configured():
        raise NotionError("Notion is not configured (NOTION_API_KEY, NOTION_BETA_DATA_SOURCE_ID)")

    headers = {
        "Authorization": f"Bearer {settings.notion_api_key.get_secret_value()}",
        "Notion-Version": _NOTION_VERSION,
    }

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "icon": {"type": "emoji", "emoji": "📩"},
        "properties": properies,
    }

    try:
        response = httpx2.post(
            _API_URL,
            headers=headers,
            json=payload,
            timeout=_TIMEOUT
        )
    except httpx2.HTTPError as e:
        raise NotionError(f"Notion request failed: {e}") from e
    if response.status_code >= 400:
        raise NotionError(f"Notion error {response.status_code}: {response.text}")
    return response.json()["id"]
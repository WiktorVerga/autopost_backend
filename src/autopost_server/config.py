from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    token_encryption_key: SecretStr

    # --- Google OAuth ---
    google_client_id: str
    google_client_secret: SecretStr
    # se vuoto viene calcolato dalla richiesta (es. http://localhost:8000/auth/google/callback)
    google_redirect_uri: str | None = None

    # --- Instagram API con login di Instagram, per collegare gli account professionali ---
    # opzionali: senza, il server parte ma il collegamento Instagram risponde 503
    # ID e chiave segreta dell'app *Instagram* (non quelli dell'app Meta)
    instagram_app_id: str | None = None
    instagram_app_secret: SecretStr | None = None
    # se vuoto viene calcolato dalla richiesta (es. http://localhost:8000/instagram-accounts/oauth/callback)
    instagram_redirect_uri: str | None = None
    instagram_graph_api_version: str = "v24.0"
    instagram_scopes: str = "instagram_business_basic,instagram_business_content_publish"

    # --- Sessione e JWT ---
    # firma il cookie di sessione usato solo durante il giro OAuth (state, nonce)
    session_secret_key: SecretStr
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # cookie HttpOnly con il JWT, impostato dal callback del login Google
    auth_cookie_name: str = "access_token"
    # True in produzione (HTTPS); su http://localhost il browser scarterebbe il cookie
    auth_cookie_secure: bool = False

    # dopo il login reindirizza qui (il token è nel cookie); è anche l'unica origine
    # abilitata da CORS. Se vuoto il callback restituisce il token come JSON
    frontend_url: str | None = None

    @property
    def frontend_origin(self) -> str | None:
        """Schema, host e porta di frontend_url (es. http://localhost:3000), senza percorso."""
        if not self.frontend_url:
            return None
        url = urlsplit(self.frontend_url)
        return f"{url.scheme}://{url.netloc}"


settings = Settings()

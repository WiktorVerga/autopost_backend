from pathlib import Path
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

    # --- Claude API, per generare i contenuti dei post ---
    # opzionale: senza, il server parte ma la generazione dei post fallisce
    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-opus-5-5"
    # profondità di ragionamento: low | medium | high | xhigh | max
    claude_effort: str = "medium"
    # cartella dei file generati per ogni post (carousel.json, immagini delle slide)
    media_dir: Path = Path("media")

    # --- Rendering e hosting delle slide ---
    # URL pubblico del server (es. https://autopost.example.com): le slide sono servite su
    # {public_base_url}/media/... e Instagram le scarica da lì. Se vuoto le slide non hanno
    # public_url e il post non è pubblicabile (il modo preview funziona comunque)
    public_base_url: str | None = None
    # browser usato per il rendering se né il Chromium di Playwright né Chrome/Edge di sistema
    # sono disponibili
    chrome_path: str | None = None

    # --- Cloudflare R2, per ospitare le slide ---
    # opzionale: se configurato le slide vengono caricate nel bucket e public_url punta a
    # r2_public_url (dominio r2.dev o personalizzato), altrimenti si usa public_base_url
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_public_url: str | None = None

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
    def r2_enabled(self) -> bool:
        return all(
            (
                self.r2_account_id,
                self.r2_access_key_id,
                self.r2_secret_access_key,
                self.r2_bucket,
                self.r2_public_url,
            )
        )

    @property
    def frontend_origin(self) -> str | None:
        """Schema, host e porta di frontend_url (es. http://localhost:3000), senza percorso."""
        if not self.frontend_url:
            return None
        url = urlsplit(self.frontend_url)
        return f"{url.scheme}://{url.netloc}"


settings = Settings()

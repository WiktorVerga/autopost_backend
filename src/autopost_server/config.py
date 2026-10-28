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

    # --- Rendering delle slide ---
    # browser usato per il rendering se né il Chromium di Playwright né Chrome/Edge di sistema
    # sono disponibili
    chrome_path: str | None = None

    # --- Amazon S3, per archiviare le slide ---
    # le slide renderizzate vengono caricate nel bucket (privato) e nel DB resta solo la chiave;
    # alla pubblicazione Instagram le scarica da un URL pre-firmato. Senza bucket il rendering
    # fallisce
    s3_bucket: str | None = None
    s3_region: str = "eu-central-1"
    # validità degli URL pre-firmati: Instagram scarica le immagini mentre si crea il container
    s3_presigned_url_expires: int = 3600
    # opzionali: se vuote boto3 usa la propria catena di credenziali (~/.aws, ruolo IAM...)
    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None

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

    @property
    def frontend_domain(self) -> str | None:
        """Restituisce il sottodominio del frontend"""
        if not self.frontend_url:
            return None

        domain = urlsplit(self.frontend_url)
        return f"{domain.netloc}"

settings = Settings()

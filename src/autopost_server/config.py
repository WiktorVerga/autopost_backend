from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": variabili non più usate (es. le vecchie S3_* e AWS_*) rimaste in un .env non
    # bloccano l'avvio del server
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    token_encryption_key: SecretStr

    # espone /docs, /redoc e /openapi.json; spento di default così in produzione non sono
    # raggiungibili, va acceso solo nel .env di sviluppo
    enable_docs: bool = False

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

    # --- Cloudflare R2, per archiviare le slide ---
    # le slide renderizzate vengono caricate nel bucket (privato) e nel DB resta solo la chiave;
    # frontend e Instagram le scaricano da URL pre-firmati. Senza configurazione R2 il server
    # parte, ma il rendering dei post fallisce
    r2_account_id: str | None = None
    # token API R2 (dashboard Cloudflare > R2 > Gestisci token API) con permesso
    # "Object Read & Write" sul bucket
    r2_access_key_id: str | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    # opzionale: endpoint S3 del bucket, se vuoto https://<r2_account_id>.r2.cloudflarestorage.com.
    # Per un bucket con giurisdizione UE va impostato a https://<r2_account_id>.eu.r2.cloudflarestorage.com
    r2_endpoint_url: str | None = None
    # validità degli URL pre-firmati (massimo 7 giorni): Instagram scarica le immagini mentre si
    # crea il container, il frontend ne riceve di nuovi a ogni lettura del post
    r2_presigned_url_expires: int = 3600

    @property
    def r2_endpoint(self) -> str | None:
        if self.r2_endpoint_url:
            return self.r2_endpoint_url.rstrip("/")
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return None

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

    # --- Claude API, Workload Identity Federation con issuer Azure Entra ID ---
    # sostituisce l'API key (che scade): se rule, organization e audience sono impostati ha la
    # precedenza su anthropic_api_key, che resta come fallback (es. sviluppo locale senza IMDS)
    # audience del JWT richiesto a Entra ID, nella forma api://<APP_ID>
    azure_claude_audience: str | None = None
    # client ID della managed identity: serve solo se la VM ne ha più di una user-assigned
    azure_client_id: str | None = None
    anthropic_federation_rule_id: str | None = None
    anthropic_organization_id: str | None = None
    anthropic_service_account_id: str | None = None
    # obbligatorio solo se la regola di federazione copre più workspace
    anthropic_workspace_id: str | None = None

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

        # solo l'host: un Domain con la porta viene scartato, e su localhost i cookie restano
        # legati all'host senza bisogno di Domain
        host = urlsplit(self.frontend_url).hostname
        if not host or host == "localhost":
            return None
        return host

settings = Settings()

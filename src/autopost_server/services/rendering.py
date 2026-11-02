"""Rendering delle slide di un post: dal contenuto (carousel.json) alle immagini JPEG.

Il template public/template/carousel.html disegna le slide con il proprio JavaScript a partire
dal blocco <script id="data">: qui lo si riempie con il contenuto del post, lo si apre in
Chromium (Playwright) e si cattura ogni elemento .slide come immagine 1080 × 1350.

Le immagini vengono scritte in una cartella temporanea e caricate su S3 (services/storage.py):
sul server non resta nulla, del rendering si conservano solo le chiavi S3 delle slide.
"""

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from autopost_server.config import settings
from autopost_server.services.storage import delete_old_slides, upload_slide

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = PROJECT_ROOT / "public" / "template" / "carousel.html"

SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350
# Instagram pubblica solo immagini JPEG
_JPEG_QUALITY = 92
_READY_TIMEOUT_MS = 30_000


class RenderError(Exception):
    pass


@dataclass
class RenderedSlide:
    position: int
    storage_key: str


@dataclass
class RenderResult:
    slides: list[RenderedSlide]
    # avvisi del template (testo che non entra nella slide anche dopo il ridimensionamento)
    problems: list[str]


def _launch_browser(p: Playwright, args: list[str] | None = None):
    """Prova il Chromium di Playwright, poi Chrome di sistema, poi settings.chrome_path."""
    attempts = [
        lambda: p.chromium.launch(args=args),
        lambda: p.chromium.launch(channel="chrome", args=args),
        lambda: p.chromium.launch(channel="msedge", args=args),
    ]
    for name in (settings.chrome_path, "google-chrome", "chromium", "chromium-browser"):
        if name:
            path = shutil.which(name) or (name if Path(name).exists() else None)
            if path:
                attempts.append(
                    lambda path=path: p.chromium.launch(executable_path=path, args=args)
                )
    last = None
    for attempt in attempts:
        try:
            return attempt()
        except Exception as e:  # noqa: BLE001
            last = e
    raise RenderError(f"Could not start a browser: {last}")


def _fill_template(content: dict) -> str:
    """Il template con i dati del post al posto di quelli d'esempio, in modalità render."""
    html = TEMPLATE.read_text(encoding="utf-8")
    start = html.index('<script id="data" type="application/json">')
    start = html.index(">", start) + 1
    end = html.index("</script>", start)
    # "</" chiuderebbe il tag <script> se comparisse in un testo
    safe_json = json.dumps(content, ensure_ascii=False).replace("</", "<\\/")
    html = html[:start] + "\n" + safe_json + "\n" + html[end:]
    return html.replace('data-mode="preview"', 'data-mode="render"', 1)


def render_slides(post_id: int, content: dict) -> RenderResult:
    """Crea un JPEG per slide e lo carica su S3 (posts/<post_id>/slide-1.jpg, slide-2.jpg, ...).

    Sincrona e lenta (avvia un browser e carica le immagini): dal codice asincrono va chiamata
    con asyncio.to_thread.
    """
    expected = len(content.get("slides") or [])
    if expected == 0:
        raise RenderError("The post content has no slides")

    with tempfile.TemporaryDirectory(prefix="autopost-render-") as tmp:
        return _render_and_upload(post_id, content, expected, Path(tmp))


def _render_and_upload(post_id: int, content: dict, expected: int, out_dir: Path) -> RenderResult:
    # il file sta accanto al template perché i percorsi relativi (font) si risolvano uguali
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".html", prefix=".render-", dir=TEMPLATE.parent, delete=False
    ) as f:
        f.write(_fill_template(content))
        page_path = Path(f.name)

    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            try:
                page = browser.new_page(viewport={"width": SLIDE_WIDTH, "height": SLIDE_HEIGHT})
                page.goto(page_path.as_uri())
                # il template imposta data-ready dopo il caricamento dei font e l'auto-fit
                page.wait_for_selector(
                    "html[data-ready='1']", state="attached", timeout=_READY_TIMEOUT_MS
                )
                report = page.evaluate("window.__REPORT") or {}
                slides = page.locator(".slide")
                count = slides.count()
                if count != expected:
                    problems = "; ".join(report.get("problems") or [])
                    raise RenderError(f"Rendered {count} of {expected} slides. {problems}".strip())

                paths = []
                for i in range(count):
                    path = out_dir / f"slide-{i:02d}.jpg"
                    slides.nth(i).screenshot(path=path, type="jpeg", quality=_JPEG_QUALITY)
                    paths.append(path)
            finally:
                browser.close()
    finally:
        page_path.unlink(missing_ok=True)

    # a browser chiuso; le slide vecchie si eliminano solo dopo aver caricato le nuove
    slides = [RenderedSlide(i, upload_slide(post_id, i, path)) for i, path in enumerate(paths)]
    delete_old_slides(post_id, [s.storage_key for s in slides])

    return RenderResult(slides=slides, problems=list(report.get("problems") or []))


# ── Anteprima di un template caricato da un utente ─────────────────────────────────────────

# origine fittizia: ogni richiesta della pagina passa da _sandbox_route, nessuna va in rete
_SANDBOX_ORIGIN = "http://template.invalid"
_SANDBOX_PAGE = f"{_SANDBOX_ORIGIN}/index.html"
# file serviti alla pagina (i font condivisi), come i percorsi relativi di carousel.html
_ASSETS_DIR = TEMPLATE.parent.resolve()
# ciò che sfugge al routing (WebSocket, richieste del browser) finisce su un proxy inesistente
_SANDBOX_ARGS = ["--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>"]
_MAX_PREVIEW_SLIDES = 20


class PreviewError(RenderError):
    """Il rendering è fallito per colpa del template (non del server)."""


@dataclass
class RenderedPreview:
    images: list[bytes]  # JPEG, una per slide (o una sola della pagina se non ci sono .slide)
    problems: list[str]


def _sandbox_route(html: str):
    def handle(route):
        url = route.request.url
        if url == _SANDBOX_PAGE:
            route.fulfill(body=html, content_type="text/html; charset=utf-8")
            return
        if url.startswith(_SANDBOX_ORIGIN + "/"):
            relative = unquote(urlsplit(url).path).lstrip("/")
            path = (_ASSETS_DIR / relative).resolve()
            if path.is_relative_to(_ASSETS_DIR) and path.is_file() and path.suffix != ".html":
                route.fulfill(path=path)
                return
        route.abort()

    return handle


def render_preview(html: str, width: int, height: int) -> RenderedPreview:
    """Disegna un HTML non fidato e ne cattura le slide (o la pagina) come JPEG, in memoria.

    La pagina non può raggiungere la rete né il filesystem: le sole risorse servite sono i
    file di public/template (i font). Sincrona e lenta: dal codice asincrono va chiamata con
    asyncio.to_thread.
    """
    page_errors: list[str] = []
    with sync_playwright() as p:
        browser = _launch_browser(p, args=_SANDBOX_ARGS)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block",
                accept_downloads=False,
            )
            context.route("**/*", _sandbox_route(html))
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.on("pageerror", lambda e: page_errors.append(f"JavaScript error: {e}"))
            page.set_default_timeout(_READY_TIMEOUT_MS)

            try:
                page.goto(_SANDBOX_PAGE, wait_until="load")
                if "ready" in html:
                    # i template come carousel.html segnalano la fine del disegno con data-ready
                    page.wait_for_selector("html[data-ready='1']", state="attached")
                else:
                    page.evaluate("document.fonts.ready.then(() => true)")
            except PlaywrightTimeoutError as e:
                reasons = ["The template did not finish rendering in time", *page_errors]
                raise PreviewError("; ".join(reasons)) from e

            report = page.evaluate("window.__REPORT || {}") or {}
            problems = [str(x) for x in (report.get("problems") or [])] + page_errors

            slides = page.locator(".slide")
            count = slides.count()
            if count > _MAX_PREVIEW_SLIDES:
                raise PreviewError(f"The template renders {count} slides, max {_MAX_PREVIEW_SLIDES}")
            if count:
                images = [
                    slides.nth(i).screenshot(type="jpeg", quality=_JPEG_QUALITY)
                    for i in range(count)
                ]
            else:
                images = [page.screenshot(type="jpeg", quality=_JPEG_QUALITY)]
        finally:
            browser.close()

    return RenderedPreview(images=images, problems=problems)

"""Rendering delle slide di un post: dal contenuto (carousel.json) alle immagini JPEG.

Le slide si disegnano con il template Jinja collegato al programma del post
(Template.jinja_content, generato da services/templates.compile_definition): riempito con il
contenuto del post diventa l'HTML della pagina, che si apre in Chromium (Playwright) nella stessa
sandbox delle anteprime dei template; ogni slide si cattura come immagine 1080 × 1350.

Le immagini vengono scritte in una cartella temporanea e caricate su R2 (services/storage.py):
sul server non resta nulla, del rendering si conservano solo le chiavi R2 delle slide.
"""

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from autopost_server.config import settings
from autopost_server.services.storage import delete_old_slides, upload_slide

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350
# Instagram pubblica solo immagini JPEG
_JPEG_QUALITY = 92
_READY_TIMEOUT_MS = 30_000


class RenderError(Exception):
    pass


class PreviewError(RenderError):
    """Il rendering è fallito per colpa del template (non del server)."""


@dataclass
class RenderedSlide:
    position: int
    storage_key: str


@dataclass
class RenderResult:
    slides: list[RenderedSlide]
    # avvisi del template (testo che non entra nella slide, errori JavaScript della pagina)
    problems: list[str]


@dataclass
class RenderedPreview:
    images: list[bytes]  # JPEG, una per slide (o una sola della pagina se non ci sono .slide)
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


# ── Sandbox del browser (slide dei post e anteprime dei template) ─────────────────────────

# origine fittizia: ogni richiesta della pagina passa da _sandbox_route, nessuna va in rete
_SANDBOX_ORIGIN = "http://template.invalid"
_SANDBOX_PAGE = f"{_SANDBOX_ORIGIN}/index.html"
# file serviti alla pagina (i font condivisi), con percorsi relativi a public/template
_ASSETS_DIR = (PROJECT_ROOT / "public" / "template").resolve()
# ciò che sfugge al routing (WebSocket, richieste del browser) finisce su un proxy inesistente
_SANDBOX_ARGS = ["--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>"]
_MAX_PREVIEW_SLIDES = 20
# le slide dei template: .slide (carousel.html) e .t-slide (basi in public/template/default templates)
_SLIDE_SELECTOR = ".slide, .t-slide"
# unica rete concessa: i Google Fonts delle basi, scaricati da Playwright (non dal browser, che
# ha il proxy inesistente) e serviti alla pagina
_ALLOWED_FONT_HOSTS = frozenset({"fonts.googleapis.com", "fonts.gstatic.com"})
_FONT_FETCH_TIMEOUT_MS = 10_000


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
        parts = urlsplit(url)
        if (
            parts.scheme == "https"
            and parts.hostname in _ALLOWED_FONT_HOSTS
            and route.request.method == "GET"
        ):
            try:
                route.fulfill(response=route.fetch(timeout=_FONT_FETCH_TIMEOUT_MS))
            except Exception:  # noqa: BLE001 - senza il font la pagina usa quello di riserva
                route.abort()
            return
        route.abort()

    return handle


@contextmanager
def _sandbox_page(html: str, width: int, height: int) -> Iterator[tuple[Page, list[str]]]:
    """Apre l'HTML nella sandbox e attende la fine del disegno; restituisce la pagina e gli
    avvisi raccolti (problemi segnalati dal template in window.__REPORT ed errori JavaScript).

    La pagina non può raggiungere la rete né il filesystem: le sole risorse servite sono i
    file di public/template e i Google Fonts. PreviewError se il disegno non finisce in tempo.
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
                # non basta cercare "ready": la parola può comparire nel testo delle slide
                if "dataset.ready" in html or "data-ready" in html:
                    # i template come carousel.html segnalano la fine del disegno con data-ready
                    page.wait_for_selector("html[data-ready='1']", state="attached")
                else:
                    page.evaluate("document.fonts.ready.then(() => true)")
            except PlaywrightTimeoutError as e:
                reasons = ["The template did not finish rendering in time", *page_errors]
                raise PreviewError("; ".join(reasons)) from e

            report = page.evaluate("window.__REPORT || {}") or {}
            problems = [str(x) for x in (report.get("problems") or [])] + page_errors
            yield page, problems
        finally:
            browser.close()


# ── Slide dei post ────────────────────────────────────────────────────────────────────────


def _fill_template(jinja_content: str, content: dict) -> str:
    """Il template Jinja del programma riempito con il contenuto del post: l'HTML da disegnare.

    Il template riceve il contenuto come unica variabile `data` ({"handle": ..., "slides": [...]}).
    """
    # import locale: services.templates importa questo modulo
    from autopost_server.services.templates import TemplateValidationError, render_jinja

    try:
        return render_jinja(jinja_content, content)
    except TemplateValidationError as e:
        raise PreviewError(str(e)) from e


def render_slides(post_id: int, content: dict, jinja_content: str) -> RenderResult:
    """Disegna il contenuto del post con il template Jinja `jinja_content` (quello del
    programma), crea un JPEG per slide e lo carica su R2 (posts/<post_id>/slide-1.jpg, ...).

    Sincrona e lenta (avvia un browser e carica le immagini): dal codice asincrono va chiamata
    con asyncio.to_thread.
    """
    expected = len(content.get("slides") or [])
    if expected == 0:
        raise RenderError("The post content has no slides")

    html = _fill_template(jinja_content, content)
    with tempfile.TemporaryDirectory(prefix="autopost-render-") as tmp:
        return _render_and_upload(post_id, html, expected, Path(tmp))


def _render_and_upload(post_id: int, html: str, expected: int, out_dir: Path) -> RenderResult:
    with _sandbox_page(html, SLIDE_WIDTH, SLIDE_HEIGHT) as (page, problems):
        slides = page.locator(_SLIDE_SELECTOR)
        count = slides.count()
        # una slide di un tipo che il template non conosce non viene disegnata
        if count != expected:
            details = "; ".join(problems)
            raise RenderError(f"Rendered {count} of {expected} slides. {details}".strip())

        paths = []
        for i in range(count):
            path = out_dir / f"slide-{i:02d}.jpg"
            slides.nth(i).screenshot(path=path, type="jpeg", quality=_JPEG_QUALITY)
            paths.append(path)

    # a browser chiuso; le slide vecchie si eliminano solo dopo aver caricato le nuove
    rendered = [RenderedSlide(i, upload_slide(post_id, i, path)) for i, path in enumerate(paths)]
    delete_old_slides(post_id, [s.storage_key for s in rendered])

    return RenderResult(slides=rendered, problems=problems)


# ── Anteprima di un template caricato da un utente ─────────────────────────────────────────


def render_preview(
    html: str, width: int, height: int, max_images: int | None = None
) -> RenderedPreview:
    """Disegna un HTML non fidato e ne cattura le slide (o la pagina) come JPEG, in memoria.

    Con max_images si catturano solo le prime max_images slide. Sincrona e lenta: dal codice
    asincrono va chiamata con asyncio.to_thread.
    """
    with _sandbox_page(html, width, height) as (page, problems):
        slides = page.locator(_SLIDE_SELECTOR)
        count = slides.count()
        if count > _MAX_PREVIEW_SLIDES:
            raise PreviewError(f"The template renders {count} slides, max {_MAX_PREVIEW_SLIDES}")
        if max_images is not None:
            count = min(count, max_images)
        if count:
            images = [
                slides.nth(i).screenshot(type="jpeg", quality=_JPEG_QUALITY)
                for i in range(count)
            ]
        else:
            images = [page.screenshot(type="jpeg", quality=_JPEG_QUALITY)]

    return RenderedPreview(images=images, problems=problems)

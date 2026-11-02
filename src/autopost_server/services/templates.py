"""Template HTML caricati dagli utenti: controllo, trasformazione in template Jinja2, verifica.

Un template segue lo stesso contratto di public/template/carousel.html:
- un documento HTML completo (<!doctype html>, <html>, <head>, <body>) ben formato;
- un unico blocco <script id="data" type="application/json"> con dei dati d'esempio (un
  oggetto JSON): è il punto in cui, al rendering, vengono iniettati i contenuti del post;
- il proprio JavaScript legge quel blocco e disegna gli elementi .slide; facoltativamente
  imposta <html data-ready="1"> quando ha finito e window.__REPORT.problems con gli avvisi.

La trasformazione sostituisce i dati d'esempio con {{ data | tojson }} e l'eventuale
data-mode dell'<html> con {{ mode }}. Nel resto del file si possono usare espressioni Jinja,
ma le sole variabili disponibili sono `data` e `mode`.

I template sono scritti dagli utenti: vengono compilati in un ambiente Jinja sandboxed (niente
accesso agli attributi interni di Python) e disegnati in un browser isolato dalla rete
(services/rendering.render_preview).
"""

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from jinja2 import StrictUndefined, TemplateError, TemplateSyntaxError, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment

from autopost_server.services.rendering import RenderedPreview, render_preview

MAX_TEMPLATE_BYTES = 2 * 1024 * 1024

# le sole variabili che il rendering passa al template
CONTEXT_VARIABLES = frozenset({"data", "mode"})

_env = ImmutableSandboxedEnvironment(autoescape=True, undefined=StrictUndefined)

_HTML_MODE = re.compile(r"""(<html\b[^>]*?\bdata-mode\s*=\s*)(["'])[^"']*\2""", re.IGNORECASE)

# elementi senza tag di chiusura
_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
})
# elementi il cui tag di chiusura è facoltativo in HTML5
_OPTIONAL_END = frozenset({
    "p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "optgroup",
    "colgroup", "caption", "rb", "rt", "rtc", "rp",
})
_REQUIRED = ("html", "head", "body")


class TemplateValidationError(Exception):
    """Il file caricato non è un template valido; `errors` elenca i motivi."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class CompiledTemplate:
    source: str  # il template Jinja2 da salvare
    sample_data: dict  # i dati d'esempio estratti dal file
    variables: list[dict]  # descrizione dei campi di primo livello dei dati


@dataclass
class VerifiedTemplate(CompiledTemplate):
    preview: RenderedPreview


class _WellFormedChecker(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        # offset del primo carattere di ogni riga, per passare da getpos() all'indice nel testo
        self._line_starts = [0]
        for line in html.split("\n")[:-1]:
            self._line_starts.append(self._line_starts[-1] + len(line) + 1)
        # (inizio, fine) del contenuto di ogni <script id="data">; quelli nei commenti non contano
        self.data_blocks: list[tuple[int, int]] = []
        self._data_start: int | None = None
        self.stack: list[tuple[str, int]] = []
        self.seen: set[str] = set()
        self.doctype = False
        self.errors: list[str] = []

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.doctype = True

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        self.seen.add(tag)
        if tag == "script" and ("id", "data") in attrs:
            self._data_start = self._offset() + len(self.get_starttag_text())
        if tag not in _VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        # <path/> e simili (SVG): elemento già chiuso
        self.seen.add(tag)

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        if tag == "script" and self._data_start is not None:
            self.data_blocks.append((self._data_start, self._offset()))
            self._data_start = None
        if tag in _VOID:
            self.errors.append(f"line {line}: </{tag}> is not allowed, <{tag}> has no closing tag")
            return
        if not any(open_tag == tag for open_tag, _ in self.stack):
            self.errors.append(f"line {line}: </{tag}> closes an element that is not open")
            return
        while True:
            open_tag, open_line = self.stack.pop()
            if open_tag == tag:
                break
            if open_tag not in _OPTIONAL_END:
                self.errors.append(
                    f"line {open_line}: <{open_tag}> is not closed before </{tag}> at line {line}"
                )

    def finish(self) -> list[str]:
        self.close()
        for tag, line in self.stack:
            if tag not in _OPTIONAL_END:
                self.errors.append(f"line {line}: <{tag}> is never closed")
        if not self.doctype:
            self.errors.append("missing <!doctype html>: the page would render in quirks mode")
        for tag in _REQUIRED:
            if tag not in self.seen:
                self.errors.append(f"missing <{tag}> element")
        return self.errors


def decode(raw: bytes) -> str:
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise TemplateValidationError([f"the file exceeds {MAX_TEMPLATE_BYTES // 1024} KB"])
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise TemplateValidationError([f"the file is not valid UTF-8 (byte {e.start})"]) from e


def check_well_formed(html: str) -> tuple[int, int]:
    """Primo controllo: struttura HTML bilanciata e blocco dati presente e valido.

    Restituisce la posizione (inizio, fine) del contenuto del blocco dati.
    """
    checker = _WellFormedChecker(html)
    checker.feed(html)
    errors = checker.finish()

    blocks = [html[start:end] for start, end in checker.data_blocks]
    if len(blocks) != 1:
        errors.append(
            f'expected exactly one <script id="data" type="application/json"> block, found {len(blocks)}'
        )
    else:
        try:
            sample = json.loads(blocks[0])
        except json.JSONDecodeError as e:
            errors.append(f'the <script id="data"> block is not valid JSON: {e}')
        else:
            if not isinstance(sample, dict):
                errors.append('the <script id="data"> block must contain a JSON object')

    if errors:
        raise TemplateValidationError(errors)
    return checker.data_blocks[0]


def _json_type(value) -> str:
    match value:
        case bool():
            return "boolean"
        case int() | float():
            return "number"
        case str():
            return "string"
        case list():
            return "array"
        case dict():
            return "object"
        case _:
            return "null"


def to_jinja(html: str, data_span: tuple[int, int]) -> CompiledTemplate:
    """Trasforma l'HTML (già controllato) in template Jinja2 e verifica che compili."""
    start, end = data_span
    sample = json.loads(html[start:end])
    before = _HTML_MODE.sub(r"\1\2{{ mode }}\2", html[:start], count=1)
    source = before + "\n{{ data | tojson }}\n" + html[end:]

    try:
        ast = _env.parse(source)
    except TemplateSyntaxError as e:
        raise TemplateValidationError([f"line {e.lineno}: Jinja syntax error: {e.message}"]) from e
    unknown = meta.find_undeclared_variables(ast) - CONTEXT_VARIABLES
    if unknown:
        names = ", ".join(sorted(unknown))
        raise TemplateValidationError(
            [f"unknown template variables: {names} (only 'data' and 'mode' are available)"]
        )

    variables = [{"name": k, "type": _json_type(v), "example": v} for k, v in sample.items()]
    return CompiledTemplate(source=source, sample_data=sample, variables=variables)


def render_source(source: str, data: dict, mode: str = "render") -> str:
    """Il template Jinja con i dati di un post: l'HTML pronto per il browser."""
    try:
        return _env.from_string(source).render(data=data, mode=mode)
    except TemplateError as e:
        raise TemplateValidationError([f"Jinja rendering failed: {e}"]) from e


def verify(raw: bytes, width: int, height: int) -> VerifiedTemplate:
    """Controllo, trasformazione e rendering di prova con i dati d'esempio del file.

    Sincrona e lenta (avvia un browser): dal codice asincrono va chiamata con asyncio.to_thread.
    """
    html = decode(raw)
    data_span = check_well_formed(html)
    compiled = to_jinja(html, data_span)
    rendered_html = render_source(compiled.source, compiled.sample_data)
    preview = render_preview(rendered_html, width, height)
    return VerifiedTemplate(**vars(compiled), preview=preview)

"""Template degli utenti: dalla definizione JSON inviata dal client al template Jinja2.

Ogni template di base (models.enums.BaseTemplate) è una coppia di file in public/:
- <nome>.template.html: l'HTML di base, con i segnaposto del contratto descritto nel file;
- <nome>.schema.json: il JSON Schema della definizione. È l'unica fonte dei valori di default
  e, con la costante di "schema_version", della versione della base (salvata in base_version);
- preview.jpeg: l'anteprima della base, restituita al client in base64.

La compilazione (compile_definition):
1. valida la definizione contro lo schema e la completa con i default;
2. sostituisce <link id="t-fonts"> con il link ai soli Google Fonts scelti e il contenuto di
   <style id="t-vars"> con le variabili CSS calcolate;
3. trasforma il <body>: le <section data-type="..."> d'esempio diventano i rami di
   {% for slide in data.slides %}{% if slide.type == "..." %}, e al loro interno
   - data-el="gruppo.chiave"  → {% if v.gruppo.chiave %} … {% endif %}
   - data-field="campo"       → il testo d'esempio diventa {{ slide.campo }}
   - data-repeat="lista"      → il primo elemento diventa il corpo di {% for … in slide.lista %},
                                gli altri con lo stesso data-repeat (esempi) vengono scartati.
   I campi "meta.counter" e "meta.handle" li calcola il template stesso (numero della slide
   e data.handle). I commenti HTML della base non finiscono nel template.

Il risultato si disegna con render_jinja(jinja_content, data), dove data è il contenuto del post
({"handle": ..., "slides": [{"type": ..., ...}]}). L'unica variabile di contesto è `data`.

L'anteprima di un template (render_template_preview, salvata in Template.preview_image) è la
sua prima slide disegnata con i dati d'esempio della base: i testi delle sezioni d'esempio,
letti dagli stessi attributi data-field / data-repeat che usa il compilatore.
"""

import base64
import json
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus

from jinja2 import ChainableUndefined, TemplateError, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jsonschema import Draft202012Validator

from autopost_server.models.enums import BaseTemplate
from autopost_server.services.rendering import (
    PROJECT_ROOT,
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    PreviewError,
    render_preview,
)

PUBLIC_DIR = PROJECT_ROOT / "public"

# le sole variabili che il rendering passa al template
CONTEXT_VARIABLES = frozenset({"data"})

# sandbox: i dati dei post non sono fidati. ChainableUndefined: un campo mancante nel contenuto
# del post produce un testo vuoto (e un ciclo su una lista mancante zero elementi), non un errore
_env = ImmutableSandboxedEnvironment(autoescape=True, undefined=ChainableUndefined)

# Google Fonts ammessi dallo schema: famiglia per l'API css2 (con assi e pesi) e font di riserva
_GOOGLE_FONTS = {
    "Inter": ("Inter:wght@400;500;600", "system-ui, sans-serif"),
    "Space Grotesk": ("Space Grotesk:wght@400;500;600", "system-ui, sans-serif"),
    "IBM Plex Mono": ("IBM Plex Mono:wght@400;500;600", "ui-monospace, monospace"),
    "Fraunces": ("Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600", "Georgia, serif"),
    "Playfair Display": ("Playfair Display:wght@400;500;600", "Georgia, serif"),
    "DM Serif Display": ("DM Serif Display", "Georgia, serif"),
}

# definizione → variabili CSS di <style id="t-vars">
_COLOR_VARS = {
    "background": "--color-bg",
    "text": "--color-text",
    "muted": "--color-muted",
    "accent": "--color-accent",
}
_FONT_VARS = {"heading": "--font-heading", "body": "--font-body"}
_SIZE_VARS = {
    "title": "--size-title",
    "subtitle": "--size-subtitle",
    "body": "--size-body",
    "kicker": "--size-kicker",
    "number": "--size-number",
    "meta": "--size-meta",
}

_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
})
# attributi del contratto: servono solo al compilatore, non finiscono nel template
_CONTRACT_ATTRS = frozenset({"data-el", "data-field", "data-repeat"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JINJA_OPENERS = ("{{", "{%", "{#")


class TemplateValidationError(Exception):
    """La definizione inviata non è valida; `errors` elenca i motivi."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class BaseTemplateError(Exception):
    """L'HTML o lo schema di una base non rispettano il contratto: errore del server."""


@dataclass(frozen=True)
class BaseFiles:
    base: BaseTemplate
    html: str
    schema: dict
    version: int
    defaults: dict
    # data URL di preview.jpeg: data:image/jpeg;base64,...
    preview_image: str
    # contenuto di un post con i testi d'esempio della base, per le anteprime dei template
    sample_data: dict


@dataclass
class CompiledTemplate:
    base_template: BaseTemplate
    base_version: int
    jinja_content: str


# ── file della base ───────────────────────────────────────────────────────────────────────


def _base_path(base: BaseTemplate) -> Path:
    public = PUBLIC_DIR.resolve()
    path = (public / base.value).resolve()
    if not path.is_relative_to(public) or not path.name.endswith(".template.html"):
        raise BaseTemplateError(f"Invalid path for base template {base.key}: {base.value}")
    return path


def _resolve(node: dict, root: dict) -> dict:
    """Il nodo con l'eventuale $ref locale ("#/$defs/...") risolto; le chiavi del nodo vincono."""
    ref = node.get("$ref")
    if not ref:
        return node
    if not ref.startswith("#/"):
        raise BaseTemplateError(f"Unsupported $ref in schema: {ref}")
    target = root
    for part in ref[2:].split("/"):
        target = target[part]
    return {**_resolve(target, root), **{k: v for k, v in node.items() if k != "$ref"}}


def _defaults(node: dict, root: dict):
    """I valori di default dichiarati nello schema, come oggetto completo."""
    node = _resolve(node, root)
    if "properties" in node:
        own = node.get("default") or {}
        return {k: own.get(k, _defaults(v, root)) for k, v in node["properties"].items()}
    return node.get("default")


@lru_cache
def load_base(base: BaseTemplate) -> BaseFiles:
    """HTML, schema, versione e default di una base (letti una volta per processo)."""
    html_path = _base_path(base)
    schema_name = html_path.name.removesuffix(".template.html") + ".schema.json"
    schema_path = html_path.with_name(schema_name)
    html = html_path.read_text(encoding="utf-8")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    props = schema.get("properties", {})
    version = props.get("schema_version", {}).get("const")
    if not isinstance(version, int):
        raise BaseTemplateError(f"{schema_name}: schema_version must be an integer const")
    if props.get("base_template", {}).get("const") != base.key:
        raise BaseTemplateError(f"{schema_name}: base_template const must be '{base.key}'")

    preview_path = html_path.with_name("preview.jpeg")
    if not preview_path.is_file():
        raise BaseTemplateError(f"Base template {base.key} has no preview.jpeg")
    preview_image = "data:image/jpeg;base64," + base64.b64encode(preview_path.read_bytes()).decode()

    return BaseFiles(
        base=base,
        html=html,
        schema=schema,
        version=version,
        defaults=_defaults(schema, schema),
        preview_image=preview_image,
        sample_data=_sample_data(_parse_html(html)),
    )


# ── validazione della definizione ─────────────────────────────────────────────────────────


def _base_of(definition: dict) -> BaseTemplate:
    key = definition.get("base_template")
    if not isinstance(key, str):
        raise TemplateValidationError(["definition_json.base_template: required string"])
    try:
        return BaseTemplate.from_key(key)
    except ValueError as e:
        raise TemplateValidationError([f"definition_json.base_template: {e}"]) from e


def validate_definition(definition: dict, expected: BaseTemplate) -> BaseFiles:
    """Controlla che la definizione sia per la base `expected` (quella scelta dal client) e la
    valida contro lo schema di quella base; restituisce i file della base."""
    declared = _base_of(definition)
    if declared is not expected:
        message = (
            f"definition_json.base_template: the definition is for '{declared.key}', "
            f"but base_template is '{expected.key}'"
        )
        raise TemplateValidationError([message])
    base = load_base(expected)
    validator = Draft202012Validator(base.schema)
    errors = [
        f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in sorted(validator.iter_errors(definition), key=lambda e: list(e.absolute_path))
    ]
    if errors:
        raise TemplateValidationError(errors)
    return base


def _merge(defaults, value):
    """La definizione completata con i default (oggetti uniti ricorsivamente)."""
    if isinstance(defaults, dict) and isinstance(value, dict):
        return {k: _merge(defaults.get(k), value.get(k)) for k in defaults.keys() | value.keys()}
    return defaults if value is None else value


# ── albero HTML minimo (html.parser) ──────────────────────────────────────────────────────


@dataclass
class _Element:
    tag: str
    attrs: list[tuple[str, str | None]]
    children: list[_Element | str]

    def get(self, name: str) -> str | None:
        return next((v for k, v in self.attrs if k == name), None)


class _TreeBuilder(HTMLParser):
    """Albero del documento; i testi restano come nel sorgente, i commenti vengono scartati."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = _Element("#document", [], [])
        self._stack = [self.root]

    def handle_decl(self, decl):
        self._stack[-1].children.append(f"<!{decl}>")

    def handle_starttag(self, tag, attrs):
        element = _Element(tag, attrs, [])
        self._stack[-1].children.append(element)
        if tag not in _VOID:
            self._stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(_Element(tag, attrs, []))

    def handle_endtag(self, tag):
        if any(e.tag == tag for e in self._stack[1:]):
            while self._stack.pop().tag != tag:
                pass

    def handle_data(self, data):
        self._stack[-1].children.append(data)

    def handle_entityref(self, name):
        self._stack[-1].children.append(f"&{name};")

    def handle_charref(self, name):
        self._stack[-1].children.append(f"&#{name};")


def _parse_html(html: str) -> _Element:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def _find(node: _Element, predicate) -> _Element | None:
    for child in node.children:
        if isinstance(child, _Element):
            if predicate(child):
                return child
            found = _find(child, predicate)
            if found:
                return found
    return None


def _text(node: _Element) -> str:
    """Il testo di un elemento come lo vede il lettore: entità risolte, spazi compattati."""
    raw = "".join(c if isinstance(c, str) else _text(c) for c in node.children)
    return " ".join(unescape(raw).split())


# ── dati d'esempio della base (per le anteprime) ──────────────────────────────────────────


def _set_path(target: dict, parts: list[str], value) -> None:
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _sample_children(node: _Element, slide: dict, loops: dict[str, dict]) -> None:
    for child in node.children:
        if not isinstance(child, _Element):
            continue
        source = child.get("data-repeat")
        if not source:
            _sample_element(child, slide, loops)
            continue
        # ogni elemento d'esempio con lo stesso data-repeat è un elemento della lista
        parts = source.split(".")
        owner, parts = (loops[parts[0]], parts[1:]) if parts[0] in loops else (slide, parts)
        for part in parts[:-1]:
            owner = owner.setdefault(part, {})
        items = owner.setdefault(parts[-1], [])
        var = _loop_var(source)
        if child.get("data-field") == var:
            items.append(_text(child))  # lista di testi: <li data-repeat="items" data-field="item">
        else:
            item: dict = {}
            _sample_children(child, slide, {**loops, var: item})
            items.append(item)


def _sample_element(node: _Element, slide: dict, loops: dict[str, dict]) -> None:
    field = node.get("data-field")
    if not field:
        _sample_children(node, slide, loops)
        return
    parts = field.split(".")
    if parts[0] == "meta":
        return  # counter e handle li calcola il template
    if parts[0] in loops:
        if len(parts) > 1:
            _set_path(loops[parts[0]], parts[1:], _text(node))
    else:
        _set_path(slide, parts, _text(node))


def _sample_data(root: _Element) -> dict:
    """Il contenuto di un post ricavato dalle <section data-type> d'esempio della base: una
    slide per sezione, con i testi d'esempio al posto dei campi data-field."""
    body = _find(root, lambda e: e.tag == "body")
    if body is None:
        raise BaseTemplateError("The base HTML has no <body>")
    slides = []
    for section in body.children:
        if isinstance(section, _Element) and section.get("data-type"):
            slide = {"type": section.get("data-type")}
            _sample_children(section, slide, {})
            slides.append(slide)
    handle = _find(body, lambda e: e.get("data-field") == "meta.handle")
    return {"handle": _text(handle) if handle else "@autopost", "slides": slides}


def _static(text: str) -> str:
    """Testo del sorgente HTML: se contiene delimitatori Jinja va protetto con {% raw %}."""
    if any(o in text for o in _JINJA_OPENERS):
        if "endraw" in text:
            raise BaseTemplateError("The base HTML contains 'endraw'")
        return "{% raw %}" + text + "{% endraw %}"
    return text


def _start_tag(element: _Element) -> str:
    parts = [element.tag]
    for name, value in element.attrs:
        if name in _CONTRACT_ATTRS:
            continue
        parts.append(name if value is None else f'{name}="{escape(value, quote=True)}"')
    return "<" + " ".join(parts) + ">"


# ── compilazione ──────────────────────────────────────────────────────────────────────────


def _path_expr(path: str, loop_vars: list[str]) -> str:
    """'left.items' → slide["left"]["items"]; 'step.title' (dentro un ciclo) → step["title"];
    'meta.counter' → meta["counter"]. Sempre con [], perché slide.items sarebbe dict.items."""
    parts = path.split(".")
    if not all(_IDENT.match(p) for p in parts):
        raise BaseTemplateError(f"Invalid path in base template: {path!r}")
    if parts[0] in loop_vars or parts[0] == "meta":
        expr, rest = parts[0], parts[1:]
    else:
        expr, rest = "slide", parts
    return expr + "".join(f"[{json.dumps(p)}]" for p in rest)


def _loop_var(path: str) -> str:
    """Nome della variabile del ciclo: 'steps' → step, 'left.items' → item."""
    last = path.split(".")[-1]
    return last[:-1] if last.endswith("s") and len(last) > 1 else f"{last}_item"


class _Compiler:
    def __init__(self, visibility: dict, fonts_link: str, css_vars: str):
        self.visibility = visibility
        self.fonts_link = fonts_link
        self.css_vars = css_vars

    @staticmethod
    def _element(node: _Element, inner: str) -> str:
        if node.tag in _VOID:
            return _start_tag(node)
        return _start_tag(node) + inner + f"</{node.tag}>"

    # ── parte statica del documento: <head> con le sostituzioni ──

    def document(self, root: _Element) -> str:
        if not _find(root, lambda e: e.tag == "link" and e.get("id") == "t-fonts"):
            raise BaseTemplateError('The base HTML has no <link id="t-fonts">')
        if not _find(root, lambda e: e.tag == "style" and e.get("id") == "t-vars"):
            raise BaseTemplateError('The base HTML has no <style id="t-vars">')
        if not _find(root, lambda e: e.tag == "body"):
            raise BaseTemplateError("The base HTML has no <body>")
        return "".join(self.static(c) for c in root.children)

    def static(self, node) -> str:
        if isinstance(node, str):
            return _static(node)
        if node.tag == "link" and node.get("id") == "t-fonts":
            return self.fonts_link
        if node.tag == "style" and node.get("id") == "t-vars":
            return _start_tag(node) + self.css_vars + "</style>"
        if node.tag == "body":
            return self.body(node)
        return self._element(node, "".join(self.static(c) for c in node.children))

    # ── <body>: le sezioni d'esempio diventano un ciclo sulle slide del post ──

    def body(self, body: _Element) -> str:
        sections = [c for c in body.children if isinstance(c, _Element) and c.get("data-type")]
        if not sections:
            raise BaseTemplateError('The base HTML has no <section data-type="..."> in <body>')
        out = [_start_tag(body), "\n{% set v = " + json.dumps(self.visibility) + " %}\n"]
        loop_emitted = False
        for child in body.children:
            if isinstance(child, str):
                if child.strip():
                    out.append(_static(child))
            elif child.get("data-type"):
                if not loop_emitted:
                    out.append(self.slides_loop(sections))
                    loop_emitted = True
            else:
                out.append(self.static(child))
        out.append("\n</body>")
        return "".join(out)

    def slides_loop(self, sections: list[_Element]) -> str:
        # meta: numero della slide e handle, calcolati qui e non chiesti a Claude
        loop_head = (
            "{% for slide in data['slides'] %}"
            "{% set meta = {'counter': '%02d / %02d' | format(loop.index, data['slides'] | length),"
            " 'handle': data['handle']} %}\n"
        )
        out = [loop_head]
        seen = set()
        for i, section in enumerate(sections):
            slide_type = section.get("data-type")
            if not _IDENT.match(slide_type) or slide_type in seen:
                raise BaseTemplateError(f"Invalid or duplicated data-type={slide_type!r}")
            seen.add(slide_type)
            keyword = "if" if i == 0 else "elif"
            out.append(f"{{% {keyword} slide['type'] == {json.dumps(slide_type)} %}}\n")
            out.append(self.slide_node(section, []))
            out.append("\n")
        out.append("{% endif %}\n{% endfor %}")
        return "".join(out)

    def slide_node(self, node, loop_vars: list[str]) -> str:
        if isinstance(node, str):
            return _static(node)
        field = node.get("data-field")
        if field:
            inner = "{{ " + _path_expr(field, loop_vars) + " }}"
        else:
            inner = self.slide_children(node, loop_vars)
        html = self._element(node, inner)

        el = node.get("data-el")
        if el:
            html = "{% if " + self.visibility_expr(el) + " %}" + html + "{% endif %}"
        return html

    def slide_children(self, node: _Element, loop_vars: list[str]) -> str:
        out = []
        repeated: set[str] = set()
        for child in node.children:
            source = child.get("data-repeat") if isinstance(child, _Element) else None
            if source:
                if source in repeated:
                    continue  # gli altri elementi d'esempio della stessa lista
                repeated.add(source)
                var = _loop_var(source)
                item = self.slide_node(child, [*loop_vars, var])
                expr = _path_expr(source, loop_vars)
                out.append(f"{{% for {var} in {expr} %}}{item}{{% endfor %}}")
            elif isinstance(child, str) and repeated and not child.strip():
                continue  # spazi fra gli esempi scartati
            else:
                out.append(self.slide_node(child, loop_vars))
        return "".join(out)

    def visibility_expr(self, path: str) -> str:
        """data-el="cover.subtitle" → v["cover"]["subtitle"], solo se la chiave è nello schema."""
        node = self.visibility
        for part in path.split("."):
            if not _IDENT.match(part) or not isinstance(node, dict) or part not in node:
                raise BaseTemplateError(f"data-el={path!r} has no matching key in the schema")
            node = node[part]
        if not isinstance(node, bool):
            raise BaseTemplateError(f"data-el={path!r} is not a boolean in the schema")
        return "v" + "".join(f"[{json.dumps(p)}]" for p in path.split("."))


def _fonts_link(fonts: dict) -> str:
    # un font scelto per titoli e testo si carica una volta sola
    names = dict.fromkeys(fonts[role] for role in _FONT_VARS)
    families = ["family=" + quote_plus(_GOOGLE_FONTS[n][0], safe=":,;@.") for n in names]
    href = "https://fonts.googleapis.com/css2?" + "&".join(families) + "&display=swap"
    return f'<link id="t-fonts" rel="stylesheet" href="{escape(href, quote=True)}">'


def _css_vars(config: dict) -> str:
    # valori già validati dallo schema: colori esadecimali, font da elenco chiuso, interi
    lines = [f"  {var}: {config['colors'][key]};" for key, var in _COLOR_VARS.items()]
    for key, var in _FONT_VARS.items():
        name = config["fonts"][key]
        lines.append(f"  {var}: '{name}', {_GOOGLE_FONTS[name][1]};")
    lines += [f"  {var}: {int(config['sizes'][key])}px;" for key, var in _SIZE_VARS.items()]
    return "\n:root {\n" + "\n".join(lines) + "\n}\n"


def compile_definition(definition: dict, base_template: BaseTemplate) -> CompiledTemplate:
    """Valida la definizione e genera il template Jinja2 dalla base `base_template`.

    TemplateValidationError se la definizione non è valida (errore del client),
    BaseTemplateError se la base non rispetta il contratto (errore del server).
    """
    base = validate_definition(definition, base_template)
    config = _merge(base.defaults, definition)
    unknown_fonts = {config["fonts"][r] for r in _FONT_VARS} - _GOOGLE_FONTS.keys()
    if unknown_fonts:
        raise BaseTemplateError(f"Fonts allowed by the schema but not configured: {unknown_fonts}")

    compiler = _Compiler(
        visibility=config["visibility"],
        fonts_link=_fonts_link(config["fonts"]),
        css_vars=_css_vars(config),
    )
    source = compiler.document(_parse_html(base.html))

    try:
        ast = _env.parse(source)
    except TemplateError as e:
        raise BaseTemplateError(f"Generated template does not compile: {e}") from e
    unknown = meta.find_undeclared_variables(ast) - CONTEXT_VARIABLES
    if unknown:
        raise BaseTemplateError(f"Generated template uses unknown variables: {sorted(unknown)}")

    return CompiledTemplate(
        base_template=base.base, base_version=base.version, jinja_content=source
    )


def render_jinja(jinja_content: str, data: dict) -> str:
    """Il template salvato con il contenuto di un post: l'HTML pronto per il browser."""
    try:
        return _env.from_string(jinja_content).render(data=data)
    except TemplateError as e:
        raise TemplateValidationError([f"Jinja rendering failed: {e}"]) from e


# ── anteprima ─────────────────────────────────────────────────────────────────────────────

# anteprime contemporanee al massimo: ognuna avvia un browser, le altre aspettano il turno
_PREVIEW_SLOTS = threading.BoundedSemaphore(2)


def render_template_preview(jinja_content: str, base_template: BaseTemplate) -> str:
    """La prima slide del template disegnata con i dati d'esempio della sua base, come data URL
    JPEG (data:image/jpeg;base64,...): il valore di Template.preview_image.

    Sincrona e lenta (avvia un browser): dal codice asincrono va chiamata con asyncio.to_thread.
    TemplateValidationError se il Jinja non si disegna, RenderError se il browser fallisce.
    """
    html = render_jinja(jinja_content, load_base(base_template).sample_data)
    with _PREVIEW_SLOTS:
        preview = render_preview(html, SLIDE_WIDTH, SLIDE_HEIGHT, max_images=1)
    if not preview.images:
        raise PreviewError("The template rendered no image")
    return "data:image/jpeg;base64," + base64.b64encode(preview.images[0]).decode("ascii")

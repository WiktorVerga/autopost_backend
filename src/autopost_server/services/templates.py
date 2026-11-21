"""Template degli utenti: dalla definizione JSON inviata dal client al template Jinja2, a partire
dalla base di un tipo di post (una riga di post_types, models.PostType).

Della base si usano:
- base_html: l'HTML d'esempio, con il contratto descritto sotto;
- editable_rules_schema: il JSON Schema della definizione. Nelle annotazioni x-ui di un campo,
  cssVar è la variabile CSS che il campo imposta e cssValue come se ne scrive il valore: un
  modello ("{value}px", "var(--color-{value})", "\"{family}\", {fallback}" per i font) o una
  mappa dal valore JSON (i booleani come "true"/"false") al valore CSS;
- default_css_vars: i valori di default della definizione (defaults.json);
- generation_schema (il generation.json del tipo): dal suo format si ricava lo schema del
  contenuto generato da Claude (PostType.output_schema), che dice quali campi sono liste e quali
  appartengono alla slide o al post; il suo sample_content è il contenuto delle anteprime.

La compilazione (compile_definition):
1. valida la definizione contro lo schema e la completa con i default;
2. sostituisce il blocco fra /* @vars:start */ e /* @vars:end */ con le variabili :root
   calcolate dalla definizione, e <link id="google-fonts"> con il link ai soli font scelti, con
   i pesi e gli stili usati dai ruoli tipografici (typography.*.font / weight / style);
3. trasforma il <body>: le <section data-type="..."> d'esempio diventano
   - se il contenuto ha "slides" (es. carousel): i rami di {% for slide in data.slides %}
     {% if slide.type == "..." %}, una sezione per ogni tipo di slide dello schema;
   - altrimenti (es. single post): l'unica sezione, disegnata una volta con il post intero.
   Nello style della sezione --slide-index e --slide-count prendono i valori della slide.
   Al loro interno data-field="percorso" sostituisce il contenuto dell'elemento con il valore:
   - "campo" o "gruppo.campo": un campo della slide (proprietà del suo tipo nello schema) o,
     se la slide non ce l'ha, del post (es. category; handle lo aggiunge il rendering);
   - una lista nello schema: il primo elemento figlio è il modello di ogni voce, gli altri sono
     esempi e vengono scartati. Dentro il modello "lista[].campo" è un campo della voce; se il
     modello non ne ha, la voce è un testo e diventa il contenuto del modello;
   - un testo il cui esempio nell'HTML contiene elementi (es. un <svg>) è markup: viene inserito
     come tale, ripulito da services/svg.sanitize_svg;
   - meta.index e meta.count: numero della slide e numero di slide ("01", "08");
     meta.item: numero della voce nella lista in cui si trova ("01", "02", ...).
   I commenti HTML della base non finiscono nel template.

Il risultato si disegna con render_jinja(jinja_content, data), dove data è il contenuto del post
con "handle". L'unica variabile di contesto è `data`.
"""

import base64
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus

from jinja2 import ChainableUndefined, TemplateError, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from autopost_server.models import PostType
from autopost_server.services.rendering import (
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    PreviewError,
    render_preview,
)
from autopost_server.services.svg import sanitize_svg

# le sole variabili che il rendering passa al template
CONTEXT_VARIABLES = frozenset({"data"})
# campi del post che non genera Claude ma aggiunge il rendering (pipeline.render_post)
RUNTIME_FIELDS = frozenset({"handle"})

# sandbox: i dati dei post non sono fidati. ChainableUndefined: un campo mancante nel contenuto
# del post produce un testo vuoto (e un ciclo su una lista mancante zero elementi), non un errore
_env = ImmutableSandboxedEnvironment(autoescape=True, undefined=ChainableUndefined)
_env.filters["svg"] = sanitize_svg

_VARS_START = "/* @vars:start */"
_VARS_END = "/* @vars:end */"
_FONTS_LINK_ID = "google-fonts"

_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
})
# attributi del contratto: servono solo al compilatore, non finiscono nel template
_CONTRACT_ATTRS = frozenset({"data-field"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JINJA_OPENERS = ("{{", "{%", "{#")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
# un valore CSS calcolato non può uscire dalla sua dichiarazione
_SAFE_CSS_VALUE = re.compile(r"^[\w\s#%.,()\"'+-]*$")


class TemplateValidationError(Exception):
    """La definizione inviata non è valida; `errors` elenca i motivi."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class BaseTemplateError(Exception):
    """L'HTML o gli schemi di una base non rispettano il contratto: errore del server."""


@dataclass
class CompiledTemplate:
    post_type: PostType
    jinja_content: str


# ── schemi ────────────────────────────────────────────────────────────────────────────────


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


def _is_array(node: dict) -> bool:
    types = node.get("type")
    return types == "array" or (isinstance(types, list) and "array" in types)


def _slide_variants(schema: dict) -> dict[str, dict]:
    """I tipi di slide dello schema del contenuto: type (la const) → schema della slide."""
    items = _resolve(schema["properties"]["slides"].get("items", {}), schema)
    variants = items.get("oneOf") or items.get("anyOf") or [items]
    result = {}
    for variant in variants:
        variant = _resolve(variant, schema)
        slide_type = _resolve(variant.get("properties", {}).get("type", {}), schema).get("const")
        if not isinstance(slide_type, str):
            raise BaseTemplateError("Every slide in generation_schema needs a const 'type'")
        result[slide_type] = variant
    return result


def _tokens(path: str) -> list[str]:
    """'steps[].title' → ['steps', '[]', 'title']."""
    tokens = []
    for part in path.split("."):
        name = part.removesuffix("[]")
        if not _IDENT.match(name):
            raise BaseTemplateError(f"Invalid data-field path: {path!r}")
        tokens.append(name)
        if part.endswith("[]"):
            tokens.append("[]")
    return tokens


def _walk(node: dict, tokens: list[str], root: dict) -> dict | None:
    """Lo schema del campo raggiunto da tokens partendo da node, o None se non esiste."""
    for token in tokens:
        node = _resolve(node, root)
        if token == "[]":
            if not _is_array(node):
                return None
            node = node.get("items", {})
        else:
            child = node.get("properties", {}).get(token)
            if child is None:
                return None
            node = child
    return _resolve(node, root)


# ── definizione: validazione e default ────────────────────────────────────────────────────


def _merge(defaults, value):
    """La definizione completata con i default (oggetti uniti ricorsivamente)."""
    if isinstance(defaults, dict) and isinstance(value, dict):
        return {k: _merge(defaults.get(k), value.get(k)) for k in defaults.keys() | value.keys()}
    return defaults if value is None else value


def _errors(validator: Draft202012Validator, instance: dict) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]


def _validator(post_type: PostType) -> Draft202012Validator:
    try:
        Draft202012Validator.check_schema(post_type.editable_rules_schema)
    except SchemaError as e:
        raise BaseTemplateError(f"editable_rules_schema of {post_type.name.value}: {e.message}") from e
    return Draft202012Validator(post_type.editable_rules_schema)


def validate_definition(definition: dict, post_type: PostType) -> dict:
    """Valida la definizione contro lo schema della base e la restituisce completata con i
    default. TemplateValidationError se non è valida."""
    validator = _validator(post_type)
    if errors := _errors(validator, definition):
        raise TemplateValidationError(errors)
    config = _merge(post_type.default_css_vars, definition)
    if errors := _errors(validator, config):
        # la definizione è valida ma i default della base no: errore del server
        raise BaseTemplateError(f"default_css_vars of {post_type.name.value}: " + "; ".join(errors))
    return config


# ── variabili CSS e font ──────────────────────────────────────────────────────────────────


def _css_value(xui: dict, value: Any, path: str) -> str:
    template = xui.get("cssValue", "{value}")
    if isinstance(template, dict):
        key = ("true" if value else "false") if isinstance(value, bool) else str(value)
        if key not in template:
            raise TemplateValidationError([f"{path}: {value!r} has no CSS value"])
        css = str(template[key])
    else:
        fields = value if isinstance(value, dict) else {"value": value}

        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in fields:
                raise BaseTemplateError(f"{path}: cssValue uses {{{name}}}, missing from the value")
            return str(fields[name])

        css = _PLACEHOLDER.sub(replace, str(template))
    if not _SAFE_CSS_VALUE.match(css):
        raise TemplateValidationError([f"{path}: invalid CSS value {css!r}"])
    return css


def _css_declarations(node: dict, value: Any, root: dict, path: str, out: list[str]) -> None:
    """Le dichiarazioni "--var: valore" dei campi con x-ui.cssVar, nell'ordine dello schema."""
    node = _resolve(node, root)
    xui = node.get("x-ui") or {}
    if "cssVar" in xui:
        # un campo oggetto con cssVar (es. un font) si scrive tutto insieme: non si scende
        if value is not None:
            out.append(f"{xui['cssVar']}: {_css_value(xui, value, path)};")
        return
    if isinstance(value, dict):
        for key, child in node.get("properties", {}).items():
            _css_declarations(child, value.get(key), root, f"{path}.{key}".lstrip("."), out)


def _css_vars(schema: dict, config: dict) -> str:
    declarations: list[str] = []
    _css_declarations(schema, config, schema, "", declarations)
    lines = "".join(f"\n      {d}" for d in declarations)
    return f"\n    :root {{{lines}\n    }}\n    "


def _font_meta(schema: dict) -> dict:
    """I metadati dei font ammessi (x-fontMeta in $defs): pesi disponibili e corsivo."""
    for definition in schema.get("$defs", {}).values():
        if isinstance(definition, dict) and isinstance(definition.get("x-fontMeta"), dict):
            return definition["x-fontMeta"]
    return {}


def _fonts_link(schema: dict, config: dict) -> str | None:
    """<link id="google-fonts"> con i font di config.fonts, nei soli pesi e stili usati dai ruoli
    tipografici; None se la definizione non ha font."""
    fonts = config.get("fonts")
    if not isinstance(fonts, dict) or not fonts:
        return None
    font_meta = _font_meta(schema)
    usage: dict[str, set[tuple[int, int]]] = {f["family"]: set() for f in fonts.values()}
    errors = []
    for role, style in (config.get("typography") or {}).items():
        if not isinstance(style, dict) or style.get("font") not in fonts:
            continue
        family = fonts[style["font"]]["family"]
        info = font_meta.get(family, {})
        weight = int(style.get("weight", 400))
        if info.get("weights") and weight not in info["weights"]:
            errors.append(f"typography.{role}.weight: {family} has no weight {weight}")
            continue
        # senza corsivo nella famiglia Google Fonts rifiuterebbe l'intero link: lo simula il browser
        italic = int(style.get("style") == "italic" and info.get("italic", True))
        usage[family].add((italic, weight))
    if errors:
        raise TemplateValidationError(errors)

    families = []
    for family, axes in usage.items():
        if not axes:
            weights = font_meta.get(family, {}).get("weights") or [400]
            axes = {(0, 400 if 400 in weights else weights[0])}
        if any(italic for italic, _ in axes):
            spec = "ital,wght@" + ";".join(f"{i},{w}" for i, w in sorted(axes))
        else:
            spec = "wght@" + ";".join(str(w) for w in sorted({w for _, w in axes}))
        families.append("family=" + quote_plus(f"{family}:{spec}", safe=":,;@"))
    href = "https://fonts.googleapis.com/css2?" + "&".join(families) + "&display=block"
    return f'<link id="{_FONTS_LINK_ID}" rel="stylesheet" href="{escape(href, quote=True)}">'


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


def _static(text: str) -> str:
    """Testo del sorgente HTML: se contiene delimitatori Jinja va protetto con {% raw %}."""
    if any(o in text for o in _JINJA_OPENERS):
        if "endraw" in text:
            raise BaseTemplateError("The base HTML contains 'endraw'")
        return "{% raw %}" + text + "{% endraw %}"
    return text


def _start_tag(element: _Element, raw: dict[str, str] | None = None) -> str:
    """Il tag di apertura senza gli attributi del contratto; i valori in `raw` (Jinja) vanno
    scritti così come sono, gli altri vengono riscritti con escape."""
    parts = [element.tag]
    for name, value in element.attrs:
        if name in _CONTRACT_ATTRS:
            continue
        if raw and name in raw:
            parts.append(f'{name}="{raw[name]}"')
        else:
            parts.append(name if value is None else f'{name}="{escape(value, quote=True)}"')
    return "<" + " ".join(parts) + ">"


def _element(node: _Element, inner: str, raw: dict[str, str] | None = None) -> str:
    if node.tag in _VOID:
        return _start_tag(node, raw)
    return _start_tag(node, raw) + inner + f"</{node.tag}>"


def _has_field(node: _Element, prefix: str) -> bool:
    return _find(node, lambda e: (e.get("data-field") or "").startswith(prefix)) is not None


def _section_style(style: str) -> str:
    """Lo style di una sezione con --slide-index / --slide-count presi dalla slide."""
    values = {"--slide-index": "{{ meta['position'] }}", "--slide-count": "{{ meta['total'] }}"}
    declarations = []
    for declaration in style.split(";"):
        name, _, value = declaration.partition(":")
        if name.strip():
            css = values.get(name.strip(), escape(value.strip(), quote=True))
            declarations.append(f"{name.strip()}: {css}")
    return "; ".join(declarations) + ";"


# ── compilazione ──────────────────────────────────────────────────────────────────────────


@dataclass
class _Scope:
    # schema della slide in corso (None per i tipi di post senza slide)
    slide: dict | None
    # liste aperte: percorso della lista ("steps") → variabile del ciclo
    lists: dict[str, str] = field(default_factory=dict)


class _Compiler:
    def __init__(self, post_type: PostType, css_vars: str, fonts_link: str | None):
        self.post_type = post_type
        self.schema = post_type.output_schema
        self.variants = _slide_variants(self.schema) if post_type.has_slides else {}
        self.css_vars = css_vars
        self.fonts_link = fonts_link
        self._vars_replaced = False

    # ── parte statica del documento: <head> con le sostituzioni ──

    def document(self, root: _Element) -> str:
        if not _find(root, lambda e: e.tag == "body"):
            raise BaseTemplateError("The base HTML has no <body>")
        if self.fonts_link and not _find(root, lambda e: e.tag == "link" and e.get("id") == _FONTS_LINK_ID):
            raise BaseTemplateError(f'The base HTML has no <link id="{_FONTS_LINK_ID}">')
        source = "".join(self.static(c) for c in root.children)
        if not self._vars_replaced:
            raise BaseTemplateError(f"The base HTML has no {_VARS_START} … {_VARS_END} block")
        return source

    def static(self, node) -> str:
        if isinstance(node, str):
            return _static(node)
        if node.tag == "link" and node.get("id") == _FONTS_LINK_ID and self.fonts_link:
            return self.fonts_link
        if node.tag == "style":
            return _element(node, _static(self.style("".join(c for c in node.children if isinstance(c, str)))))
        if node.tag == "body":
            return self.body(node)
        return _element(node, "".join(self.static(c) for c in node.children))

    def style(self, css: str) -> str:
        start, end = css.find(_VARS_START), css.find(_VARS_END)
        if start == -1 or end == -1:
            return css
        if end < start:
            raise BaseTemplateError(f"{_VARS_END} comes before {_VARS_START}")
        self._vars_replaced = True
        return css[: start + len(_VARS_START)] + self.css_vars + css[end:]

    # ── <body>: le sezioni d'esempio diventano le slide del post ──

    def body(self, body: _Element) -> str:
        sections = [c for c in body.children if isinstance(c, _Element) and c.get("data-type")]
        if not sections:
            raise BaseTemplateError('The base HTML has no <section data-type="..."> in <body>')
        out = [_start_tag(body), "\n"]
        emitted = False
        for child in body.children:
            if isinstance(child, str):
                if child.strip():
                    out.append(_static(child))
            elif child.get("data-type"):
                if not emitted:
                    out.append(self.slides(sections) if self.variants else self.single(sections))
                    emitted = True
            else:
                out.append(self.static(child))
        out.append("\n</body>")
        return "".join(out)

    def slides(self, sections: list[_Element]) -> str:
        types = [s.get("data-type") for s in sections]
        if len(set(types)) != len(types):
            raise BaseTemplateError(f"Duplicated data-type in the base HTML: {types}")
        if unknown := set(types) - self.variants.keys():
            raise BaseTemplateError(f"data-type not in generation_schema: {sorted(unknown)}")
        if missing := self.variants.keys() - set(types):
            raise BaseTemplateError(f"Slide types without a section in the base HTML: {sorted(missing)}")
        out = [
            (
                "{% for slide in data['slides'] %}"
                "{% set meta = {'index': '%02d' | format(loop.index),"
                " 'count': '%02d' | format(loop.length), 'position': loop.index, 'total': loop.length} %}\n"
            )
        ]
        for i, section in enumerate(sections):
            slide_type = section.get("data-type")
            keyword = "if" if i == 0 else "elif"
            out.append(f"{{% {keyword} slide['type'] == {json.dumps(slide_type)} %}}\n")
            out.append(self.section(section, _Scope(slide=self.variants[slide_type])))
            out.append("\n")
        out.append("{% endif %}\n{% endfor %}")
        return "".join(out)

    def single(self, sections: list[_Element]) -> str:
        if len(sections) != 1:
            raise BaseTemplateError(
                f"A post type without slides needs exactly one <section data-type>, found {len(sections)}"
            )
        head = "{% set meta = {'index': '01', 'count': '01', 'position': 1, 'total': 1} %}\n"
        return head + self.section(sections[0], _Scope(slide=None))

    def section(self, section: _Element, scope: _Scope) -> str:
        style = section.get("style")
        raw = {"style": _section_style(style)} if style else None
        inner = "".join(self.node(c, scope) for c in section.children)
        return _element(section, inner, raw)

    # ── contenuto delle slide ──

    def node(self, node, scope: _Scope) -> str:
        if isinstance(node, str):
            return _static(node)
        path = node.get("data-field")
        if not path:
            return _element(node, "".join(self.node(c, scope) for c in node.children))
        if path.startswith("meta."):
            return _element(node, self.meta(path, scope))

        expr, schema = self.field_expr(path, scope)
        if _is_array(schema):
            return _element(node, self.list_items(node, path, expr, scope))
        if any(isinstance(c, _Element) for c in node.children):
            return _element(node, "{{ " + expr + " | svg }}")
        return _element(node, "{{ " + expr + " }}")

    def field_expr(self, path: str, scope: _Scope) -> tuple[str, dict]:
        """L'espressione Jinja di un data-field e lo schema del campo."""
        tokens = _tokens(path)
        schema = self.schema_of(tokens, scope)

        def subscripts(ts: list[str]) -> str:
            return "".join(f"[{json.dumps(t)}]" for t in ts)

        # un campo di una voce: 'steps[].title' dentro il ciclo su 'steps'
        if "[]" in tokens:
            prefix, sep, rest = path.rpartition("[].")
            var = scope.lists.get(prefix)
            if not sep or var is None:
                raise BaseTemplateError(f"data-field={path!r} is outside the list {prefix or path!r}")
            return var + subscripts(_tokens(rest)), schema

        if scope.slide is not None and _walk(scope.slide, tokens[:1], self.schema) is not None:
            return "slide" + subscripts(tokens), schema
        return "data" + subscripts(tokens), schema

    def schema_of(self, tokens: list[str], scope: _Scope) -> dict:
        for root in (scope.slide, self.schema):
            if root is not None and _walk(root, tokens[:1], self.schema) is not None:
                schema = _walk(root, tokens, self.schema)
                if schema is None:
                    break
                return schema
        if len(tokens) == 1 and tokens[0] in RUNTIME_FIELDS:
            return {"type": "string"}
        raise BaseTemplateError(f"data-field={'.'.join(tokens)!r} has no matching field in generation_schema")

    def list_items(self, node: _Element, path: str, expr: str, scope: _Scope) -> str:
        template = next((c for c in node.children if isinstance(c, _Element)), None)
        if template is None:
            raise BaseTemplateError(f"data-field={path!r} is a list but has no sample item")
        var = f"item{len(scope.lists) + 1}"
        inner_scope = _Scope(slide=scope.slide, lists={**scope.lists, path: var})
        if _has_field(template, f"{path}[]."):
            item = self.node(template, inner_scope)
        else:
            # lista di testi: la voce è il contenuto del modello
            item = _element(template, "{{ " + var + " }}")
        return f"{{% for {var} in {expr} %}}{item}{{% endfor %}}"

    @staticmethod
    def meta(path: str, scope: _Scope) -> str:
        if path in ("meta.index", "meta.count"):
            return "{{ meta[" + json.dumps(path.split(".")[1]) + "] }}"
        if path == "meta.item":
            if not scope.lists:
                raise BaseTemplateError("data-field='meta.item' is outside a list")
            return "{{ '%02d' | format(loop.index) }}"
        raise BaseTemplateError(f"Unknown data-field {path!r}: use meta.index, meta.count or meta.item")


def compile_definition(definition: dict, post_type: PostType) -> CompiledTemplate:
    """Valida la definizione e genera il template Jinja2 dalla base del tipo di post.

    TemplateValidationError se la definizione non è valida (errore del client),
    BaseTemplateError se la base non rispetta il contratto (errore del server).
    """
    config = validate_definition(definition, post_type)
    schema = post_type.editable_rules_schema
    compiler = _Compiler(
        post_type,
        css_vars=_css_vars(schema, config),
        fonts_link=_fonts_link(schema, config),
    )
    source = compiler.document(_parse_html(post_type.base_html))

    try:
        ast = _env.parse(source)
    except TemplateError as e:
        raise BaseTemplateError(f"Generated template does not compile: {e}") from e
    unknown = meta.find_undeclared_variables(ast) - CONTEXT_VARIABLES
    if unknown:
        raise BaseTemplateError(f"Generated template uses unknown variables: {sorted(unknown)}")

    return CompiledTemplate(post_type=post_type, jinja_content=source)


def render_jinja(jinja_content: str, data: dict) -> str:
    """Il template salvato con il contenuto di un post: l'HTML pronto per il browser."""
    try:
        return _env.from_string(jinja_content).render(data=data)
    except TemplateError as e:
        raise TemplateValidationError([f"Jinja rendering failed: {e}"]) from e


def page_count(post_type: PostType, content: dict) -> int:
    """Le immagini che il contenuto produce: una per slide, o una sola per i tipi senza slide."""
    if post_type.has_slides:
        return len(content.get("slides") or [])
    return 1


# ── anteprime ─────────────────────────────────────────────────────────────────────────────


def sample_data(post_type: PostType) -> dict:
    """Il contenuto d'esempio della base, per le anteprime: il sample_content del
    generation.json (non va nel prompt) con l'handle d'esempio dell'HTML."""
    example = post_type.generation_schema.get("sample_content")
    if not isinstance(example, dict):
        raise BaseTemplateError(f"{post_type.name.value} has no sample_content")
    handle = _find(_parse_html(post_type.base_html), lambda e: e.get("data-field") == "handle")
    return {**example, "handle": _text(handle) if handle else "@autopost"}


# anteprime contemporanee al massimo: ognuna avvia un browser, le altre aspettano il turno
_PREVIEW_SLOTS = threading.BoundedSemaphore(2)


def render_template_preview(jinja_content: str, post_type: PostType) -> str:
    """La prima slide del template disegnata con i dati d'esempio della sua base, come data URL
    JPEG (data:image/jpeg;base64,...): il valore di Template.preview_image.

    Sincrona e lenta (avvia un browser): dal codice asincrono va chiamata con asyncio.to_thread.
    TemplateValidationError se il Jinja non si disegna, RenderError se il browser fallisce.
    """
    html = render_jinja(jinja_content, sample_data(post_type))
    with _PREVIEW_SLOTS:
        preview = render_preview(html, SLIDE_WIDTH, SLIDE_HEIGHT, max_images=1)
    if not preview.images:
        raise PreviewError("The template rendered no image")
    return "data:image/jpeg;base64," + base64.b64encode(preview.images[0]).decode("ascii")


# anteprima di ogni base con i suoi default, per versione: (id, updated_at) → data URL
_base_previews: dict[tuple[int, datetime], str] = {}
_base_previews_lock = threading.Lock()


def base_preview(post_type: PostType) -> str:
    """L'anteprima della base con i valori di default, calcolata una volta per versione della
    base e per processo. Stessi errori di compile_definition e render_template_preview."""
    key = (post_type.id, post_type.updated_at)
    with _base_previews_lock:
        if key in _base_previews:
            return _base_previews[key]
    compiled = compile_definition(post_type.default_css_vars, post_type)
    image = render_template_preview(compiled.jinja_content, post_type)
    with _base_previews_lock:
        _base_previews[key] = image
    return image

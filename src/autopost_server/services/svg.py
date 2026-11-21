"""Sanificazione degli SVG generati da Claude (es. content.decoration del single post).

L'SVG arriva da un modello e finisce nell'HTML della slide come markup, quindi non è fidato:
restano solo gli elementi e gli attributi di disegno in elenco. Vengono scartati script, stili,
<foreignObject>, gestori di eventi (on*), riferimenti esterni (href e url() che non puntano a un
#id del documento) e tutto ciò che sta fuori da un <svg>. Un elemento non ammesso viene scartato
con tutto il suo contenuto.

È il filtro Jinja `svg` dei template (services/templates.py): {{ data["content"]["decoration"] | svg }}.
"""

import re
from html import escape
from html.parser import HTMLParser

from markupsafe import Markup

# nomi in minuscolo: html.parser li normalizza così, e il parser HTML del browser ripristina le
# maiuscole degli elementi e degli attributi SVG (lineargradient → linearGradient, viewbox → viewBox)
_TAGS = frozenset({
    "svg", "g", "defs", "symbol", "use", "title", "desc",
    "path", "circle", "ellipse", "line", "polyline", "polygon", "rect",
    "lineargradient", "radialgradient", "stop", "clippath", "mask",
    "text", "tspan",
})

_ATTRS = frozenset({
    "xmlns", "xmlns:xlink", "id", "class", "viewbox", "preserveaspectratio", "width", "height",
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr",
    "d", "points", "pathlength", "transform", "offset",
    "fill", "fill-opacity", "fill-rule", "clip-rule", "opacity", "visibility",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "vector-effect", "paint-order",
    "stop-color", "stop-opacity", "gradientunits", "gradienttransform", "spreadmethod",
    "clip-path", "clippathunits", "mask", "maskunits",
    "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "letter-spacing",
    "href", "xlink:href",
})

_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
})
_HREF_ATTRS = frozenset({"href", "xlink:href"})
# url(...) ammesso solo verso un #id del documento
_EXTERNAL_URL = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.IGNORECASE)
_SCHEMES = re.compile(r"(javascript|data|vbscript):", re.IGNORECASE)


def _safe_attr(name: str, value: str | None) -> bool:
    if value is None or name not in _ATTRS:
        return False
    compact = "".join(value.split())
    if _SCHEMES.search(compact) or _EXTERNAL_URL.search(value):
        return False
    if name in _HREF_ATTRS:
        return value.strip().startswith("#")
    return True


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        # elementi aperti: (tag, tenuto nell'output)
        self._stack: list[tuple[str, bool]] = []
        # profondità dentro un elemento scartato: il suo contenuto si scarta tutto
        self._skip = 0

    def _in_svg(self) -> bool:
        return any(tag == "svg" and kept for tag, kept in self._stack)

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        kept = not self._skip and tag in _TAGS and (tag == "svg" or self._in_svg())
        if kept:
            parts = [tag] + [
                f'{name}="{escape(value, quote=True)}"' for name, value in attrs if _safe_attr(name, value)
            ]
            self.out.append("<" + " ".join(parts) + ("/>" if self_closing else ">"))
        if not self_closing:
            self._stack.append((tag, kept))
            if not kept:
                self._skip += 1

    def handle_starttag(self, tag, attrs):
        # un elemento void HTML (<img>, <br>...) non ha chiusura: senza questo resterebbe aperto
        # e farebbe scartare tutto ciò che segue
        self._open(tag, attrs, self_closing=tag in _VOID)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, self_closing=True)

    def handle_endtag(self, tag):
        if not any(t == tag for t, _ in self._stack):
            return
        while self._stack:
            t, kept = self._stack.pop()
            if kept:
                self.out.append(f"</{t}>")
            else:
                self._skip -= 1
            if t == tag:
                break

    def handle_data(self, data):
        if not self._skip and self._in_svg():
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        self.close()
        while self._stack:
            t, kept = self._stack.pop()
            if kept:
                self.out.append(f"</{t}>")
        return "".join(self.out)


def sanitize_svg(value) -> Markup:
    """Il markup SVG ripulito, pronto da inserire nell'HTML (vuoto se value non è una stringa)."""
    if not isinstance(value, str):
        return Markup("")
    sanitizer = _Sanitizer()
    sanitizer.feed(value)
    return Markup(sanitizer.result())

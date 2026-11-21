"""Il formato del contenuto di un tipo di post: dal JSON semplice di generation.json allo schema
della richiesta strutturata a Claude, e i controlli leggeri sull'output.

Il "format" è un esempio del JSON da generare in cui ogni valore foglia è la descrizione di
cosa scrivere in quel campo (in inglese: la legge Claude), per esempio:

    {
      "category": "Series label, 1-2 words",
      "slides": [
        {"type": "cover", "title": "Promise with an open loop, max 8 words"},
        {"type": "steps", "title": "...", "steps": [{"title": "1-2 words", "text": "One line"}]}
      ],
      "hashtags": ["One hashtag, lowercase"]
    }

Regole della conversione in JSON Schema (to_json_schema):
- una stringa è un campo di testo, con la stringa come description ("..." = nessuna);
- un oggetto ha tutti i suoi campi obbligatori e nessun campo in più;
- una lista di oggetti che hanno tutti un campo "type" è una lista di varianti: ogni oggetto è
  una variante e il suo "type" è la costante che la distingue (i tipi di slide);
- ogni altra lista descrive i suoi elementi con il primo.

Lo schema garantisce la struttura (l'API vincola la generazione), non i conteggi, l'ordine delle
slide o i campi vuoti: per quelli ci sono "limits" e "sequence" di generation.json, verificati da
content_errors sull'output.
"""

from typing import Any

# percorso di una lista nel formato → (minimo, massimo) elementi, es. "slides[].steps": [2, 5]
Limits = dict[str, list[int]]


def _is_variant_list(items: list) -> bool:
    return bool(items) and all(isinstance(i, dict) and isinstance(i.get("type"), str) for i in items)


def _count_text(bounds: list[int]) -> str:
    low, high = bounds
    return f"exactly {low} items" if low == high else f"{low} to {high} items"


def to_json_schema(fmt: dict[str, Any], limits: Limits | None = None) -> dict[str, Any]:
    """Lo schema JSON della richiesta strutturata, dal formato semplice di un tipo di post.

    È anche lo schema che services/templates.py usa per i data-field e i data-type della base.
    """
    limits = limits or {}

    def convert(node: Any, path: str) -> dict[str, Any]:
        if isinstance(node, dict):
            return {
                "type": "object",
                "properties": {k: convert(v, f"{path}.{k}" if path else k) for k, v in node.items()},
                "required": list(node),
                "additionalProperties": False,
            }
        if isinstance(node, list):
            item_path = f"{path}[]"
            if _is_variant_list(node):
                items = {"anyOf": [variant(v, item_path) for v in node]}
            else:
                items = convert(node[0] if node else "...", item_path)
            schema = {"type": "array", "items": items}
            if path in limits:
                schema["description"] = _count_text(limits[path])
            return schema
        if isinstance(node, bool):
            return {"type": "boolean"}
        if isinstance(node, int | float):
            return {"type": "number"}
        schema = {"type": "string"}
        if isinstance(node, str) and node.strip() not in ("", "..."):
            schema["description"] = node
        return schema

    def variant(node: dict[str, Any], path: str) -> dict[str, Any]:
        schema = convert({k: v for k, v in node.items() if k != "type"}, path)
        schema["properties"] = {"type": {"const": node["type"]}, **schema["properties"]}
        schema["required"] = ["type", *schema["required"]]
        return schema

    return convert(fmt, "")


# ── controlli sull'output ─────────────────────────────────────────────────────────────────


def _empty_errors(node: Any, path: str) -> list[str]:
    if isinstance(node, str):
        return [] if node.strip() else [f"{path}: empty text"]
    if isinstance(node, list):
        if not node:
            return [f"{path}: empty list"]
        return [e for i, item in enumerate(node) for e in _empty_errors(item, f"{path}/{i}")]
    if isinstance(node, dict):
        return [e for k, v in node.items() for e in _empty_errors(v, f"{path}/{k}" if path else k)]
    return []


def _values_at(node: Any, path: str) -> list[tuple[str, Any]]:
    """I valori al percorso di limits (es. "slides[].steps") con il loro percorso concreto."""
    found = [("", node)]
    for part in path.split("."):
        name, is_list = part.removesuffix("[]"), part.endswith("[]")
        step = []
        for where, value in found:
            if isinstance(value, dict) and name in value:
                child, child_path = value[name], f"{where}/{name}" if where else name
                if is_list and isinstance(child, list):
                    step += [(f"{child_path}/{i}", item) for i, item in enumerate(child)]
                else:
                    step.append((child_path, child))
        found = step
    return found


def _limit_errors(content: dict[str, Any], limits: Limits) -> list[str]:
    errors = []
    for path, (low, high) in limits.items():
        for where, value in _values_at(content, path):
            if isinstance(value, list) and not low <= len(value) <= high:
                errors.append(f"{where}: {len(value)} items, expected {low} to {high}")
    return errors


def _one_of(values: list[str]) -> str:
    return values[0] if len(values) == 1 else " or ".join(values)


def sequence_errors(content: dict[str, Any], sequence: dict[str, Any]) -> list[str]:
    """Le regole di sequence violate dalle slide: l'ordine non si esprime con lo schema."""
    slides = content.get("slides")
    types = [s.get("type") for s in slides if isinstance(s, dict)] if isinstance(slides, list) else []
    if not types:
        return []
    errors = []
    if (first := sequence.get("first")) and types[0] not in first:
        errors.append(f"slides/0: the first slide must be {_one_of(first)}, not {types[0]}")
    if (last := sequence.get("last")) and types[-1] not in last:
        errors.append(f"slides/{len(types) - 1}: the last slide must be {_one_of(last)}, not {types[-1]}")
    for i, t in enumerate(types):
        if t in sequence.get("only_first", []) and i != 0:
            errors.append(f"slides/{i}: a {t} slide can only be the first slide")
        if t in sequence.get("only_last", []) and i != len(types) - 1:
            errors.append(f"slides/{i}: a {t} slide can only be the last slide")
        if sequence.get("no_consecutive_repeat") and i > 0 and t == types[i - 1]:
            errors.append(f"slides/{i}: same type as the previous slide ({t})")
    return errors


def content_errors(content: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """I problemi dell'output che lo schema non esclude: campi vuoti (un output che si interrompe
    viene chiuso con valori vuoti), conteggi fuori da limits e ordine delle slide fuori da
    sequence. spec è il generation.json del tipo di post."""
    return (
        _empty_errors(content, "")
        + _limit_errors(content, spec.get("limits", {}))
        + sequence_errors(content, spec.get("sequence", {}))
    )

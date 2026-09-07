"""Best-effort deterministic signature -> draft Overload[] parser.

4D's doc signatures use a distinctive bracketing convention: each optional
parameter (or optional tail) is wrapped in its own `{ ... }` blob, often
starting with a literal `;` *inside* the braces (e.g.
`{aTable : Table} {; ...(aField : Field {; order : >, <})} {; *}`), rather
than one flat top-level `;`-separated list where optionality is a per-item
flag. This module does a small recursive-descent parse over that
convention to produce a draft, schema-shaped `OverloadElement[]`.

This is Stage 3's mechanical first draft, not ground truth: for adversarial
signatures (nested groups, literal-symbol markers, cardinality semantics
that syntax alone can't settle) callers should treat the result as a
starting point to be corrected by a hand-authored semantic overlay (see
pipeline/semantic_overlays/).
"""
from __future__ import annotations

import re


_PSEUDO_NAMES = {"operator", "expression", "any", "variant", "untypedarray"}


def _single_type_ref(token: str) -> dict:
    token = token.strip()
    if re.fullmatch(r"[^\w\s]{1,2}", token):
        return {"kind": "literal_symbols", "symbols": [token]}
    if token.lower() in _PSEUDO_NAMES:
        # preserve schema's canonical casing for the known enum values
        canon = {"operator": "Operator", "expression": "Expression", "any": "any",
                 "variant": "Variant", "untypedarray": "UntypedArray"}[token.lower()]
        return {"kind": "pseudo", "name": canon}
    return {"kind": "concrete", "name": token}


def _type_ref(type_str: str):
    """Guess a TypeRef (or, for multi-type params like "Text, Real, Date,
    Time", an array of TypeRef per-token) from a raw doc type string.

    Adjacent literal-symbol tokens are merged into a single
    `literal_symbols` TypeRef; a lone token becomes a single TypeRef;
    otherwise each comma-separated alternative becomes its own TypeRef in
    an array (per the schema's "array of TypeRef" multi-type allowance).
    """
    tokens = [t.strip() for t in type_str.split(",") if t.strip()]
    if not tokens:
        return {"kind": "concrete", "name": type_str.strip()}
    if len(tokens) == 1:
        return _single_type_ref(tokens[0])
    if all(re.fullmatch(r"[^\w\s]{1,2}", t) for t in tokens):
        return {"kind": "literal_symbols", "symbols": tokens}
    return [_single_type_ref(t) for t in tokens]


def _parse_token(token: str) -> dict:
    token = token.strip()
    if token == "*":
        return {"kind": "literal", "value": "*"}
    if token.startswith("..."):
        rest = token[3:].strip()
        if rest.startswith("("):
            inner = rest[1:]
            if inner.endswith(")"):
                inner = inner[:-1]
            return {"kind": "group", "members": _parse_items(inner)}
        m = re.match(r"^(?P<name>\$?\w+)\s*:\s*(?P<type>.+)$", rest)
        if m:
            return {
                "kind": "group",
                "members": [{"kind": "param", "name": m.group("name"), "type": m.group("type").strip(), "optional": False}],
            }
        return {"kind": "group", "members": [], "raw": rest}
    m = re.match(r"^(?P<name>\*|\$?\w+)\s*:\s*(?P<type>.+)$", token)
    if m:
        return {"kind": "param", "name": m.group("name"), "type": m.group("type").strip()}
    return {"kind": "unknown", "raw": token}


def _parse_items(s: str) -> list[dict]:
    """Recursive-descent split of a signature body into top-level slots,
    each tagged `optional` per the brace-wrapping convention.
    """
    items: list[dict] = []
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i] in " \t\n":
            i += 1
        if i >= n:
            break
        if s[i] == ";":
            i += 1
            continue
        if s[i] == "{":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            inner = s[i + 1 : j - 1]
            inner = inner.lstrip()
            if inner.startswith(";"):
                inner = inner[1:]
            for it in _parse_items(inner):
                it["optional"] = True
                items.append(it)
            i = j
            continue
        depth = 0
        j = i
        while j < n:
            c = s[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "{" and depth == 0:
                break
            elif c == ";" and depth == 0:
                break
            j += 1
        token = s[i:j].strip()
        if token:
            parsed = _parse_token(token)
            parsed.setdefault("optional", False)
            items.append(parsed)
        i = j
    return items


def _to_overload_element(item: dict, is_last: bool) -> dict | None:
    kind = item["kind"]
    if kind == "param":
        return {
            "name": item["name"],
            "type": _type_ref(item["type"]),
            "direction": "in",
            "optional": item.get("optional", False),
        }
    if kind == "literal":
        return {
            "name": item["value"],
            "type": {"kind": "literal_symbols", "symbols": [item["value"]]},
            "direction": "in",
            "optional": item.get("optional", False),
        }
    if kind == "group":
        members = []
        for m in item.get("members", []):
            if m["kind"] != "param":
                continue
            members.append(
                {
                    "name": m["name"],
                    "type": _type_ref(m["type"]),
                    "direction": "in",
                    "optional": m.get("optional", False),
                }
            )
        return {
            "name": "group",
            "members": members,
            "cardinality": {"min": 0 if item.get("optional") else 1, "max": None},
            "position": "trailing" if is_last else "embedded",
        }
    return None


def draft_overload_params(signature_text: str) -> tuple[list[dict], list[str], dict | None]:
    """Return (overload_elements, notes, returns)."""
    notes: list[str] = []
    text = signature_text.strip()
    m = re.search(r"\((.*)\)\s*(?::\s*(.+))?\s*$", text)
    if not m:
        # No top-level '(...)' parameter list at all -- this is a valid
        # shape for a zero-argument command/function, e.g. the bare
        # "Monitored activity : Collection" signature. Fall back to
        # matching just a trailing ": ReturnType" after the bolded name,
        # with an empty parameter list, rather than dropping the return
        # type entirely (see pipeline/semantic_overlays/*.json's several
        # pre-existing hand-authored notes documenting this exact gap).
        m2 = re.search(r":\s*(.+)\s*$", text)
        if not m2:
            return [], [f"could not locate a top-level '(...)' parameter list in: {signature_text!r}"], None
        return [], [], _type_ref(m2.group(1))

    body, return_type = m.group(1), m.group(2)
    items = _parse_items(body)
    elements: list[dict] = []
    for idx, item in enumerate(items):
        el = _to_overload_element(item, is_last=(idx == len(items) - 1))
        if el is None:
            notes.append(f"could not parse item: {item!r}")
            continue
        elements.append(el)

    returns = _type_ref(return_type) if return_type else None
    return elements, notes, returns

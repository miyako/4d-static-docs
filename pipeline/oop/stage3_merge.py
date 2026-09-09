#!/usr/bin/env python3
"""Stage O3 — merge parsed signatures with HTML enrichment into IR entries.

One `CommandEntry` per member is written to `out/oop_stage3_ir_full/<id>.json`,
each independently schema-valid. Inputs:

    O0  out/oop_manifest.json         which members are in scope
    O1  out/oop_stage1_raw.json       HTML enrichment
    O2  out/oop_signatures.json       parsed, round-tripped signatures
    O2b out/oop_param_conflicts.json  findings consumed here (nullability, case)

The highest-value enrichment is the constant resolution: a parameter typed
merely `Integer` whose description names constants (backticked in the source,
captured as `<code>` spans by O1) is upgraded from a bare concrete type to an
`enum_ref` pointing at a generated enum holding exactly the constants that
parameter accepts. Pointing at the whole registry theme would over-state the
accepted set, so the generated enums are member-scoped.

Usage:
    python3 pipeline/oop/stage3_merge.py [--repo-root PATH] [--no-cache]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oopcommon as oop  # noqa: E402
import stage2b_crosscheck as crosscheck  # noqa: E402
from common.cache import read_cached, write_cached  # noqa: E402

PSEUDO_TYPES = {"Operator", "Expression", "any", "Variant", "UntypedArray"}

# Prose markers used to decide property write access. Deliberately narrow: a
# property is assumed writable only when the docs do not say otherwise, which
# matches how the 4D docs are written (read-only is always called out).
READ_ONLY_MARKERS = (
    "is read-only",
    "read-only property",
    "this property is read only",
    "is read only",
)
WRITABLE_MARKERS = (
    "you can set",
    "this property can be set",
    "is read/write",
    "read-write property",
)

THROWS_MARKERS = (
    "throws an error",
    "an error is thrown",
    "generates an error",
    "error is generated",
    "raises an error",
)
RETURNS_NULL_MARKERS = (
    "returns null",
    "returns undefined",
    "null is returned",
    "undefined is returned",
)

# History "Release" cells are spelled inconsistently: "21", "18 R6", "v16 R5".
_VERSION_RE = re.compile(r"^\s*v?\s*(\d+(?:\s*R\d+)?)\s*$", re.IGNORECASE)

# Doc type spellings inside returned-object tables are lower-case and
# occasionally prose-like; map them onto the canonical 4D type names used
# everywhere else in the IR.
SHAPE_TYPE_CANON = {
    "boolean": "Boolean",
    "bool": "Boolean",
    "text": "Text",
    "string": "Text",
    "number": "Real",
    "real": "Real",
    "integer": "Integer",
    "longint": "Integer",
    "object": "Object",
    "collection": "Collection",
    "collection of objects": "Collection",
    "collection of texts": "Collection",
    "collection of strings": "Collection",
    "date": "Date",
    "time": "Time",
    "picture": "Picture",
    "blob": "Blob",
    "pointer": "Pointer",
}


def type_ref(name: str | None) -> dict | None:
    """A raw type name from either source -> a schema TypeRef."""
    if not name:
        return None
    value = oop.strip_zws(name).strip().strip("*` ")
    if not value:
        return None
    if value in PSEUDO_TYPES:
        return {"kind": "pseudo", "name": value}
    if value.lower() in ("any", "any type", "variant"):
        return {"kind": "pseudo", "name": "any"}
    if value.lower() == "expression":
        return {"kind": "pseudo", "name": "Expression"}
    return {"kind": "concrete", "name": value}


def normalize_version(text: str) -> str | None:
    match = _VERSION_RE.match(oop.strip_zws(text))
    if not match:
        return None
    return re.sub(r"\s+", "-", match.group(1).strip())


def shape_type_ref(name: str | None) -> dict | None:
    if not name:
        return None
    canonical = SHAPE_TYPE_CANON.get(oop.strip_zws(name).strip().lower())
    return type_ref(canonical or name)


def history_facts(history: dict | None) -> dict:
    """Turn a History table into sinceVersion / deprecated / behavior changes.

    The tables are two-column (Release, Changes) and list newest first. "Added"
    marks introduction; anything else at an older release is a behavior change.
    """
    facts: dict = {}
    if not history:
        return facts
    changes = []
    introduced: str | None = None
    for row in history["rows"]:
        cells = row["cells"]
        raw_release = cells.get("Release", "")
        release = normalize_version(raw_release) or oop.strip_zws(raw_release).strip()
        note = oop.strip_zws(cells.get("Changes", "")).strip()
        if not release and not note:
            continue
        lowered = note.lower()
        # Only an exact "Added" marks introduction. "Added status 7 and 8" is a
        # behavior change on an existing member and must not be mistaken for
        # the version the member first appeared in — the tables list newest
        # first, so the introduction row is the last one.
        if lowered == "added":
            introduced = release
            continue
        if "deprecated" in lowered or "removed" in lowered:
            facts["deprecated"] = True
        if release:
            changes.append({"release": release, "change": note})
    if introduced:
        facts["sinceVersion"] = introduced
    if changes:
        facts["versionBehaviorChanges"] = changes
    return facts


def collect_constant_mentions(texts: list[str], code_spans: list[str],
                              registry: dict) -> list[str]:
    """Registry constant names named by a parameter's documentation.

    Backticked spans are trusted directly. Plain prose is only scanned for
    constants whose name is distinctive enough (three or more words, or a
    known 4D prefix) so that ordinary English does not produce false hits.
    """
    found: list[str] = []
    seen: set[str] = set()
    for span in code_spans:
        name = oop.strip_zws(span).strip()
        if name in registry and name not in seen:
            seen.add(name)
            found.append(name)
    haystack = " ".join(texts)
    if haystack:
        for name in registry:
            if name in seen:
                continue
            distinctive = name.count(" ") >= 2 or name.split(" ")[0] in (
                "dk", "ck", "sk", "wk", "zk", "mk", "ak", "Use",
            )
            if not distinctive:
                continue
            if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", haystack):
                seen.add(name)
                found.append(name)
    return found


def constant_values(names: list[str], registry: dict) -> tuple[list[dict], set[str]]:
    values = []
    themes: set[str] = set()
    for name in names:
        entries = registry.get(name) or []
        if not entries:
            continue
        entry = entries[0]
        themes.add(entry.get("theme", ""))
        raw = entry.get("value")
        try:
            value: object = int(raw)
        except (TypeError, ValueError):
            value = raw
        values.append({"name": name, "value": value})
    return values, {t for t in themes if t}


def constant_tables(section: dict | None) -> list[dict]:
    """Constant/Value/Comment tables in a member section.

    27 members document their accepted constants in such a table rather than
    inline in the Parameter row. The sub-heading above the table says what the
    constants belong to ("options parameter", "status and statusText"), which
    is what makes attaching them to the right slot possible.
    """
    if not section:
        return []
    out = []
    for sub in section.get("subsections", []):
        table = sub.get("table")
        if not table:
            continue
        headers = [h.lower() for h in table["headers"]]
        if "constant" not in headers and "constants" not in headers:
            continue
        name_key = next(
            h for h in table["headers"] if h.lower() in ("constant", "constants")
        )
        value_key = next(
            (h for h in table["headers"] if h.lower() == "value"), None
        )
        comment_key = next(
            (h for h in table["headers"] if h.lower() in ("comment", "description")),
            None,
        )
        values = []
        for row in table["rows"]:
            cells = row["cells"]
            name = oop.strip_zws(cells.get(name_key, "")).strip()
            if not name:
                continue
            raw_value = oop.strip_zws(cells.get(value_key, "")).strip() if value_key else ""
            try:
                value: object = int(raw_value)
            except (TypeError, ValueError):
                value = raw_value or None
            record = {"name": name, "value": value}
            if comment_key and cells.get(comment_key):
                record["description"] = oop.strip_zws(cells[comment_key]).strip()
            values.append(record)
        if values:
            out.append({"title": sub.get("title") or "", "values": values})
    return out


def prose_constants_for_param(section: dict | None, name: str,
                              registry: dict) -> list[str]:
    """Constants named in a Description paragraph that explicitly refers to
    this parameter.

    A bare mention of the parameter's name is not enough: Entity.save's page
    says "the automatic merge **mode** is not available ... will result in a
    `dk status stamp has changed` error", which names `mode` but is talking
    about a returned status, not an accepted argument. The paragraph must
    refer to the parameter as a parameter — "in the mode parameter",
    "parameter option", or a backticked `mode` — before its constants are
    attributed to it.
    """
    if not section:
        return []
    escaped = re.escape(name)
    pattern = re.compile(
        rf"(?:(?<![\w.]){escaped}\s+parameter\b"
        rf"|\bparameter\s+{escaped}(?![\w])"
        rf"|`{escaped}`)",
        re.IGNORECASE,
    )
    found: list[str] = []
    for block in section["descriptionBlocks"]:
        if not pattern.search(block["text"]):
            continue
        for span in block["codeSpans"]:
            candidate = oop.strip_zws(span).strip()
            if candidate in registry and candidate not in found:
                found.append(candidate)
    return found


def param_description(entry_id: str, name: str, section: dict,
                      syntax_record: dict) -> tuple[str, list[str]]:
    """Description text plus backticked spans for one parameter, from both
    sources. syntaxEN keeps the backticks; the HTML keeps them as <code>.
    """
    texts: list[str] = []
    spans: list[str] = []
    for row in (syntax_record.get("Params") or []):
        if not isinstance(row, list) or len(row) < 4:
            continue
        if crosscheck.norm_name(row[0]) and crosscheck.norm_name(row[0]).lower() in (
            name.lower(), crosscheck.strip_variadic_suffix(name).lower()
        ):
            texts.append(row[3])
            spans.extend(re.findall(r"`([^`]+)`", row[3]))
    table = section.get("paramTable") if section else None
    if table:
        params, _result = crosscheck.table_params(table)
        for param in params:
            if param["name"].lower() in (
                name.lower(), crosscheck.strip_variadic_suffix(name).lower()
            ):
                texts.append(param["description"])
                spans.extend(param.get("codeSpans", []))
    # Both sources usually carry the same sentence, differing only in that
    # syntaxEN keeps the markdown backticks. Compare on the stripped form so
    # the merged description is not doubled.
    merged: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = oop.strip_zws(text).strip()
        if not cleaned:
            continue
        fingerprint = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged.append(cleaned)
    return " ".join(merged), spans


def description_text(section: dict | None) -> tuple[str | None, list[str]]:
    if not section:
        return None, []
    blocks = [
        b for b in section["descriptionBlocks"]
        if b["underHeading"] in (None, "Description")
    ]
    if not blocks:
        blocks = section["descriptionBlocks"]
    text = "\n\n".join(b["text"] for b in blocks)
    spans = [s for b in blocks for s in b["codeSpans"]]
    return (text or None), spans


def build_returns_shape(section: dict | None) -> dict | None:
    if not section or not section["returnsShapeTables"]:
        return None
    table = section["returnsShapeTables"][0]["table"]
    headers = {h.lower(): h for h in table["headers"]}
    prop_key = headers.get("property")
    type_key = headers.get("type")
    desc_key = headers.get("description")
    if not prop_key:
        return None
    properties: dict[str, dict] = {}
    pending_condition: str | None = None
    for row in table["rows"]:
        cells = row["cells"]
        name = oop.strip_zws(cells.get(prop_key, "")).strip()
        description = oop.strip_zws(cells.get(desc_key, "")).strip() if desc_key else ""
        raw_type = cells.get(type_key, "") if type_key else ""
        if not name:
            # A nameless row with a description is a group condition heading
            # ("Available only in case of error:") that applies to the rows
            # under it.
            if description:
                pending_condition = description.rstrip(":")
            continue
        entry: dict = {
            "type": shape_type_ref(raw_type) or {"kind": "pseudo", "name": "any"}
        }
        if description:
            entry["description"] = description
        if pending_condition:
            entry["presentWhen"] = pending_condition
            entry["optional"] = True
        properties[name] = entry
    if not properties:
        return None
    return {
        "properties": properties,
        "source": section["returnsShapeTables"][0].get("underHeading")
        or "returned-object table on the API page",
    }


def build_error_model(section: dict | None, returns_shape: dict | None,
                      description: str | None) -> dict | None:
    lowered = (description or "").lower()
    if returns_shape and {"success", "status", "statusText"} & set(returns_shape["properties"]):
        return {
            "style": "status_object",
            "note": "failure is reported in the returned status object, not by throwing",
        }
    if any(marker in lowered for marker in THROWS_MARKERS):
        return {"style": "throws", "catchableWith": "try/catch"}
    if any(marker in lowered for marker in RETURNS_NULL_MARKERS):
        return {"style": "returns_null"}
    return None


def accessor_for(section: dict | None, description: str | None,
                 type_name: str | None, nullable: bool) -> dict:
    lowered = (description or "").lower()
    writable = True
    if any(marker in lowered for marker in READ_ONLY_MARKERS):
        writable = False
    elif any(marker in lowered for marker in WRITABLE_MARKERS):
        writable = True
    accessor = {
        "type": type_ref(type_name) or {"kind": "pseudo", "name": "any"},
        "readable": True,
        "writable": writable,
    }
    if nullable:
        accessor["nullable"] = True
    return accessor


NUMERIC_TYPES = ("Integer", "Real", "Longint", "Number")


def sole_constant_table(section: dict | None, signature: dict) -> list[dict] | None:
    """The one constant table on a page whose owner is unambiguous.

    25 members put their accepted constants in a Constant/Value/Comment table
    that sits under the generic "Description" heading, so the heading cannot
    say which parameter it belongs to. When the member has exactly one such
    table and exactly one numerically-typed parameter, the pairing is the only
    one possible and is safe to make. Anything more ambiguous is left alone
    rather than guessed at.
    """
    if not section:
        return None
    tables = [t for t in constant_tables(section) if t["values"]]
    if len(tables) != 1:
        return None
    numeric = {
        param["name"]
        for overload in signature["overloads"]
        for param in overload["params"]
        if type_ref(param.get("type")) and
        (type_ref(param["type"]) or {}).get("name") in NUMERIC_TYPES
    }
    if len(numeric) != 1:
        return None
    return [next(iter(numeric)), tables[0]["values"]]


def build_params(overload: dict, entry_id: str, section: dict | None,
                 syntax_record: dict, registry: dict,
                 enums: dict, upgrades: list,
                 sole_table: list | None = None) -> list[dict]:
    params: list[dict] = []
    for raw in overload["params"]:
        if raw.get("literalStar"):
            params.append(
                {
                    "name": "*",
                    "type": {
                        "kind": "literal_symbols",
                        "symbols": ["*"],
                        "meanings": {
                            "*": "positional marker literal, passed as written"
                        },
                    },
                    "direction": "in",
                    "optional": raw["optional"],
                }
            )
            continue
        name = raw["name"]
        description, spans = param_description(entry_id, name, section, syntax_record)
        type_obj = type_ref(raw["type"]) or {"kind": "pseudo", "name": "any"}

        mentions = collect_constant_mentions(
            [description], spans, registry
        ) if description or spans else []
        # Constants are numeric selectors, so prose association is only
        # attempted for numerically-typed parameters. A Text or 4D.Folder
        # parameter mentioned in the same paragraph is not a constant slot.
        if type_obj.get("name") in ("Integer", "Real", "Longint", "Number"):
            for extra in prose_constants_for_param(section, name, registry):
                if extra not in mentions:
                    mentions.append(extra)

        table_values: list[dict] = []
        for table in constant_tables(section):
            title = table["title"].lower()
            if re.search(rf"(?<![\w]){re.escape(name.lower())}(?![\w])", title):
                table_values = table["values"]
                break
        # The positional fallback only applies when the parameter's own
        # description named no constants. Entity.save's only constant table
        # lists the *returned* status codes, not the values `mode` accepts,
        # and `mode`'s own description already names `dk auto merge`.
        if not mentions and not table_values and sole_table and sole_table[0] == name:
            table_values = sole_table[1]

        if mentions or table_values:
            values, themes = constant_values(mentions, registry)
            if table_values:
                # The page's own Constant table is authoritative about which
                # constants this parameter accepts, and carries per-value
                # comments the registry does not have.
                by_name = {v["name"]: v for v in values}
                merged = []
                for value in table_values:
                    if value["value"] is None and value["name"] in by_name:
                        value = dict(value, value=by_name[value["name"]]["value"])
                    merged.append(value)
                values = merged
            if values:
                enum_key = f"{entry_id}.{name}"
                enums[enum_key] = {
                    "description": (
                        f"Constants accepted by the `{name}` parameter of "
                        f"{entry_id}"
                        + (f", from the '{sorted(themes)[0]}' theme"
                           if len(themes) == 1 else "")
                        + "."
                    ),
                    "values": values,
                }
                upgrades.append(
                    {
                        "id": entry_id,
                        "param": name,
                        "wasType": type_obj.get("name"),
                        "enum": enum_key,
                        "constants": [v["name"] for v in values],
                        "themes": sorted(themes),
                        "source": (
                            "constant table on the API page" if table_values
                            else "constant names in the parameter description"
                        ),
                    }
                )
                type_obj = {"kind": "enum_ref", "enum": enum_key}

        param: dict = {
            "name": name,
            "type": type_obj,
            "direction": "in",
            "optional": raw["optional"],
        }
        if description:
            param["description"] = description
        if raw.get("variadic"):
            params.append(
                {
                    "name": name,
                    "members": [param],
                    "cardinality": {"min": 0 if raw["optional"] else 1, "max": None},
                    "position": "trailing",
                }
            )
            continue
        params.append(param)
    return params


def build_entry(manifest_entry: dict, signature: dict, section: dict | None,
                syntax_record: dict, syntax: dict, registry: dict,
                nullable_returns: set[str], enums: dict,
                upgrades: list) -> dict:
    entry_id = manifest_entry["id"]
    kind = manifest_entry["kind"]
    class_name = manifest_entry["class"]
    member_name = manifest_entry.get("memberName") or signature["overloads"][0][
        "memberName"
    ] if signature["overloads"] else manifest_entry.get("memberName")

    description, desc_spans = description_text(section)
    returns_shape = build_returns_shape(section)
    summary = syntax_record.get("Summary") or (section or {}).get("summary")

    if kind == "oop_constructor":
        receiver_class = manifest_entry.get("constructs") or class_name
        receiver = {
            "classId": receiver_class,
            "kind": "class",
            "typeRef": {"kind": "concrete", "name": f"4D.{receiver_class}"},
        }
    else:
        receiver = {
            "classId": class_name,
            "kind": "instance",
            "typeRef": {"kind": "concrete", "name": class_name},
        }
        declaring = manifest_entry.get("declaringClass")
        if declaring and declaring != class_name:
            receiver["inheritedFrom"] = declaring

    entry: dict = {
        "id": entry_id,
        "displayName": entry_id,
        "kind": kind,
        "memberName": member_name,
        "receiver": receiver,
    }
    if summary:
        entry["summary"] = summary if summary[0].isupper() else summary[0].upper() + summary[1:]
    if description:
        entry["description"] = description
    if section:
        entry["docPage"] = section.get("docPage")

    if kind == "oop_property":
        return_type = (
            signature["overloads"][0]["returnType"] if signature["overloads"] else None
        )
        entry["accessor"] = accessor_for(
            section, description, return_type, entry_id in nullable_returns
        )
        tables = [t for t in constant_tables(section) if t["values"]]
        if len(tables) == 1 and entry["accessor"]["type"].get("name") in NUMERIC_TYPES:
            enum_key = f"{entry_id}.value"
            enums[enum_key] = {
                "description": f"Values accepted by the {entry_id} property.",
                "values": tables[0]["values"],
            }
            upgrades.append(
                {
                    "id": entry_id,
                    "param": "(accessor)",
                    "wasType": entry["accessor"]["type"].get("name"),
                    "enum": enum_key,
                    "constants": [v["name"] for v in tables[0]["values"]],
                    "themes": [],
                    "source": "constant table on the API page",
                }
            )
            entry["accessor"]["type"] = {"kind": "enum_ref", "enum": enum_key}
    else:
        overloads = []
        for overload in signature["overloads"]:
            record: dict = {
                "params": build_params(
                    overload, entry_id, section, syntax_record, registry, enums,
                    upgrades, sole_constant_table(section, signature),
                ),
                "rawSyntax": overload["rawSyntax"],
            }
            record["returns"] = type_ref(overload["returnType"])
            if entry_id in nullable_returns:
                record["returnsNullable"] = True
            overloads.append(record)
        entry["overloads"] = overloads

    if returns_shape:
        # 27 members document their status codes in a Constant/Value table
        # whose sub-heading names the shape property it describes ("status and
        # statusText"). Attaching it turns an opaque `status: number` into an
        # enumerated set.
        for table in constant_tables(section):
            title = table["title"].lower()
            for prop_name in list(returns_shape["properties"]):
                if re.search(
                    rf"(?<![\w]){re.escape(prop_name.lower())}(?![\w])", title
                ):
                    enum_key = f"{entry_id}.returns.{prop_name}"
                    enums[enum_key] = {
                        "description": (
                            f"Values of the `{prop_name}` property of the object "
                            f"returned by {entry_id}."
                        ),
                        "values": table["values"],
                    }
                    returns_shape["properties"][prop_name]["type"] = {
                        "kind": "enum_ref",
                        "enum": enum_key,
                    }
                    upgrades.append(
                        {
                            "id": entry_id,
                            "param": f"(returnsShape).{prop_name}",
                            "wasType": "Real",
                            "enum": enum_key,
                            "constants": [v["name"] for v in table["values"]],
                            "themes": [],
                            "source": "constant table on the API page",
                        }
                    )
                    break
        entry["returnsShape"] = returns_shape
    error_model = build_error_model(section, returns_shape, description)
    if error_model:
        entry["errorModel"] = error_model
    if manifest_entry.get("dynamicMember"):
        dynamic = {
            "namePattern": manifest_entry.get(
                "namePattern", f"<{member_name.lstrip('.')}>"
            )
        }
        if manifest_entry.get("note"):
            dynamic["note"] = manifest_entry["note"]
        entry["dynamicMember"] = dynamic

    entry.update(history_facts((section or {}).get("history")))
    if section and section.get("seeAlso"):
        entry["_seeAlso"] = section["seeAlso"]
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--syntax-json", default="references/syntaxEN.json")
    ap.add_argument("--manifest", default="out/oop_manifest.json")
    ap.add_argument("--signatures", default="out/oop_signatures.json")
    ap.add_argument("--raw", default="out/oop_stage1_raw.json")
    ap.add_argument("--conflicts", default="out/oop_param_conflicts.json")
    ap.add_argument("--constants", default="references/4d-constants-registry.json")
    ap.add_argument("--out-dir", default="out/oop_stage3_ir_full")
    ap.add_argument("--cache-dir", default="cache/oop/merged")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    syntax = oop.load_syntax_json(repo_root / args.syntax_json)
    manifest = json.loads((repo_root / args.manifest).read_text(encoding="utf-8"))
    signatures = json.loads((repo_root / args.signatures).read_text(encoding="utf-8"))
    raw = json.loads((repo_root / args.raw).read_text(encoding="utf-8"))
    conflicts = json.loads((repo_root / args.conflicts).read_text(encoding="utf-8"))
    registry = json.loads(
        (repo_root / args.constants).read_text(encoding="utf-8")
    )["byName"]

    nullable_returns = {
        item["id"] for item in conflicts["items"]
        if item["kind"] == "return_nullable_only_in_table"
    }
    raw_index = crosscheck.build_index(raw)
    doc_page_by_class = {name: page["docPage"] for name, page in raw.items()}

    out_dir = repo_root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        stale.unlink()
    cache_dir = repo_root / args.cache_dir

    enums: dict = {}
    upgrades: list = []
    written = 0
    missing_signature = []

    for manifest_entry in manifest["entries"]:
        entry_id = manifest_entry["id"]
        signature = signatures.get(entry_id)
        if signature is None:
            if not manifest_entry.get("dynamicMember"):
                missing_signature.append(entry_id)
            signature = {"overloads": []}
        class_name = manifest_entry["class"]
        member_key = manifest_entry["memberKey"]
        section = crosscheck.section_for(
            raw_index, syntax, entry_id, class_name, member_key
        )
        if section is not None:
            for name, page in raw.items():
                if section in page["sections"]:
                    section = dict(section, docPage=page["docPage"])
                    break
        syntax_record = (
            oop.class_members(syntax, class_name).get(member_key, {})
            if class_name != oop.CLASS_STORE_KEY
            else _class_store_record(syntax, member_key)
        )
        entry = build_entry(
            manifest_entry, signature, section, syntax_record, syntax, registry,
            nullable_returns, enums, upgrades,
        )
        safe = entry_id.replace("/", "_")
        (out_dir / f"{safe}.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written += 1

    enums_path = repo_root / "out" / "oop_enums.json"
    enums_path.write_text(
        json.dumps(enums, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report = {
        "entriesWritten": written,
        "enumsGenerated": len(enums),
        "paramsUpgradedToEnumRef": len(upgrades),
        "missingSignature": missing_signature,
        "upgrades": upgrades,
    }
    (repo_root / "out" / "oop_enrichment_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"entries written:          {written}")
    print(f"params upgraded to enum_ref: {len(upgrades)}")
    print(f"enums generated:          {len(enums)}")
    if missing_signature:
        print(f"WARNING: {len(missing_signature)} members had no parsed signature")
    print(f"entries -> {out_dir}")
    return 0


def _class_store_record(syntax: dict, member_key: str) -> dict:
    parts = member_key.split(".")
    if len(parts) < 3:
        # A dynamic pseudo-member of the class store itself, which syntaxEN
        # does not describe (it has no fixed name).
        return {}
    target, member = parts[1], ".".join(parts[2:])
    return syntax.get(oop.CLASS_STORE_KEY, {}).get(target, {}).get(member, {})


if __name__ == "__main__":
    raise SystemExit(main())

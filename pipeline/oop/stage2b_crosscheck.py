#!/usr/bin/env python3
"""Stage O2b — cross-validate parsed signatures against the HTML Params tables.

Two independent sources describe every member: the `Syntax` string in
`references/syntaxEN.json` (parsed by O2) and the `Parameter` table on the API
page (captured by O1). Where they agree, the extraction is trustworthy. Where
they disagree, one of them is wrong and a human has to decide which — so
disagreements are written to `out/oop_param_conflicts.json` for review rather
than being silently resolved in favour of either source.

Conflict kinds:
    param_table_missing     documented function has no Parameter table at all
    param_missing_in_table  signature names a param the table does not list
    param_missing_in_syntax table lists a param no overload declares
    type_mismatch           both list the param, with different types
    return_type_mismatch    the table's Result row disagrees with `: Type`
    return_row_missing      signature returns a value, table has no Result row
    return_row_unexpected   table has a Result row, no overload returns
    param_case_mismatch     same parameter, different capitalization
    param_variadic_spelling Syntax says "elementN", the table says "element"
    return_nullable_only_in_table
                            the table's Result adds "undefined"/"null" to the
                            Syntax return type, i.e. the return is nullable

The last two are reported as *findings*, not defects: O3 consumes them (case is
taken from the Syntax string, nullability from the table).

Usage:
    python3 pipeline/oop/stage2b_crosscheck.py [--repo-root PATH]
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

RESULT_ROW_NAMES = {"result", "results", "return", "returned value"}

# Type spellings that the two sources use interchangeably. Recorded here rather
# than applied silently in the comparison so the equivalence set is auditable.
TYPE_ALIASES = {
    "integer": "integer",
    "longint": "integer",
    "long integer": "integer",
    "real": "real",
    "number": "real",
    "boolean": "boolean",
    "bool": "boolean",
    "text": "text",
    "string": "text",
    "object": "object",
    "collection": "collection",
    "variant": "any",
    "any": "any",
    "any type": "any",
    "pointer": "pointer",
    "picture": "picture",
    "blob": "blob",
    "date": "date",
    "time": "time",
    "null": "null",
    "undefined": "undefined",
}


NULLISH = {"undefined", "null"}

# The two sources spell four things differently in ways that are conventions,
# not disagreements. Each is normalized explicitly and named here so the
# normalization is auditable rather than hidden inside a comparison:
#
#   1. a union type is written "Text, Blob" in the table and as one overload
#      per member type in the Syntax string;
#   2. a variadic parameter is "elementN" in the Syntax string and "element"
#      in the table;
#   3. capitalization of parameter names drifts ("targetPath"/"targetpath");
#   4. the table's Result adds "undefined" to mark a nullable return.


def split_union(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in (norm_type(part) for part in text.split(",")) if t}


def strip_variadic_suffix(name: str) -> str:
    """"elementN" -> "element". Only a bare trailing capital N is stripped."""
    return name[:-1] if len(name) > 1 and name.endswith("N") else name


def norm_type(text: str | None) -> str | None:
    if not text:
        return None
    value = oop.strip_zws(text).strip()
    value = re.sub(r"\s+", " ", value)
    value = value.strip("*` ")
    if not value:
        return None
    lowered = value.lower()
    return TYPE_ALIASES.get(lowered, lowered)


def norm_name(text: str | None) -> str | None:
    if not text:
        return None
    value = oop.strip_zws(text).strip().strip("*`")
    value = re.sub(r"^\.{3}", "", value)
    return value or None


def table_params(param_table: dict | None) -> tuple[list[dict], dict | None]:
    """Split a Parameter table into ordinary params and its Result row."""
    if not param_table:
        return [], None
    params: list[dict] = []
    result_row = None
    header_name = param_table["headers"][0] if param_table["headers"] else "Parameter"
    type_header = next(
        (h for h in param_table["headers"] if h.lower() == "type"), "Type"
    )
    desc_header = next(
        (h for h in param_table["headers"] if h.lower() == "description"), "Description"
    )
    for row in param_table["rows"]:
        cells = row["cells"]
        raw_name = cells.get(header_name, "")
        name = norm_name(raw_name)
        if name is None:
            continue
        record = {
            "name": name,
            "type": norm_type(cells.get(type_header)),
            "rawType": cells.get(type_header),
            "description": cells.get(desc_header, ""),
            "codeSpans": row.get("codeSpans", []),
        }
        # 4D.SystemWorker.new spells the row "result" in lower case.
        if name.lower() in RESULT_ROW_NAMES:
            result_row = record
            continue
        params.append(record)
    return params, result_row


def build_index(raw: dict) -> dict[str, dict]:
    """Map member id -> the O1 section, using the syntaxEN join keys."""
    index: dict[str, dict] = {}
    for class_name, page in raw.items():
        for section in page["sections"]:
            key = oop.join_key(section["headingKey"])
            index.setdefault(f"{class_name}::{key}", section)
    return index


def section_for(raw_index: dict, syntax: dict, entry_id: str, class_name: str,
                member_key: str) -> dict | None:
    """Find the O1 section for a member, following the superclass chain.

    Inherited members are documented on the subclass page too, but the IR
    models them once on the declaring class, so the declaring class's own page
    is tried first and subclass pages are only a fallback.
    """
    if class_name == oop.CLASS_STORE_KEY and member_key.startswith(
        oop.CLASS_STORE_KEY + "."
    ):
        # "4D.Blob.new()" is documented on BlobClass.html, not on the class
        # store page.
        target = member_key.split(".")[1]
        for candidate in (target, *oop.PAGE_TITLE_TO_CLASS.values()):
            hit = raw_index.get(f"{candidate}::{member_key}")
            if hit is not None:
                return hit
        return None
    key = oop.join_key(member_key)
    chain = [class_name] + oop.superclass_chain(syntax, class_name)
    for candidate in chain:
        hit = raw_index.get(f"{candidate}::{key}")
        if hit is not None:
            return hit
    # Fall back to any subclass page that re-documents the member.
    for raw_key, section in raw_index.items():
        if raw_key.endswith(f"::{key}"):
            return section
    return None


def compare(entry_id: str, signature: dict, section: dict | None) -> list[dict]:
    conflicts: list[dict] = []
    is_function = bool(signature["overloads"]) and any(
        ov["hasCallPart"] for ov in signature["overloads"]
    )
    if section is None:
        return [
            {
                "id": entry_id,
                "kind": "doc_section_missing",
                "detail": "no API-page section found for this member",
            }
        ]
    params, result_row = table_params(section.get("paramTable"))

    syntax_params: dict[str, set[str]] = {}
    declared_order: list[str] = []
    for overload in signature["overloads"]:
        for param in overload["params"]:
            if param.get("literalStar"):
                continue
            name = norm_name(param["name"])
            if name is None:
                continue
            if name not in syntax_params:
                syntax_params[name] = set()
                declared_order.append(name)
            if param["type"]:
                syntax_params[name].add(norm_type(param["type"]))

    if is_function and declared_order and not section.get("paramTable"):
        conflicts.append(
            {
                "id": entry_id,
                "kind": "param_table_missing",
                "detail": (
                    "the signature declares "
                    f"{len(declared_order)} parameter(s) but the API page has "
                    "no Parameter table"
                ),
                "syntaxParams": declared_order,
            }
        )
        params = []

    table_by_name: dict[str, dict] = {}
    for param in params:
        for key in {
            param["name"],
            param["name"].lower(),
            strip_variadic_suffix(param["name"]).lower(),
        }:
            table_by_name.setdefault(key, param)

    def lookup(name: str) -> dict | None:
        for key in (name, name.lower(), strip_variadic_suffix(name).lower()):
            if key in table_by_name:
                return table_by_name[key]
        return None

    matched_table_params: set[int] = set()
    for name in declared_order:
        if lookup(name) is None:
            if section.get("paramTable"):
                conflicts.append(
                    {
                        "id": entry_id,
                        "kind": "param_missing_in_table",
                        "param": name,
                        "detail": "declared in Syntax, absent from the Parameter table",
                    }
                )
            continue
        table_entry = lookup(name)
        matched_table_params.add(id(table_entry))
        table_types = split_union(table_entry["rawType"])
        syntax_types = {t for t in syntax_params[name] if t}
        if table_types and syntax_types and not (syntax_types & table_types):
            conflicts.append(
                {
                    "id": entry_id,
                    "kind": "type_mismatch",
                    "param": name,
                    "syntaxType": sorted(syntax_types),
                    "tableType": sorted(table_types),
                }
            )
        if table_entry["name"] != name:
            variadic = (
                strip_variadic_suffix(name).lower() == table_entry["name"].lower()
                and strip_variadic_suffix(name) != name
            )
            conflicts.append(
                {
                    "id": entry_id,
                    "kind": (
                        "param_variadic_spelling" if variadic
                        else "param_case_mismatch"
                    ),
                    "param": name,
                    "tableSpelling": table_entry["name"],
                    "detail": "the Syntax spelling is used in the IR",
                }
            )

    for param in params:
        if id(param) not in matched_table_params:
            conflicts.append(
                {
                    "id": entry_id,
                    "kind": "param_missing_in_syntax",
                    "param": param["name"],
                    "tableType": param["type"],
                    "detail": "listed in the Parameter table, absent from every overload",
                }
            )

    return_types = {
        norm_type(ov["returnType"]) for ov in signature["overloads"] if ov["returnType"]
    }
    if result_row is not None and return_types:
        table_returns = split_union(result_row["rawType"])
        if table_returns & NULLISH and not (return_types & NULLISH):
            conflicts.append(
                {
                    "id": entry_id,
                    "kind": "return_nullable_only_in_table",
                    "syntaxType": sorted(return_types),
                    "tableType": sorted(table_returns),
                    "detail": "consumed by O3 as Overload.returnsNullable",
                }
            )
        if table_returns and not (table_returns - NULLISH) & return_types:
            conflicts.append(
                {
                    "id": entry_id,
                    "kind": "return_type_mismatch",
                    "syntaxType": sorted(return_types),
                    "tableType": sorted(table_returns),
                }
            )
    elif result_row is None and return_types and section.get("paramTable"):
        conflicts.append(
            {
                "id": entry_id,
                "kind": "return_row_missing",
                "syntaxType": sorted(return_types),
                "detail": "the Syntax declares a return type, the table has no Result row",
            }
        )
    elif result_row is not None and not return_types:
        conflicts.append(
            {
                "id": entry_id,
                "kind": "return_row_unexpected",
                "tableType": result_row["type"],
                "detail": "the table declares a Result, no overload declares a return type",
            }
        )
    return conflicts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--syntax-json", default="references/syntaxEN.json")
    ap.add_argument("--signatures", default="out/oop_signatures.json")
    ap.add_argument("--raw", default="out/oop_stage1_raw.json")
    ap.add_argument("--out", default="out/oop_param_conflicts.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    syntax = oop.load_syntax_json(repo_root / args.syntax_json)
    signatures = json.loads((repo_root / args.signatures).read_text(encoding="utf-8"))
    raw = json.loads((repo_root / args.raw).read_text(encoding="utf-8"))
    raw_index = build_index(raw)

    conflicts: list[dict] = []
    checked = 0
    matched_sections = 0
    for entry_id, class_name, member_key, _record in oop.iter_syntax_members(syntax):
        signature = signatures.get(entry_id)
        if signature is None:
            continue
        checked += 1
        section = section_for(raw_index, syntax, entry_id, class_name, member_key)
        if section is not None:
            matched_sections += 1
        conflicts.extend(compare(entry_id, signature, section))

    by_kind: dict[str, int] = {}
    for conflict in conflicts:
        by_kind[conflict["kind"]] = by_kind.get(conflict["kind"], 0) + 1

    report = {
        "membersChecked": checked,
        "membersWithDocSection": matched_sections,
        "conflicts": len(conflicts),
        "byKind": dict(sorted(by_kind.items())),
        "typeAliasesApplied": TYPE_ALIASES,
        "note": (
            "Conflicts are review items, not errors. Neither source is treated "
            "as authoritative; each entry names both readings so a human can "
            "decide, and any resolution lands as a semantic overlay."
        ),
        "items": conflicts,
    }
    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"members checked:        {checked}")
    print(f"with a doc section:     {matched_sections}")
    print(f"conflicts:              {len(conflicts)}")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind:24s} {count}")
    print(f"conflicts -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

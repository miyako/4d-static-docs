#!/usr/bin/env python3
"""Stage 2 — Layer-2 candidate mining (heuristic, not LLM).

Scans out/stage1_raw.json for structural/textual signals matching the
category A-S taxonomy in references/4d-syntax-scan-prompt.md, and emits
CANDIDATES for human review. Nothing here is auto-committed to a final
Layer 2 table — this is a review queue, grouped by category, with the
evidence snippet that triggered each match so a reviewer doesn't have to
re-derive why a command was flagged.

These are heuristics, not a determination: expect false positives (flag
generously) and rely on Stage 3 / human review to confirm or drop each one.

Usage:
    python3 pipeline/stage2_candidates.py [--repo-root PATH]
        [--stage1 out/stage1_raw.json] [--out out/candidates.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


CATEGORY_LABELS = {
    "A": "builder_continuation_star",
    "B": "repeatable_interlaced_pairs",
    "C": "star_operator_dual_signature",
    "D": "property_constant_value_dependency",
    "E": "optional_dialog_overload",
    "F": "special_literal_symbols",
    "G": "polymorphic_array_input",
    "H": "magic_ref_values",
    "I": "writepro_variadic_or_object_map",
    "J": "foreign_grammar_string_param",
    "J_native": "4d_native_subgrammar (contrast with J)",
    "L": "multi_command_state_machine",
    "M": "opaque_handle_lifecycle",
    "N": "callback_contract",
    "O": "pseudo_type_parameter",
    "P": "silent_coercion_default",
    "Q": "deprecated_placeholder_param",
    "R": "cross_parameter_joint_constraint",
    "S": "statically_indistinguishable_overloads",
}

PSEUDO_TYPES = {"operator", "expression", "any", "variant", "untypedarray", "array"}
FOREIGN_GRAMMAR_KEYWORDS = [
    "sql", "regex", "regular expression", "xpath", "json", "xml", "wsdl", "soap",
    "javascript", "url", "query string", "css selector",
]
NATIVE_SUBGRAMMAR_KEYWORDS = [
    "dot notation", "attribute path", "property path", "dotted", "bracket notation",
]
DIALOG_KEYWORDS = ["dialog box", "editor appears", "is displayed", "displays the", "opens the"]
CALLBACK_TYPE_HINTS = {"method"}
CALLBACK_PROSE_HINTS = ["is called when", "invoked when", "as soon as", "is triggered", "callback"]
COERCION_HINTS = ["is used by default", "text type is used", "default type is used"]
DEPRECATED_HINTS = ["deprecated"]
PLACEHOLDER_HINTS = ["must be passed", "must pass", "pass 0", "no longer used", "for compatibility"]
JOINT_HINTS = ["if either", "both fall back", "only applies when", "only if", "only when"]
SENTINEL_HINTS = [
    re.compile(r"\b0\s*=\s*\D"), re.compile(r"\b-1\s*=\s*\D"), re.compile(r"\*\s*=\s*\D"),
    re.compile(r"if (it is |)omitted"), re.compile(r"last (item|record|element)"),
]
HANDLE_KEYWORDS = ["reference", "context", "handle", " id ", "id.", "id,"]


def _split_params(sig_text: str) -> list[str]:
    """Very rough split of a signature's parameter list on top-level ';'."""
    depth = 0
    parts = []
    current = []
    for ch in sig_text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == ";" and depth <= 1:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def detect_B_repeating_group(sig_text: str) -> str | None:
    m = re.search(r"\.\.\.\s*\(([^()]*;[^()]*)\)", sig_text)
    if m:
        return f"repeating group notation: '...({m.group(1).strip()})'"
    return None


def detect_star_position(rows: list[dict]) -> tuple[str | None, str | None]:
    """Return (leading_evidence, trailing_evidence) for a literal '*' param."""
    star_rows = [i for i, r in enumerate(rows) if r.get("Parameter", "").strip() == "*"]
    if not star_rows:
        return None, None
    leading = star_rows[0] == 0
    trailing = star_rows[-1] == len(rows) - 2 or star_rows[-1] == len(rows) - 1  # allow for trailing Function result row
    lead_ev = "leading literal '*' parameter" if leading else None
    trail_ev = "trailing literal '*' parameter" if trailing and not leading else None
    return lead_ev, trail_ev


def detect_F_symbols(param_type: str) -> str | None:
    tokens = [t.strip() for t in param_type.split(",")]
    if len(tokens) >= 1 and all(t and re.fullmatch(r"[^\w\s]{1,2}", t) for t in tokens):
        return f"literal-symbol type set: '{param_type}'"
    return None


def detect_G_polymorphic_array(param_type: str) -> str | None:
    tokens = [t.strip().lower() for t in param_type.split(",")]
    array_tokens = [t for t in tokens if "array" in t]
    if len(array_tokens) >= 2 and len(set(array_tokens)) >= 2:
        return f"array parameter accepts multiple element types: '{param_type}'"
    return None


def detect_O_pseudo(param_type: str) -> str | None:
    tokens = [t.strip().lower() for t in param_type.split(",")]
    hit = [t for t in tokens if t in PSEUDO_TYPES]
    return f"pseudo-type token(s): {hit}" if hit else None


def detect_N_callback(param_type: str, description: str) -> str | None:
    if param_type.strip().lower() in CALLBACK_TYPE_HINTS:
        return "parameter typed 'Method'"
    lower = description.lower()
    if "method" in lower and any(h in lower for h in CALLBACK_PROSE_HINTS):
        return f"prose mentions method + trigger phrase: '{_snippet(description, CALLBACK_PROSE_HINTS)}'"
    return None


def _snippet(text: str, keywords: list[str], width: int = 60) -> str:
    lower = text.lower()
    for kw in keywords:
        idx = lower.find(kw)
        if idx >= 0:
            start = max(0, idx - width // 2)
            return text[start:idx + len(kw) + width // 2].strip()
    return text[:width]


def detect_keyword_hit(text: str, keywords: list[str]) -> str | None:
    lower = text.lower()
    for kw in keywords:
        if kw in lower:
            return _snippet(text, [kw])
    return None


def detect_sentinel(description: str) -> str | None:
    for pat in SENTINEL_HINTS:
        m = pat.search(description.lower())
        if m:
            start = max(0, m.start() - 20)
            return description[start:m.end() + 20].strip()
    return None


def detect_J_foreign_or_native(param_type: str, description: str):
    if param_type.strip().lower() != "text":
        return None, None
    foreign = detect_keyword_hit(description, FOREIGN_GRAMMAR_KEYWORDS)
    native = detect_keyword_hit(description, NATIVE_SUBGRAMMAR_KEYWORDS)
    return foreign, native


def analyze_command(record: dict) -> dict:
    hits: dict[str, list[dict]] = defaultdict(list)
    sig_texts = [l["text"] for l in record.get("signatureLines", [])]
    param_table = record.get("parameterTable")
    rows = param_table["rows"] if param_table else []
    sections = record.get("sections", {})
    description = sections.get("description", {}).get("text", "")
    history_text = " ".join(
        r.get("Changes", "") for r in (record.get("history") or {}).get("rows", [])
    )

    for sig in sig_texts:
        ev = detect_B_repeating_group(sig)
        if ev:
            hits["B"].append({"evidence": ev, "source": "signature"})

    lead_ev, trail_ev = detect_star_position(rows)
    if lead_ev:
        hits["C"].append({"evidence": lead_ev, "source": "parameterTable"})
    if trail_ev:
        hits["A"].append(
            {
                "evidence": trail_ev
                + (" + history/description mentions repeated calls" if any(
                    kw in (description + history_text).lower()
                    for kw in ["several times", "each call", "last call", "repeated", "successive"]
                ) else ""),
                "source": "parameterTable",
            }
        )

    for row in rows:
        pname = row.get("Parameter", "")
        ptype = row.get("Type", "")
        pdesc = row.get("Description", "")
        if not ptype:
            continue

        ev = detect_F_symbols(ptype)
        if ev and pname != "*":
            hits["F"].append({"evidence": ev, "source": f"param '{pname}'"})

        ev = detect_G_polymorphic_array(ptype)
        if ev:
            hits["G"].append({"evidence": ev, "source": f"param '{pname}'"})

        ev = detect_O_pseudo(ptype)
        if ev:
            hits["O"].append({"evidence": ev, "source": f"param '{pname}'"})

        ev = detect_N_callback(ptype, pdesc)
        if ev:
            hits["N"].append({"evidence": ev, "source": f"param '{pname}'"})

        ev = detect_sentinel(pdesc)
        if ev:
            hits["H"].append({"evidence": ev, "source": f"param '{pname}'"})

        foreign, native = detect_J_foreign_or_native(ptype, pdesc)
        if foreign:
            hits["J"].append({"evidence": foreign, "source": f"param '{pname}'"})
        if native:
            hits["J_native"].append({"evidence": native, "source": f"param '{pname}'"})

        ev = detect_keyword_hit(pdesc, JOINT_HINTS)
        if ev:
            hits["R"].append({"evidence": ev, "source": f"param '{pname}'"})

    ev = detect_keyword_hit(description, DIALOG_KEYWORDS)
    if ev and any(kw in description.lower() for kw in ["omit", "not pass", "if you do not"]):
        hits["E"].append({"evidence": ev, "source": "description"})

    ev = detect_keyword_hit(description, COERCION_HINTS)
    if ev:
        hits["P"].append({"evidence": ev, "source": "description"})

    if detect_keyword_hit(description, DEPRECATED_HINTS) and detect_keyword_hit(description, PLACEHOLDER_HINTS):
        hits["Q"].append(
            {
                "evidence": _snippet(description, DEPRECATED_HINTS) + " | " + _snippet(description, PLACEHOLDER_HINTS),
                "source": "description",
            }
        )

    # I: writepro_variadic_or_object_map — two overloads, one with a
    # "...(name;value)"-style repeating tail, another with a single Object
    # parameter as the last positional argument.
    if len(sig_texts) >= 2:
        has_variadic_pairs = any(re.search(r"\.\.\.\([^()]*;[^()]*\)", s) for s in sig_texts)
        has_object_overload = any(
            re.search(r":\s*Object\s*\)\s*$", s) or re.search(r":\s*Object\s*\{", s) for s in sig_texts
        )
        if has_variadic_pairs and has_object_overload:
            hits["I"].append({"evidence": "variadic name/value overload + single-Object overload", "source": "signature"})

    # S: statically_indistinguishable_overloads — 2+ overloads whose
    # parameter *type* sequences (ignoring names) are identical.
    if len(sig_texts) >= 2:
        type_seqs = []
        for s in sig_texts:
            params = _split_params(re.sub(r"^\S+\s*\(", "", s).rstrip(")"))
            types = tuple(re.sub(r"^\s*\S+\s*:\s*", "", p).strip() for p in params if ":" in p)
            if types:
                type_seqs.append(types)
        if len(type_seqs) >= 2 and len(set(type_seqs)) == 1 and len(type_seqs) == len(sig_texts):
            hits["S"].append(
                {"evidence": f"{len(sig_texts)} overloads share identical param-type sequence {type_seqs[0]}", "source": "signature"}
            )

    return {k: v for k, v in hits.items() if v}


def mine_duplicate_param_descriptions(records: list[dict]) -> list[dict]:
    """Enum/shared-substructure candidates: the exact same non-trivial
    parameter description text reused verbatim across 2+ different
    commands under the same parameter name is a signal that the underlying
    concept (often an enum of constants) should be authored once in Layer 2
    rather than re-derived per command.
    """
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in records:
        table = r.get("parameterTable")
        if not table:
            continue
        for row in table["rows"]:
            pname = row.get("Parameter", "").strip().lower()
            pdesc = row.get("Description", "").strip()
            if pname and len(pdesc) >= 40:
                index[(pname, pdesc)].add(r["id"])

    out = []
    for (pname, pdesc), cmds in index.items():
        if len(cmds) >= 2:
            out.append(
                {
                    "paramName": pname,
                    "descriptionText": pdesc,
                    "commands": sorted(cmds),
                    "textHash": hashlib.sha1(pdesc.encode()).hexdigest()[:12],
                }
            )
    out.sort(key=lambda e: -len(e["commands"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--stage1", default="out/stage1_raw.json")
    ap.add_argument("--out", default="out/candidates.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    stage1 = json.loads((repo_root / args.stage1).read_text(encoding="utf-8"))
    records = stage1["records"]

    by_category: dict[str, list[dict]] = defaultdict(list)
    per_command_hits: dict[str, dict] = {}
    for r in records:
        hits = analyze_command(r)
        if hits:
            per_command_hits[r["id"]] = hits
        for cat, evidences in hits.items():
            by_category[cat].append(
                {
                    "id": r["id"],
                    "displayName": r["displayName"],
                    "theme": r.get("theme"),
                    "evidence": evidences,
                }
            )

    overlap_counts: dict[str, int] = defaultdict(int)
    pair_counts: dict[str, int] = defaultdict(int)
    for cid, hits in per_command_hits.items():
        cats = sorted(hits.keys())
        if len(cats) >= 2:
            overlap_counts["2+"] += 1
        for i in range(len(cats)):
            for j in range(i + 1, len(cats)):
                pair_counts[f"{cats[i]}+{cats[j]}"] += 1

    duplicate_descriptions = mine_duplicate_param_descriptions(records)

    result = {
        "categoryLabels": CATEGORY_LABELS,
        "counts": {
            "totalCommandsScanned": len(records),
            "commandsWithAnyHit": len(per_command_hits),
            "byCategory": {cat: len(v) for cat, v in sorted(by_category.items())},
            "multiLabelOverlap": overlap_counts.get("2+", 0),
        },
        "categoryCoOccurrence": dict(sorted(pair_counts.items(), key=lambda kv: -kv[1])),
        "byCategory": dict(by_category),
        "enumCandidates": duplicate_descriptions,
    }

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"commands scanned: {len(records)}")
    print(f"commands with >=1 category hit: {len(per_command_hits)}")
    print("counts by category:")
    for cat, n in sorted(result["counts"]["byCategory"].items()):
        print(f"  {cat} ({CATEGORY_LABELS.get(cat, cat)}): {n}")
    print(f"multi-label (2+ categories): {result['counts']['multiLabelOverlap']}")
    print(f"enum/shared-substructure candidates (param desc reused across >=2 commands): {len(duplicate_descriptions)}")
    print(f"candidates written to: {out_path}")


if __name__ == "__main__":
    main()

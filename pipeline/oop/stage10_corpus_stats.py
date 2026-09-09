#!/usr/bin/env python3
"""Stage O10 -- corpus statistics for the `4d-language-oop` CLI (session C).

Session C tunes a deterministic ranking over the OOP corpus. That needs
frequency data, not a ranking algorithm, so this stage deliberately produces
only measurements:

* per-token document frequency across member ids, member names, summaries and
  parameter names, kept as four separate fields plus a combined one, so a
  consumer can weight a name match differently from a prose match;
* per-class member counts, split by member kind;
* example coverage per member -- doc example vs synthetic-only vs neither --
  which is what decides whether a hit can be shown with human-written code.

Usage:
    python3 pipeline/oop/stage10_corpus_stats.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IR_PATH = ROOT / "out" / "4d-oop-ir.json"
EXAMPLES_PATH = ROOT / "out" / "oop_doc_examples.json"
MANIFEST_PATH = ROOT / "out" / "oop_synth_manifest.json"
OUT_PATH = ROOT / "out" / "oop_corpus_stats.json"

# Split on non-alphanumerics AND on camelCase humps, because almost every OOP
# identifier is camelCase: a query for "entity selection" must be able to reach
# `EntitySelection`, and "order by" must reach `orderByFormula`.
SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
HUMP_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for part in SPLIT_RE.split(text or ""):
        if not part:
            continue
        for piece in HUMP_RE.split(part):
            if piece:
                tokens.append(piece.lower())
    return tokens


def main() -> int:
    ir = json.load(open(IR_PATH))
    members = ir["commands"]

    # --- document frequencies (a token counts once per member, not per use)
    fields = {
        "id": lambda m: [m["id"], m.get("displayName", "")],
        "name": lambda m: [m.get("memberName", ""), m["receiver"]["classId"]],
        "summary": lambda m: [m.get("description") or ""],
        "paramNames": lambda m: [
            p.get("name") or ""
            for o in m.get("overloads", [])
            for p in o.get("params", [])
        ],
    }
    df = {k: Counter() for k in fields}
    df_all = Counter()
    for m in members:
        seen_all = set()
        for field, getter in fields.items():
            seen = set()
            for text in getter(m):
                seen.update(tokenize(text))
            df[field].update(seen)
            seen_all |= seen
        df_all.update(seen_all)

    # --- per-class member counts
    per_class: dict[str, Counter] = defaultdict(Counter)
    for m in members:
        per_class[m["receiver"]["classId"]][m["kind"]] += 1
    class_counts = {}
    for class_id, kinds in sorted(per_class.items()):
        info = ir["classes"].get(class_id, {})
        class_counts[class_id] = {
            "total": sum(kinds.values()),
            **{k: kinds.get(k, 0) for k in ("oop_function", "oop_property", "oop_constructor")},
            "superclass": info.get("superclass"),
            "abstract": bool(info.get("abstract")),
        }

    # --- example coverage
    examples = json.load(open(EXAMPLES_PATH))
    manifest = json.load(open(MANIFEST_PATH))
    synth_ids = {info["member_id"] for info in manifest["files"].values()}

    doc_any: set[str] = set()
    doc_verified: set[str] = set()
    per_member_docs: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "compilerVerified": 0, "wrapped": 0, "notVerified": 0}
    )
    for block in examples["examples"]:
        member_id = block.get("memberId")
        if not member_id or block.get("language") != "4d":
            continue
        doc_any.add(member_id)
        rec = per_member_docs[member_id]
        rec["total"] += 1
        bucket = (block.get("compilerVerification") or {}).get("bucket")
        if bucket == 1:
            rec["compilerVerified"] += 1
            doc_verified.add(member_id)
        elif bucket == 2:
            rec["wrapped"] += 1
            doc_verified.add(member_id)
        else:
            rec["notVerified"] += 1

    all_ids = {m["id"] for m in members}
    coverage = {
        "members": len(all_ids),
        "withCompilerVerifiedDocExample": len(doc_verified),
        "withDocExampleNotCompilerVerified": len(doc_any - doc_verified),
        "withAnyDocExample": len(doc_any),
        "syntheticOnly": len(all_ids - doc_any),
        "neither": len(all_ids - doc_any - synth_ids),
        "withSyntheticExample": len(all_ids & synth_ids),
    }

    stats = {
        "_purpose": (
            "Frequency and coverage measurements for the 4d-language-oop CLI's "
            "deterministic ranking. This stage deliberately defines no ranking, no "
            "weights and no scoring -- only the data those decisions need."
        ),
        "corpus": {
            "members": len(members),
            "classes": len(ir["classes"]),
            "enums": len(ir["enums"]),
            "byKind": dict(Counter(m["kind"] for m in members)),
        },
        "tokenization": {
            "splitOn": "non-alphanumeric runs, then camelCase humps",
            "lowercased": True,
            "note": (
                "Counts are DOCUMENT frequencies: a token contributes at most 1 per "
                "member per field, so a token repeated in one summary does not "
                "outweigh a token that appears across many members."
            ),
            "distinctTokens": {k: len(v) for k, v in df.items()} | {"combined": len(df_all)},
        },
        "documentFrequency": {
            "combined": dict(df_all.most_common()),
            **{k: dict(v.most_common()) for k, v in df.items()},
        },
        "perClassMemberCounts": class_counts,
        "exampleCoverage": coverage,
        "perMemberDocExamples": {k: v for k, v in sorted(per_member_docs.items())},
    }
    OUT_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(stats["corpus"], indent=2))
    print(json.dumps(coverage, indent=2))
    print(json.dumps(stats["tokenization"]["distinctTokens"], indent=2))
    print(f"-> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

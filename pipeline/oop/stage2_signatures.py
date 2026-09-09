#!/usr/bin/env python3
"""Stage O2 — parse every member's `Syntax` string into typed overloads.

Runs the tokenizer/parser/renderer in `syntaxparse.py` over every overload line
in `references/syntaxEN.json` and enforces **GATE G1**: every line must
round-trip byte-exactly from its parsed AST.

The gate is deliberately strict. A line that does not round-trip means either a
parser gap or a documentation defect; both are triaged individually and
recorded in `out/oop_roundtrip_report.json`. The gate is never relaxed to make
the run pass.

Usage:
    python3 pipeline/oop/stage2_signatures.py [--repo-root PATH]
        [--syntax-json PATH] [--out out/oop_signatures.json]
        [--report out/oop_roundtrip_report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oopcommon as oop  # noqa: E402
import syntaxparse  # noqa: E402


def param_to_dict(param) -> dict:
    out = {
        "name": param.name,
        "type": param.typeName,
        "optional": param.optional,
    }
    if param.variadic:
        out["variadic"] = True
    if param.isLiteralStar:
        out["literalStar"] = True
    if not param.italicized and not param.isLiteralStar:
        out["_review"] = (
            "parameter name is not italicized in the source Syntax string "
            "(documentation formatting artifact)"
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--syntax-json", default="references/syntaxEN.json")
    ap.add_argument("--out", default="out/oop_signatures.json")
    ap.add_argument("--report", default="out/oop_roundtrip_report.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    syntax = oop.load_syntax_json(repo_root / args.syntax_json)

    signatures: dict[str, dict] = {}
    failures: list[dict] = []
    normalizations: list[dict] = []
    total_lines = 0
    ok_lines = 0

    for entry_id, class_name, member_key, record in oop.iter_syntax_members(syntax):
        raw = record.get("Syntax", "")
        lines = syntaxparse.split_overloads(raw)
        overloads = []
        for position, line in enumerate(lines):
            total_lines += 1
            try:
                parsed = syntaxparse.parse_overload(line)
                rendered = syntaxparse.render(parsed)
            except syntaxparse.SyntaxParseError as exc:
                failures.append(
                    {
                        "id": entry_id,
                        "class": class_name,
                        "member": member_key,
                        "overloadIndex": position,
                        "line": line,
                        "error": str(exc),
                        "stage": "parse",
                    }
                )
                continue
            if rendered != line:
                failures.append(
                    {
                        "id": entry_id,
                        "class": class_name,
                        "member": member_key,
                        "overloadIndex": position,
                        "line": line,
                        "rendered": rendered,
                        "error": "rendered output differs from source",
                        "stage": "roundtrip",
                    }
                )
                continue
            ok_lines += 1
            if parsed.notes:
                normalizations.append(
                    {
                        "id": entry_id,
                        "overloadIndex": position,
                        "line": line,
                        "semanticMemberName": parsed.memberName,
                        "notes": parsed.notes,
                        "roundTrip": "byte-exact — the malformed emphasis is "
                                     "preserved verbatim; only the semantic "
                                     "member name is normalized",
                    }
                )
            overloads.append(
                {
                    "rawSyntax": line,
                    "memberName": parsed.memberName,
                    "receiverPath": parsed.receiverPath,
                    "hasCallPart": parsed.hasCallPart,
                    "params": [param_to_dict(p) for p in parsed.params],
                    "returnType": parsed.returnType,
                }
            )

        signatures[entry_id] = {
            "id": entry_id,
            "class": class_name,
            "memberKey": member_key,
            "rawSyntax": raw,
            "overloads": overloads,
        }

    report = {
        "syntaxJson": args.syntax_json,
        "members": len(signatures),
        "overloadLines": total_lines,
        "roundTripped": ok_lines,
        "failures": failures,
        "documentedNormalizations": normalizations,
        "gate": "G1",
        "passed": not failures,
    }

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(signatures, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_path = repo_root / args.report
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"members parsed:   {len(signatures)}")
    print(f"overload lines:   {total_lines}")
    print(f"round-tripped:    {ok_lines}")
    print(f"failures:         {len(failures)}")
    for failure in failures[:20]:
        print(f"  [{failure['stage']}] {failure['id']}#{failure['overloadIndex']}: "
              f"{failure['error']}")
    print(f"documented normalizations: {len(normalizations)}")
    print(f"signatures -> {out_path}")
    print(f"report     -> {report_path}")
    print()
    if failures:
        print(f"GATE G1: FAILED — {len(failures)}/{total_lines} lines did not "
              "round-trip. Triage each one; do not relax the gate.")
        return 1
    print(f"GATE G1: PASSED — {ok_lines}/{total_lines} overload lines "
          "round-trip byte-exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

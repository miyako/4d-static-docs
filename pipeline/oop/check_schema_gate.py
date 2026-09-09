#!/usr/bin/env python3
"""GATE G2 — the OOP schema extension must not break the classic corpus.

Asserts that `out/4d-command-ir.json`, byte-unchanged, still validates against
the extended `references/4d-command-ir-schema.json`, and that the schema's new
conditional requirements actually bite (a positive-only check would pass even
if the `if/then` block were silently inert).

Prefers `boon` (see `skills/4dtools/SKILL.md`) and additionally uses the Python
`jsonschema` package when available, so the result does not rest on a single
implementation of Draft 2020-12.

Usage:
    python3 pipeline/oop/check_schema_gate.py [--repo-root PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Documents that must validate as-is.
MUST_VALIDATE = [
    "out/4d-command-ir.json",
    "references/4d-command-ir-examples.json",
    "references/4d-oop-ir-examples.json",
    # Present once stage O5 has run; skipped with a note if the pipeline has
    # not been executed in this clone yet.
    "out/4d-oop-ir.json",
]

OPTIONAL = {"out/4d-oop-ir.json"}

# (label, document, expected_valid) — the negative cases prove the conditional
# requirements introduced for OOP are live, not decorative.
CONDITIONAL_CASES = [
    (
        "classic_command without overloads",
        {"commands": [{"id": "X", "displayName": "X", "kind": "classic_command"}]},
        False,
    ),
    (
        "classic_command with overloads",
        {"commands": [{"id": "X", "displayName": "X", "kind": "classic_command",
                       "overloads": [{"params": []}]}]},
        True,
    ),
    (
        "oop_property without accessor",
        {"commands": [{"id": "C.length", "displayName": ".length",
                       "kind": "oop_property"}]},
        False,
    ),
    (
        "oop_property with accessor and no overloads",
        {"commands": [{"id": "C.length", "displayName": ".length",
                       "kind": "oop_property",
                       "accessor": {"type": {"kind": "concrete", "name": "Integer"},
                                    "readable": True, "writable": True}}]},
        True,
    ),
    (
        "unknown CommandEntry.kind",
        {"commands": [{"id": "X", "displayName": "X", "kind": "not_a_kind",
                       "overloads": [{"params": []}]}]},
        False,
    ),
    (
        "relationship edge pointing at a classId",
        {"commands": [],
         "relationships": [{"type": "member_of", "from": {"command": "C.length"},
                            "to": {"classId": "Collection"}}]},
        True,
    ),
    (
        "CommandRef with neither command nor classId",
        {"commands": [],
         "relationships": [{"type": "member_of", "from": {}, "to": {}}]},
        False,
    ),
]


def boon_validate(boon: Path, schema: Path, doc_path: Path) -> bool:
    result = subprocess.run(
        [str(boon), "-q", str(schema), str(doc_path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    schema_path = repo_root / "references" / "4d-command-ir-schema.json"
    boon = repo_root / "tools" / "boon"
    if not boon.exists():
        print(
            "tools/boon not found — provision it per skills/4dtools/SKILL.md",
            file=sys.stderr,
        )
        return 2

    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        py_validator = None
    else:
        py_validator = jsonschema.Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )

    failures = 0

    print("Documents that must validate against the extended schema:")
    for rel in MUST_VALIDATE:
        path = repo_root / rel
        if not path.exists():
            if rel in OPTIONAL:
                print(f"  {rel:<45} not built yet (run pipeline/oop/stage5_assemble.py)")
                continue
            print(f"  {rel:<45} MISSING")
            failures += 1
            continue
        ok = boon_validate(boon, schema_path, path)
        detail = ""
        if py_validator is not None:
            py_errors = list(py_validator.iter_errors(
                json.loads(path.read_text(encoding="utf-8"))
            ))
            ok = ok and not py_errors
            detail = " (boon + jsonschema)" if not py_errors else f" ({len(py_errors)} jsonschema errors)"
        print(f"  {rel:<45} {'VALID' if ok else 'INVALID'}{detail}")
        failures += 0 if ok else 1

    print("Conditional-requirement cases:")
    with tempfile.TemporaryDirectory() as tmp:
        for label, doc, expected in CONDITIONAL_CASES:
            doc_path = Path(tmp) / "case.json"
            doc_path.write_text(json.dumps(doc), encoding="utf-8")
            actual = boon_validate(boon, schema_path, doc_path)
            ok = actual == expected
            print(
                f"  {label:<48} expected "
                f"{'valid' if expected else 'invalid'}, got "
                f"{'valid' if actual else 'invalid'} — {'OK' if ok else 'FAIL'}"
            )
            failures += 0 if ok else 1

    print()
    if failures:
        print(f"GATE G2: FAILED ({failures} problem(s))")
        return 1
    print("GATE G2: PASSED — the classic corpus still validates, unchanged, "
          "and the new conditional requirements are live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

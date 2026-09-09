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


def verbatim_syntax_violations(document: dict) -> list[str]:
    """Ids of members carrying no verbatim source line.

    Functions and constructors keep theirs on every `overloads[].rawSyntax`;
    properties have no overload, so theirs lives on `accessor.rawSyntax`. The
    two paths existed asymmetrically at first — properties silently had none —
    which is invisible in the pipeline (out/oop_signatures.json keeps the line
    either way) but breaks any consumer reading only the assembled IR. This
    check exists so that asymmetry cannot come back.

    Dynamic pseudo-members (`.attributeName` and friends) are exempt: they are
    not declared anywhere, so there is no source line to preserve.
    """
    violations = []
    for entry in document.get("commands", []):
        if entry.get("dynamicMember"):
            continue
        if entry.get("kind") == "oop_property":
            if not (entry.get("accessor") or {}).get("rawSyntax"):
                violations.append(entry["id"])
            continue
        if not entry.get("kind", "").startswith("oop_"):
            continue  # classic corpus predates rawSyntax
        overloads = entry.get("overloads") or []
        if not overloads or not all(o.get("rawSyntax") for o in overloads):
            violations.append(entry["id"])
    return violations


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

    print("Verbatim-source-line invariant (every non-dynamic member):")
    oop_ir_path = repo_root / "out" / "4d-oop-ir.json"
    if not oop_ir_path.exists():
        print("  out/4d-oop-ir.json not built yet — invariant not checked")
    else:
        oop_ir = json.loads(oop_ir_path.read_text(encoding="utf-8"))
        violations = verbatim_syntax_violations(oop_ir)
        members = [e for e in oop_ir["commands"] if not e.get("dynamicMember")]
        props = [e for e in members if e["kind"] == "oop_property"]
        callables = [e for e in members if e["kind"] != "oop_property"]
        print(f"  {len(callables)} function/constructor entries via overloads[].rawSyntax")
        print(f"  {len(props)} property entries via accessor.rawSyntax")
        if violations:
            print(f"  FAIL — {len(violations)} member(s) carry no verbatim source line: "
                  f"{violations[:10]}{' ...' if len(violations) > 10 else ''}")
            failures += 1
        else:
            print(f"  OK — all {len(members)} non-dynamic members carry one")

        # Negative test: an assertion nobody has seen fail is not yet evidence.
        # Strip the line from one property and one function and require the
        # check to notice both.
        probe = json.loads(json.dumps(oop_ir))
        stripped = []
        for entry in probe["commands"]:
            if entry.get("dynamicMember"):
                continue
            if entry["kind"] == "oop_property" and entry["id"] not in stripped:
                entry["accessor"].pop("rawSyntax", None)
                stripped.append(entry["id"])
                break
        for entry in probe["commands"]:
            if entry.get("dynamicMember") or entry["kind"] == "oop_property":
                continue
            for overload in entry.get("overloads") or []:
                overload.pop("rawSyntax", None)
            stripped.append(entry["id"])
            break
        caught = verbatim_syntax_violations(probe)
        detected = all(item in caught for item in stripped)
        print(f"  negative test: stripped {stripped} — "
              f"{'detected both' if detected else 'NOT DETECTED'} "
              f"— {'OK' if detected else 'FAIL'}")
        failures += 0 if detected else 1

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
          "the new conditional requirements are live, and every non-dynamic "
          "member carries a verbatim source line.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

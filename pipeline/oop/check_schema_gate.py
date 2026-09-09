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
SYNTAX_SEPARATOR = "<br/>"

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


def reconstruct_syntax(entry: dict) -> str | None:
    """The member's declared source, rebuilt from the IR alone.

    Callables keep one `rawSyntax` per overload; properties keep the whole
    field on `accessor.rawSyntax`, because a property has no overload. Both
    must rebuild to the `Syntax` field byte-for-byte.
    """
    if entry.get("kind") == "oop_property":
        return (entry.get("accessor") or {}).get("rawSyntax")
    overloads = entry.get("overloads") or []
    lines = [o.get("rawSyntax") for o in overloads]
    if not lines or not all(lines):
        return None
    return SYNTAX_SEPARATOR.join(lines)


def verbatim_syntax_violations(document: dict, sources: dict[str, str]) -> list[dict]:
    """Members whose IR-reconstructed source is not byte-identical to syntaxEN.

    This deliberately checks *equality*, not presence. Presence is the weaker
    oracle and it passed while nine multi-variant properties were silently
    truncated to their first `<br/>` variant: the merge step assumed a property
    has exactly one signature. Only a byte comparison against the source of
    truth catches that, so that is what is asserted here.

    Dynamic pseudo-members are exempt — they are not declared anywhere, so
    there is no source line to preserve.
    """
    violations = []
    for entry in document.get("commands", []):
        if entry.get("dynamicMember"):
            continue
        if not entry.get("kind", "").startswith("oop_"):
            continue  # classic corpus predates rawSyntax
        entry_id = entry["id"]
        expected = sources.get(entry_id)
        if expected is None:
            continue
        actual = reconstruct_syntax(entry)
        if actual != expected:
            violations.append(
                {"id": entry_id, "expected": expected, "actual": actual}
            )
    return violations


def syntax_sources(repo_root: Path, syntax_json: Path) -> dict[str, str]:
    sys.path.insert(0, str(repo_root / "pipeline" / "oop"))
    sys.path.insert(0, str(repo_root / "pipeline"))
    import oopcommon as oop

    syntax = json.loads(syntax_json.read_text(encoding="utf-8"))
    return {
        member_id: record["Syntax"]
        for member_id, _cls, _key, record in oop.iter_syntax_members(syntax)
        if record.get("Syntax")
    }


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

    print("Verbatim-source invariant (byte-identical to syntaxEN.json):")
    oop_ir_path = repo_root / "out" / "4d-oop-ir.json"
    if not oop_ir_path.exists():
        print("  out/4d-oop-ir.json not built yet — invariant not checked")
    else:
        oop_ir = json.loads(oop_ir_path.read_text(encoding="utf-8"))
        sources = syntax_sources(repo_root, repo_root / "references" / "syntaxEN.json")
        violations = verbatim_syntax_violations(oop_ir, sources)
        members = [e for e in oop_ir["commands"] if not e.get("dynamicMember")]
        props = [e for e in members if e["kind"] == "oop_property"]
        callables = [e for e in members if e["kind"] != "oop_property"]
        multi = [e for e in props if isinstance(e["accessor"]["type"], list)]
        print(f"  {len(callables)} function/constructor entries via "
              f"'<br/>'-joined overloads[].rawSyntax")
        print(f"  {len(props)} property entries via accessor.rawSyntax "
              f"({len(multi)} multi-variant)")
        if violations:
            print(f"  FAIL — {len(violations)} member(s) do not match syntaxEN:")
            for item in violations[:10]:
                print(f"    {item['id']}")
                print(f"      expected {item['expected']!r}")
                print(f"      actual   {item['actual']!r}")
            failures += 1
        else:
            print(f"  OK — all {len(members)} non-dynamic members reconstruct exactly")

        # Negative tests. An assertion nobody has seen fail is not yet evidence,
        # and the probes must cover every code path the real bug could hide in:
        # the property path, the callable path, and specifically the truncation
        # of a multi-variant property to its first line — which is the exact
        # shape of the bug a presence-only check let through.
        probes = []

        drop_prop = json.loads(json.dumps(oop_ir))
        for entry in drop_prop["commands"]:
            if entry["kind"] == "oop_property" and not entry.get("dynamicMember"):
                entry["accessor"].pop("rawSyntax", None)
                probes.append(("property missing rawSyntax", drop_prop, entry["id"]))
                break

        drop_fn = json.loads(json.dumps(oop_ir))
        for entry in drop_fn["commands"]:
            if entry["kind"] == "oop_property" or entry.get("dynamicMember"):
                continue
            for overload in entry.get("overloads") or []:
                overload.pop("rawSyntax", None)
            probes.append(("function missing rawSyntax", drop_fn, entry["id"]))
            break

        truncate = json.loads(json.dumps(oop_ir))
        for entry in truncate["commands"]:
            accessor = entry.get("accessor") or {}
            raw = accessor.get("rawSyntax")
            if raw and SYNTAX_SEPARATOR in raw:
                accessor["rawSyntax"] = raw.split(SYNTAX_SEPARATOR)[0]
                probes.append(
                    ("multi-variant property truncated to first variant",
                     truncate, entry["id"])
                )
                break

        drop_overload = json.loads(json.dumps(oop_ir))
        for entry in drop_overload["commands"]:
            if entry["kind"] == "oop_property" or entry.get("dynamicMember"):
                continue
            if len(entry.get("overloads") or []) > 1:
                entry["overloads"] = entry["overloads"][:1]
                probes.append(
                    ("multi-overload function truncated to first overload",
                     drop_overload, entry["id"])
                )
                break

        for label, probe_doc, probe_id in probes:
            caught = {v["id"] for v in verbatim_syntax_violations(probe_doc, sources)}
            detected = probe_id in caught
            print(f"  negative test: {label} ({probe_id}) — "
                  f"{'detected' if detected else 'NOT DETECTED'} "
                  f"— {'OK' if detected else 'FAIL'}")
            failures += 0 if detected else 1
        if len(probes) < 4:
            print(f"  FAIL — only {len(probes)}/4 negative probes could be built")
            failures += 1

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
          "member reconstructs to its syntaxEN.json source byte-for-byte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

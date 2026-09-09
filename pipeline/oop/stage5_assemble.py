#!/usr/bin/env python3
"""Stage O5 — assemble, overlay, validate and diff the OOP IR.

Produces `out/4d-oop-ir.json`: a separate IR document from the classic
`out/4d-command-ir.json` (decision 1 of the plan), validating against the same
extended schema.

Semantic overlays in `pipeline/oop/semantic_overlays/<id>.json` are merged over
the machine-extracted entries here, never edited into them, so a re-run against
updated docs cannot silently discard hand-authored judgement. Every overlay
must carry a `_reason` citing its evidence; one without is a hard error.

GATE G3 is enforced here: every member on the Phase 1.2 reconciled in-scope
list must appear in the final IR or be explicitly skipped with a logged reason.

Usage:
    python3 pipeline/oop/stage5_assemble.py [--repo-root PATH] [--validate]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oopcommon as oop  # noqa: E402

# Keys stripped before validation: O3 bookkeeping that is not part of the
# schema and is carried only between stages.
INTERNAL_KEYS = ("_seeAlso",)


def deep_merge(base: dict, overlay: dict) -> dict:
    """Overlay wins on scalars and lists; dicts merge recursively."""
    out = dict(base)
    for key, value in overlay.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def strip_internal(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in INTERNAL_KEYS}


def see_also_edges(entries: list[dict], ids: set[str]) -> list[dict]:
    """"See also" links become Layer-3 edges when they resolve to a known id."""
    edges = []
    for entry in entries:
        for link in entry.get("_seeAlso", []):
            text = (link.get("text") or "").strip()
            if not text:
                continue
            member = text[:-2] if text.endswith("()") else text
            candidates = [
                f"{entry['receiver']['classId']}.{member.lstrip('.')}",
                member,
            ]
            target = next((c for c in candidates if c in ids), None)
            if target and target != entry["id"]:
                edges.append(
                    {
                        "type": "same_mechanism_family",
                        "from": {"command": entry["id"]},
                        "to": {"command": target},
                        "note": "'See also' link on the API page",
                    }
                )
    return edges


def validate(repo_root: Path, schema: Path, document: Path) -> tuple[bool, str]:
    boon = repo_root / "tools" / "boon"
    if boon.exists():
        result = subprocess.run(
            [str(boon), str(schema), str(document)],
            capture_output=True, text=True,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    try:
        import jsonschema
    except ImportError:
        return False, (
            "no validator available: tools/boon is not provisioned (see "
            "skills/4dtools/SKILL.md) and the jsonschema package is not installed"
        )
    schema_doc = json.loads(schema.read_text(encoding="utf-8"))
    instance = json.loads(document.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema_doc)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if not errors:
        return True, "valid (jsonschema)"
    return False, "\n".join(
        f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:20]
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--entries-dir", default="out/oop_stage3_ir_full")
    ap.add_argument("--classes", default="out/oop_classes.json")
    ap.add_argument("--relationships", default="out/oop_relationships.json")
    ap.add_argument("--enums", default="out/oop_enums.json")
    ap.add_argument("--manifest", default="out/oop_manifest.json")
    ap.add_argument("--overlays", default="pipeline/oop/semantic_overlays")
    ap.add_argument("--schema", default="references/4d-command-ir-schema.json")
    ap.add_argument("--classic-ir", default="out/4d-command-ir.json")
    ap.add_argument("--out", default="out/4d-oop-ir.json")
    ap.add_argument("--diff-report", default="out/oop_diff_report.json")
    ap.add_argument("--coverage", default="out/oop_coverage_report.json")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    manifest = json.loads((repo_root / args.manifest).read_text(encoding="utf-8"))
    classes = json.loads((repo_root / args.classes).read_text(encoding="utf-8"))
    relationships = json.loads(
        (repo_root / args.relationships).read_text(encoding="utf-8")
    )
    enums = json.loads((repo_root / args.enums).read_text(encoding="utf-8"))

    entries: list[dict] = []
    for path in sorted((repo_root / args.entries_dir).glob("*.json")):
        entries.append(json.loads(path.read_text(encoding="utf-8")))

    overlay_dir = repo_root / args.overlays
    applied_overlays: list[dict] = []
    orphan_overlays: list[str] = []
    if overlay_dir.is_dir():
        by_id = {entry["id"]: index for index, entry in enumerate(entries)}
        for path in sorted(overlay_dir.glob("*.json")):
            overlay = json.loads(path.read_text(encoding="utf-8"))
            overlay_id = overlay.get("id") or path.stem
            if "_reason" not in overlay:
                print(
                    f"ERROR: overlay {path.name} has no `_reason`. Every overlay "
                    "must cite the doc page or evidence it is based on."
                )
                return 1
            if overlay_id not in by_id:
                orphan_overlays.append(overlay_id)
                continue
            # An overlay that introduces an `enum_ref` must also supply the
            # enum it points at, since stage O3 could not derive one.
            for enum_id, enum_def in (overlay.pop("_enums", None) or {}).items():
                enums[enum_id] = enum_def
            index = by_id[overlay_id]
            entries[index] = deep_merge(entries[index], overlay)
            applied_overlays.append(
                {"id": overlay_id, "reason": overlay["_reason"],
                 "fields": sorted(k for k in overlay if not k.startswith("_"))}
            )

    ids = {entry["id"] for entry in entries}
    relationships = relationships + see_also_edges(entries, ids)

    document = {
        "enums": enums,
        "classes": classes,
        "commands": [strip_internal(entry) for entry in entries],
        "relationships": relationships,
    }
    out_path = repo_root / args.out
    out_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # --- id collision check against the classic corpus -------------------
    classic_path = repo_root / args.classic_ir
    collisions: list[str] = []
    if classic_path.exists():
        classic_ids = {
            entry["id"] for entry in
            json.loads(classic_path.read_text(encoding="utf-8"))["commands"]
        }
        collisions = sorted(ids & classic_ids)

    # --- GATE G3 coverage -------------------------------------------------
    expected = {record["id"] for record in manifest["entries"]}
    skipped = [
        {
            "what": record.get("id") or record.get("path")
            or record.get("syntaxKey") or record.get("class"),
            "reason": record.get("reason", ""),
            "inScope": record.get("inScope", False),
        }
        for record in manifest.get("skipped", [])
    ]
    missing = sorted(expected - ids)
    unexpected = sorted(ids - expected)
    by_kind: dict[str, int] = {}
    for entry in entries:
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1

    coverage = {
        "gate": "G3",
        "inScope": len(expected),
        "present": len(expected & ids),
        "missing": missing,
        "unexpected": unexpected,
        "skippedWithReason": skipped,
        "byKind": dict(sorted(by_kind.items())),
        "passed": not missing and not unexpected,
    }
    (repo_root / args.coverage).write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # --- diff against the previous assembled run -------------------------
    diff_path = repo_root / args.diff_report
    previous: dict = {}
    if diff_path.exists():
        try:
            previous = json.loads(diff_path.read_text(encoding="utf-8")).get(
                "fingerprints", {}
            )
        except json.JSONDecodeError:
            previous = {}
    fingerprints = {
        entry["id"]: oop.sha1_of(json.dumps(entry, sort_keys=True, ensure_ascii=False))
        for entry in document["commands"]
    }
    diff = {
        "added": sorted(set(fingerprints) - set(previous)),
        "removed": sorted(set(previous) - set(fingerprints)),
        "changed": sorted(
            key for key in set(fingerprints) & set(previous)
            if fingerprints[key] != previous[key]
        ),
        "fingerprints": fingerprints,
    }
    diff_path.write_text(
        json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"entries:        {len(entries)}")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind:18s} {count}")
    print(f"classes:        {len(classes)}")
    print(f"enums:          {len(enums)}")
    print(f"relationships:  {len(relationships)}")
    print(f"overlays:       {len(applied_overlays)} applied"
          + (f", {len(orphan_overlays)} orphaned: {orphan_overlays}"
             if orphan_overlays else ""))
    print(f"diff vs previous run: +{len(diff['added'])} "
          f"-{len(diff['removed'])} ~{len(diff['changed'])}")
    print(f"ir -> {out_path}")
    print()

    failed = False
    if collisions:
        print(f"ERROR: {len(collisions)} ids collide with the classic corpus: "
              f"{collisions[:10]}")
        failed = True
    elif classic_path.exists():
        print("id collision with the classic corpus: none")

    if coverage["passed"]:
        print(f"GATE G3: PASSED — all {len(expected)} in-scope members present "
              f"({len(skipped)} explicitly skipped with a logged reason).")
    else:
        print(f"GATE G3: FAILED — missing {len(missing)}, "
              f"unexpected {len(unexpected)}")
        failed = True

    if not args.no_validate:
        ok, detail = validate(
            repo_root, repo_root / args.schema, out_path
        )
        print(f"schema validation: {'OK' if ok else 'FAILED'}")
        if not ok:
            print(detail)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

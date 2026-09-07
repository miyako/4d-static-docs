"""Stage 3 (sample): LLM/human-assisted schema-validated semantic extraction.

Scope for this run (per explicit user decision): only the 13 regression-
fixture commands from references/4d-command-ir-examples.json, so we can
validate the Stage 3 approach cheaply before considering a full-corpus
rollout. Each target command is:

  1. looked up in Stage 1's raw extraction (out/stage1_raw.json);
  2. run through common/autoparse.py to get a mechanical draft of each
     overload's params/returns from its signature line(s) (common/stage3lib.py);
  3. deep-merged with a hand-authored semantic overlay, if one exists
     under pipeline/semantic_overlays/<id>.json;
  4. validated against references/4d-command-ir-schema.json; and
  5. diffed against the matching hand-authored fixture in examples.json.

Nothing here overwrites examples.json. Output goes to:
  out/stage3_ir_sample.json   -- assembled {"commands": [...]} document
  out/stage3_diff_report.json -- per-command validation + diff-vs-example summary

For the full-corpus rollout (all other commands), see stage3_bulk.py --
it uses the same common/stage3lib.py logic but tracks progress in a
resumable on-disk ledger instead of diffing against ground truth.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

from common.stage3lib import apply_overlay, build_draft_entry, load_json

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
OVERLAY_DIR = Path(__file__).resolve().parent / "semantic_overlays"

# Stage-1 id -> examples.json id, for the one known case-convention mismatch.
ID_ALIASES = {"Table": "TABLE"}


def normalize_id(cid: str) -> str:
    return ID_ALIASES.get(cid, cid).upper()


def diff_against_example(entry: dict, example: dict | None) -> dict:
    if example is None:
        return {"status": "no_fixture_available"}
    diffs = []
    for field in ("kind", "theme", "displayName"):
        if entry.get(field) != example.get(field):
            diffs.append(f"{field}: draft={entry.get(field)!r} example={example.get(field)!r}")
    n_draft, n_example = len(entry.get("overloads", [])), len(example.get("overloads", []))
    if n_draft != n_example:
        diffs.append(f"overload count: draft={n_draft} example={n_example}")
    for field in ("constraints", "protocolRefs", "handleRoles", "callbackContractRef", "deprecated"):
        if field in example and field not in entry:
            diffs.append(f"missing top-level '{field}' present in example")
    return {"status": "diffed", "differences": diffs, "difference_count": len(diffs)}


def main():
    stage1 = load_json(OUT_DIR / "stage1_raw.json")
    examples = load_json(ROOT / "references" / "4d-command-ir-examples.json")

    records_by_norm_id = {normalize_id(r["id"]): r for r in stage1["records"]}
    examples_by_id = {c["id"].upper(): c for c in examples["commands"]}

    schema = load_json(ROOT / "references" / "4d-command-ir-schema.json")
    validator = jsonschema.Draft202012Validator(schema)

    target_ids = list(examples_by_id.keys())  # the 13 fixtures, source of truth for scope
    assembled_commands = []
    report = []

    for norm_id in target_ids:
        example = examples_by_id[norm_id]
        record = records_by_norm_id.get(norm_id)
        if record is None:
            report.append({
                "id": norm_id,
                "status": "no_source_page",
                "overload_merges": [],
                "note": "not present in Stage 1 raw extraction (e.g. C_LONGINT has no standalone "
                        "page in this docs snapshot) -- cannot run Stage 3 for this command.",
            })
            continue

        draft_entry, review_notes, signature_texts = build_draft_entry(record)
        overlay_path = OVERLAY_DIR / f"{record['id']}.json"
        entry, merge_log = apply_overlay(copy.deepcopy(draft_entry), signature_texts, overlay_path)

        doc = {"commands": [entry]}
        errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
        valid = not errors

        assembled_commands.append(entry)
        report.append({
            "id": norm_id,
            "status": "validated" if valid else "schema_invalid",
            "overlay_applied": overlay_path.exists(),
            "overload_merges": merge_log,
            "schema_errors": [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors],
            "review_notes": review_notes,
            "diff_vs_example": diff_against_example(entry, example),
        })

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "stage3_ir_sample.json").write_text(json.dumps({"commands": assembled_commands}, indent=2))
    (OUT_DIR / "stage3_diff_report.json").write_text(json.dumps(report, indent=2))

    n_valid = sum(1 for r in report if r["status"] == "validated")
    n_invalid = sum(1 for r in report if r["status"] == "schema_invalid")
    n_missing = sum(1 for r in report if r["status"] == "no_source_page")
    n_merged = sum(1 for r in report if r["overload_merges"])
    print(f"Stage 3 sample run: {len(target_ids)} fixture commands targeted")
    print(f"  valid: {n_valid}  schema_invalid: {n_invalid}  no_source_page: {n_missing}  commands_with_overload_merges: {n_merged}")
    for r in report:
        if r["overload_merges"]:
            print(f"  [MERGED] {r['id']}:")
            for m in r["overload_merges"]:
                print(f"      indices {m['merged_source_indices']} -> overload #{m['into_overload_index']}: {m['note']}")
                for s in m["merged_source_signatures"]:
                    print(f"        - {s}")
    for r in report:
        if r["status"] == "schema_invalid":
            print(f"  [INVALID] {r['id']}: {r['schema_errors']}")


if __name__ == "__main__":
    main()

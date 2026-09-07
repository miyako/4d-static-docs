"""Stage 3 (sample): LLM/human-assisted schema-validated semantic extraction.

Scope for this run (per explicit user decision): only the 13 regression-
fixture commands from references/4d-command-ir-examples.json, so we can
validate the Stage 3 approach cheaply before considering a full-corpus
rollout. Each target command is:

  1. looked up in Stage 1's raw extraction (out/stage1_raw.json);
  2. run through common/autoparse.py to get a mechanical draft of each
     overload's params/returns from its signature line(s);
  3. deep-merged with a hand-authored semantic overlay, if one exists
     under pipeline/semantic_overlays/<id>.json (corrections/enrichment
     that syntax alone can't provide: semanticRole, discriminatedBy,
     mechanism, cardinality judgment calls, sentinelValues, etc.);
  4. validated against references/4d-command-ir-schema.json; and
  5. diffed against the matching hand-authored fixture in examples.json.

Nothing here overwrites examples.json. Output goes to:
  out/stage3_ir_sample.json   -- assembled {"commands": [...]} document
  out/stage3_diff_report.json -- per-command validation + diff-vs-example summary
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import jsonschema

from common.autoparse import draft_overload_params

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
OVERLAY_DIR = Path(__file__).resolve().parent / "semantic_overlays"

# Stage-1 id -> examples.json id, for the one known case-convention mismatch.
ID_ALIASES = {"Table": "TABLE"}


def normalize_id(cid: str) -> str:
    return ID_ALIASES.get(cid, cid).upper()


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def deep_merge(base, overlay):
    """Deep-merge `overlay` onto `base`; overlay wins on scalars/lists,
    dicts are merged key-by-key.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for k, v in overlay.items():
            merged[k] = deep_merge(base.get(k), v) if k in base else v
        return merged
    return overlay if overlay is not None else base


def first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.{10,220}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:220]).strip()


def build_draft_entry(record: dict) -> tuple[dict, list[str]]:
    """Build a mechanical draft CommandEntry from a Stage 1 raw record."""
    review_notes: list[str] = []
    description = record.get("sections", {}).get("description", {}).get("text")
    role_guess = first_sentence(description)
    if role_guess is None:
        review_notes.append("no description section found; semanticRole left unset")

    overloads = []
    for sig in record.get("signatureLines", []):
        elements, notes, returns = draft_overload_params(sig["text"])
        for n in notes:
            review_notes.append(f"signature {sig['text']!r}: {n}")
        overload = {"params": elements}
        if returns is not None:
            overload["returns"] = returns
        if role_guess:
            overload["semanticRole"] = role_guess
        overloads.append(overload)
    if len(overloads) > 1:
        review_notes.append(
            f"{len(overloads)} overloads share one auto-derived semanticRole; "
            "needs a per-overload overlay to actually discriminate them"
        )

    entry = {
        "id": record["id"],
        "displayName": record["displayName"],
        "kind": "classic_command",
        "theme": record.get("theme") or "",
        "overloads": overloads,
    }
    return entry, review_notes


def apply_overlay(entry: dict, overlay_path: Path) -> dict:
    if not overlay_path.exists():
        return entry
    overlay = load_json(overlay_path)
    return deep_merge(entry, overlay)


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
                "note": "not present in Stage 1 raw extraction (e.g. C_LONGINT has no standalone "
                        "page in this docs snapshot) -- cannot run Stage 3 for this command.",
            })
            continue

        draft_entry, review_notes = build_draft_entry(record)
        overlay_path = OVERLAY_DIR / f"{record['id']}.json"
        entry = apply_overlay(copy.deepcopy(draft_entry), overlay_path)

        doc = {"commands": [entry]}
        errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
        valid = not errors

        assembled_commands.append(entry)
        report.append({
            "id": norm_id,
            "status": "validated" if valid else "schema_invalid",
            "overlay_applied": overlay_path.exists(),
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
    print(f"Stage 3 sample run: {len(target_ids)} fixture commands targeted")
    print(f"  valid: {n_valid}  schema_invalid: {n_invalid}  no_source_page: {n_missing}")
    for r in report:
        if r["status"] == "schema_invalid":
            print(f"  [INVALID] {r['id']}: {r['schema_errors']}")


if __name__ == "__main__":
    main()

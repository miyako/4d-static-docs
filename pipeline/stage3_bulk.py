"""Stage 3 (full corpus): resumable rollout across every in-scope command
except the 13 regression fixtures (handled separately by stage3_semantic.py,
which has ground truth to diff against -- this script does not).

Architecture:
  - A JSON ledger (out/stage3_progress.json) tracks one status per command
    id: "pending" | "in_progress" | "done" | "failed", plus the last error
    for failed ids and a timestamp. Re-running any command is a no-op if
    it's already "done"; failed/pending ids are exactly what gets retried.
  - The actual semantic judgment (writing pipeline/semantic_overlays/<id>.json)
    is done out-of-band (by a human or an LLM sub-agent) -- this script
    does NOT call an LLM itself. It only:
      1. hands out batches of pending ids to work on (`next-batch`), and
      2. validates the draft+overlay assembly for a batch of ids against
         the schema and updates the ledger accordingly (`validate`).
  - No overlay file is required: a command with no overlay still gets a
    schema-valid mechanical draft (this is a legitimate "done" outcome for
    a simple, low-ambiguity command; overlays only need to exist where the
    draft is wrong or under-specified).

Usage:
  python3 stage3_bulk.py init                  # (re)build the ledger from manifest.json
  python3 stage3_bulk.py report                # print status counts
  python3 stage3_bulk.py next-batch 25         # print 25 pending ids, one per line
  python3 stage3_bulk.py validate ID [ID ...]  # validate+ledger-update specific ids
  python3 stage3_bulk.py validate --all-pending  # validate every pending/in_progress id
  python3 stage3_bulk.py validate --all-failed   # retry every currently-failed id
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from common.stage3lib import apply_overlay, build_draft_entry, load_json

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
PIPELINE_DIR = Path(__file__).resolve().parent
OVERLAY_DIR = PIPELINE_DIR / "semantic_overlays"
LEDGER_PATH = OUT_DIR / "stage3_progress.json"
IR_DIR = OUT_DIR / "stage3_ir_full"  # one JSON file per successfully-validated command

# The 13 fixtures (by Stage-1 id) are handled by stage3_semantic.py, not here.
FIXTURE_IDS = {
    "ORDER-BY-FORMULA", "ORDER-BY", "C-LONGINT", "Table", "OB-SET",
    "MULTI-SORT-ARRAY", "SET-LIST-ITEM-PROPERTIES", "SET-LIST-PROPERTIES",
    "GRAPH", "GRAPH-SETTINGS", "QUERY-BY-ATTRIBUTE", "SQL-EXECUTE",
    "WA-EXECUTE-JAVASCRIPT-FUNCTION", "WP-SET-ATTRIBUTES",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return load_json(LEDGER_PATH)
    return {}


def save_ledger(ledger: dict) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, sort_keys=True))


def cmd_init():
    manifest = load_json(OUT_DIR / "manifest.json")
    ledger = load_ledger()
    added = 0
    for e in manifest["entries"]:
        cid = e["id"]
        if cid in FIXTURE_IDS:
            continue
        if cid not in ledger:
            ledger[cid] = {"status": "pending", "error": None, "updated_at": now_iso()}
            added += 1
    save_ledger(ledger)
    print(f"Ledger initialized: {len(ledger)} tracked ids ({added} newly added).")
    cmd_report(ledger)


def cmd_report(ledger: dict | None = None):
    ledger = ledger if ledger is not None else load_ledger()
    counts: dict[str, int] = {}
    for v in ledger.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(f"Stage 3 full-corpus ledger: {len(ledger)} tracked ids")
    for status in ("pending", "in_progress", "draft_ok", "done", "failed"):
        print(f"  {status}: {counts.get(status, 0)}")


def cmd_next_batch(n: int):
    ledger = load_ledger()
    pending = [cid for cid, v in sorted(ledger.items()) if v["status"] in ("pending", "in_progress", "draft_ok")]
    for cid in pending[:n]:
        print(cid)


def validate_one(cid: str, record: dict | None, validator: jsonschema.Draft202012Validator) -> dict:
    if record is None:
        return {"status": "failed", "error": "no Stage 1 raw record found for this id (no source page?)"}

    try:
        draft_entry, review_notes, signature_texts = build_draft_entry(record)
        overlay_path = OVERLAY_DIR / f"{cid}.json"
        entry, merge_log = apply_overlay(copy.deepcopy(draft_entry), signature_texts, overlay_path)
    except Exception as exc:  # noqa: BLE001 -- want to record *any* draft/overlay failure, not crash the batch
        return {"status": "failed", "error": f"draft/overlay assembly raised {type(exc).__name__}: {exc}"}

    doc = {"commands": [entry]}
    errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
    if errors:
        msg = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:5])
        return {"status": "failed", "error": f"schema validation failed: {msg}", "entry": entry}

    # Schema-valid is necessary but NOT sufficient: the mechanical draft alone
    # (no overlay) has no real semantic content (constraints, sentinelValues,
    # discriminatedBy, protocolRefs, correct overload count/split). Only an
    # authored overlay counts as "reviewed" -- a schema-valid draft with no
    # overlay stays "draft_ok" so it's still picked up by next-batch.
    reviewed = overlay_path.exists()
    return {
        "status": "done" if reviewed else "draft_ok",
        "error": None,
        "entry": entry,
        "overlay_applied": reviewed,
        "overload_merges": merge_log,
        "review_notes": review_notes,
    }


def cmd_validate(ids: list[str]):
    ledger = load_ledger()
    stage1 = load_json(OUT_DIR / "stage1_raw.json")
    records_by_id = {r["id"]: r for r in stage1["records"]}
    schema = load_json(ROOT / "references" / "4d-command-ir-schema.json")
    validator = jsonschema.Draft202012Validator(schema)

    if ids == ["--all-pending"]:
        ids = [cid for cid, v in ledger.items() if v["status"] in ("pending", "in_progress", "draft_ok")]
    elif ids == ["--all-failed"]:
        ids = [cid for cid, v in ledger.items() if v["status"] == "failed"]

    IR_DIR.mkdir(parents=True, exist_ok=True)
    n_done = n_draft_ok = n_failed = n_unknown = 0
    for cid in ids:
        if cid not in ledger:
            print(f"[SKIP] {cid}: not a tracked id (check spelling / run 'init' first)")
            n_unknown += 1
            continue
        result = validate_one(cid, records_by_id.get(cid), validator)
        if result["status"] in ("done", "draft_ok"):
            (IR_DIR / f"{cid}.json").write_text(json.dumps(result["entry"], indent=2))
            ledger[cid] = {"status": result["status"], "error": None, "updated_at": now_iso()}
            if result["status"] == "done":
                n_done += 1
                tag = "DONE, MERGED" if result["overload_merges"] else "DONE"
            else:
                n_draft_ok += 1
                tag = "DRAFT_OK (no overlay authored yet)"
            print(f"[{tag}] {cid}")
        else:
            ledger[cid] = {"status": "failed", "error": result["error"], "updated_at": now_iso()}
            n_failed += 1
            print(f"[FAILED] {cid}: {result['error']}")

    save_ledger(ledger)
    print(f"\nBatch complete: {n_done} done (reviewed), {n_draft_ok} draft_ok (no overlay yet), "
          f"{n_failed} failed, {n_unknown} unknown-id.")
    cmd_report(ledger)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    action = sys.argv[1]
    if action == "init":
        cmd_init()
    elif action == "report":
        cmd_report()
    elif action == "next-batch":
        cmd_next_batch(int(sys.argv[2]) if len(sys.argv) > 2 else 25)
    elif action == "validate":
        cmd_validate(sys.argv[2:])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Produce a source-delta report with explicit, authored semantic decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOISE_KEYS = {"contentHash", "versionBadge", "html", "sourcePaths", "provenance"}


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in NOISE_KEYS}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.replace("\u200b", "")).strip()
    return value


def baseline(ref: str, path: str):
    return json.loads(subprocess.check_output(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT, text=True,
    ))


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "out/classic_r5_review.json")
    args = parser.parse_args()
    ref = subprocess.check_output(["git", "rev-parse", args.baseline_ref], cwd=ROOT, text=True).strip()
    old = {r["id"]: r for r in baseline(ref, "out/stage1_raw.json")["records"]}
    raw = json.loads((ROOT / "out/stage1_raw.json").read_text())
    new = {r["id"]: r for r in raw["records"]}
    added, removed = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    changed = sorted(cid for cid in old.keys() & new.keys() if normalize(old[cid]) != normalize(new[cid]))
    decisions = {}
    for group in json.loads(args.decisions.read_text())["decisions"]:
        for cid in group["ids"]:
            if cid in decisions:
                raise ValueError(f"Duplicate decision: {cid}")
            decisions[cid] = group["decision"]
    needed = set(added + removed + changed)
    if set(decisions) != needed:
        raise ValueError(f"Decision coverage mismatch: missing={sorted(needed - decisions.keys())}, extra={sorted(decisions.keys() - needed)}")
    entries = []
    for cid in sorted(needed):
        before, after = normalize(old.get(cid)), normalize(new.get(cid))
        entries.append({
            "id": cid, "change": "added" if cid in added else "removed" if cid in removed else "changed",
            "beforeContentSha256": fingerprint(before) if before is not None else None,
            "afterContentSha256": fingerprint(after) if after is not None else None,
            "changedFields": sorted(k for k in (before or {}).keys() | (after or {}).keys()
                                   if (before or {}).get(k) != (after or {}).get(k)),
            "decision": decisions[cid],
        })
    unchanged = sorted((old.keys() & new.keys()) - set(changed))
    report = {
        "baselineCommit": ref, "docsRoot": raw["docsRoot"],
        "normalization": {"ignoredKeys": sorted(NOISE_KEYS), "text": "Collapse whitespace and zero-width spaces only; retain prose, tables, history, links and properties."},
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed), "unchanged": len(unchanged)},
        "added": added, "removed": removed, "changed": changed, "unchanged": unchanged,
        "reviews": entries,
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(report["counts"])


if __name__ == "__main__":
    main()

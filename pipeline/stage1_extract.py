#!/usr/bin/env python3
"""Stage 1 — Deterministic HTML extraction (no LLM).

Reads out/manifest.json (Stage 0's output) and, for each in-scope command,
produces a raw-extraction record: signature line(s), parameter table,
history table, full section prose (description/example/see-also/etc,
verbatim), properties, with every field tagged with its HTML provenance.

Content-hash cached per command under cache/raw/<id>.<hash>.json — a command
whose source HTML hasn't changed since the last run is served from cache
instead of being re-parsed.

Usage:
    python3 pipeline/stage1_extract.py [--repo-root PATH]
        [--manifest out/manifest.json] [--out out/stage1_raw.json]
        [--cache-dir cache/raw] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.cache import read_cached, write_cached
from common.extract import extract_raw_record
from common.htmlutil import parse_article, read_html


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--manifest", default="out/manifest.json")
    ap.add_argument("--out", default="out/stage1_raw.json")
    ap.add_argument("--cache-dir", default="cache/raw")
    ap.add_argument("--force", action="store_true", help="Ignore cache, reprocess everything")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    manifest = json.loads((repo_root / args.manifest).read_text(encoding="utf-8"))
    docs_root = repo_root / manifest["docsRoot"]
    cache_dir = repo_root / args.cache_dir

    hits = 0
    misses = 0
    failures = []
    records = []

    for entry in manifest["entries"]:
        cid = entry["id"]
        chash = entry["contentHash"]
        cached = None if args.force else read_cached(cache_dir, cid, chash)
        if cached is not None:
            hits += 1
            records.append(cached)
            continue

        misses += 1
        try:
            source_paths = [docs_root / p for p in entry["sourcePaths"]]
            html = read_html(source_paths[0])
            article = parse_article(html)
            if article is None:
                raise ValueError("no <article> element")
            record = extract_raw_record(article, entry, source_paths)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, logged not raised
            failures.append({"id": cid, "error": str(exc)})
            continue

        write_cached(cache_dir, cid, chash, record)
        records.append(record)

    records.sort(key=lambda r: r["id"])
    warn_count = sum(len(r.get("parseWarnings", [])) for r in records)

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "docsRoot": manifest["docsRoot"],
                "counts": {
                    "processed": len(records),
                    "cacheHits": hits,
                    "cacheMisses": misses,
                    "failures": len(failures),
                    "parseWarnings": warn_count,
                },
                "failures": failures,
                "records": records,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"processed: {len(records)} (cache hits: {hits}, misses: {misses})")
    print(f"failures: {len(failures)}")
    print(f"parse warnings (malformed tables etc.): {warn_count}")
    print(f"stage1 output written to: {out_path}")


if __name__ == "__main__":
    main()

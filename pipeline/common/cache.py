"""Content-hash based cache helpers, shared by Stage 1 and Stage 3.

Cache layout: cache/<kind>/<command-id>.<sha1(source bytes)>.json
The hash is over the concatenation of every contributing source file's raw
bytes (usually just one file, but some commands' true source could span more
than one page in principle) so a hit/miss decision never needs to re-parse
anything.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def hash_sources(paths: Iterable[Path]) -> str:
    h = hashlib.sha1()
    for p in sorted(paths, key=str):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def safe_id_for_filename(command_id: str) -> str:
    return command_id.replace("/", "_")


def cache_path(cache_dir: Path, command_id: str, content_hash: str) -> Path:
    return cache_dir / f"{safe_id_for_filename(command_id)}.{content_hash}.json"


def read_cached(cache_dir: Path, command_id: str, content_hash: str):
    p = cache_path(cache_dir, command_id, content_hash)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def write_cached(cache_dir: Path, command_id: str, content_hash: str, record: dict) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_path(cache_dir, command_id, content_hash)
    p.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    # Prune stale hash variants for this command id so the cache dir doesn't
    # accumulate every historical version forever.
    for stale in cache_dir.glob(f"{safe_id_for_filename(command_id)}.*.json"):
        if stale != p:
            stale.unlink()
    return p

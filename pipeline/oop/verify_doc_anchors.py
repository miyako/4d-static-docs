#!/usr/bin/env python3
"""Verify every member's `docPage` anchor against the live documentation.

This cannot be checked offline: the local mirror's HTML carries no `id`
attributes at all, so a mirror-based check reports a clean 0% and looks like
a definitive negative while actually measuring nothing. It has to hit the
live site.

Two properties are checked, because the weaker one is not sufficient:

1. the anchor exists on the page; and
2. the heading it points at *names that member*.

(1) alone would accept an anchor that happens to share a name with an
unrelated section, silently sending a reader to the wrong place.

A fetch-failure control is included: a page that fails to load yields no
anchors and would otherwise be indistinguishable from "the anchor is
missing", which is how an earlier version of this check produced a
confident, entirely wrong 0%.

Usage:
    python3 pipeline/oop/verify_doc_anchors.py [--ir out/4d-oop-ir.json]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HEADING = re.compile(
    r"<h[2-4][^>]*\bid=[\"']?([A-Za-z0-9_.\-]+)[\"']?[^>]*>(.*?)</h[2-4]>", re.S | re.I
)
TAG = re.compile(r"<[^>]+>")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def fetch(url: str):
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return url, None, str(exc)
    return url, {i: TAG.sub("", t).strip() for i, t in HEADING.findall(body)}, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ir", default="out/4d-oop-ir.json")
    args = ap.parse_args()

    members = [c for c in json.loads((ROOT / args.ir).read_text())["commands"] if c.get("docPage")]
    pages = sorted({m["docPage"].split("#", 1)[0] for m in members})

    with cf.ThreadPoolExecutor(10) as pool:
        results = list(pool.map(fetch, pages))
    headings = {url: h for url, h, _ in results}
    failures = [(url, err) for url, h, err in results if h is None or not h]
    if failures:
        print(f"FETCH FAILURES: {len(failures)} page(s) could not be read", file=sys.stderr)
        for url, err in failures[:5]:
            print(f"  {url}: {err}", file=sys.stderr)
        print("Refusing to report anchor results from an incomplete fetch.", file=sys.stderr)
        return 2

    bad = []
    for member in members:
        page, _, anchor = member["docPage"].partition("#")
        if not anchor:
            bad.append((member["id"], "no anchor emitted", ""))
            continue
        heading = headings[page].get(anchor)
        if heading is None:
            bad.append((member["id"], f"anchor #{anchor} not on page", page))
        elif norm(member["displayName"].rsplit(".", 1)[-1]) not in norm(heading):
            bad.append((member["id"], f"#{anchor} heading does not name it", heading))

    print(f"pages fetched:  {len(pages)} (0 fetch failures)")
    print(f"members:        {len(members)}")
    print(f"anchors valid:  {len(members) - len(bad)}")
    if bad:
        print(f"PROBLEMS: {len(bad)}")
        for item in bad[:20]:
            print("  ", item)
        return 1
    print("All member anchors resolve to a heading naming that member.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

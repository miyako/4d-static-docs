#!/usr/bin/env python3
"""Stage 0 — Corpus enumeration.

Crawls the resolved docs-version root's command directories, decides which
HTML pages are real (in-scope, classic-procedural) command pages vs.
index/listing/OOP-class pages, and writes a manifest describing every
in-scope command: id, displayName, theme, source file path(s), and a content
hash for Stage 1/3 caching.

Usage:
    python3 pipeline/stage0_manifest.py [--docs-root PATH] [--version 21-R3]
        [--repo-root PATH] [--out out/manifest.json]
        [--exclude-dir ViewPro/commands ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.docsroot import COMMAND_DIRS, KNOWN_NON_COMMAND_FILES, command_dirs, resolve_docs_root
from common.htmlutil import (
    breadcrumb_theme,
    command_title,
    is_command_page,
    parse_article,
    read_html,
    signature_name_mismatch,
    slugify_id,
    version_badge,
)
from common.cache import hash_sources

# Folder-derived theme fallback for command directories that aren't grouped
# via commands/theme/*.html breadcrumbs (View Pro is indexed alphabetically
# instead of by theme).
FOLDER_THEME_FALLBACK = {
    "WritePro/commands": "Write Pro",
    "ViewPro/commands": "View Pro",
}


def classify_kind(display_name: str) -> str:
    # Compiler directives are the C_xxx family (C_LONGINT, C_TEXT, ...).
    if display_name.startswith("C_"):
        return "compiler_directive"
    return "classic_command"


def build_manifest(docs_root: Path, exclude_dirs: set[str]) -> dict:
    entries = []
    skipped = []
    seen_ids: dict[str, str] = {}

    for rel_dir, abs_dir in command_dirs(docs_root):
        if rel_dir in exclude_dirs:
            skipped.append({"path": rel_dir, "reason": "excluded command dir (config)"})
            continue
        for html_path in sorted(abs_dir.glob("*.html")):
            rel_path = str(html_path.relative_to(docs_root))
            if html_path.name in KNOWN_NON_COMMAND_FILES:
                skipped.append({"path": rel_path, "reason": "known non-command index file"})
                continue

            html = read_html(html_path)
            article = parse_article(html)
            if article is None:
                skipped.append({"path": rel_path, "reason": "no <article> element"})
                continue

            title_probe = command_title(article)
            if title_probe.lower().endswith("database method"):
                skipped.append(
                    {
                        "path": rel_path,
                        "reason": "database-method callback hook, not a classic command (out of scope)",
                    }
                )
                continue

            if not is_command_page(article):
                skipped.append({"path": rel_path, "reason": "does not look like a command page"})
                continue

            display_name = title_probe
            command_id = slugify_id(display_name)
            theme = breadcrumb_theme(article) or FOLDER_THEME_FALLBACK.get(rel_dir)
            badge = version_badge(article)
            mismatch = signature_name_mismatch(article)

            if command_id in seen_ids and mismatch:
                # h1 collided with another command's id; the syntax line's
                # own bolded name is the rendered source of truth per the
                # extraction brief, so re-derive the id from it instead of
                # dropping this page.
                alt_id = slugify_id(mismatch)
                if alt_id not in seen_ids:
                    display_name = mismatch
                    command_id = alt_id

            if command_id in seen_ids:
                skipped.append(
                    {
                        "path": rel_path,
                        "reason": f"duplicate id '{command_id}', first seen at {seen_ids[command_id]}",
                    }
                )
                continue
            seen_ids[command_id] = rel_path

            source_paths = [html_path]
            entry = {
                "id": command_id,
                "displayName": display_name,
                "kind": classify_kind(display_name),
                "theme": theme,
                "sourcePaths": [rel_path],
                "sourceDir": rel_dir,
                "versionBadge": badge,
                "contentHash": hash_sources(source_paths),
            }
            if mismatch:
                entry["_review"] = {
                    "reason": "h1 title differs from syntax-line command name",
                    "signatureName": mismatch,
                }
            entries.append(entry)

    entries.sort(key=lambda e: e["id"])
    return {"entries": entries, "skipped": skipped}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".", help="Repository root (default: cwd)")
    ap.add_argument("--docs-root", default=None, help="Explicit docs-version root path, overrides --version")
    ap.add_argument("--version", default=None, help="Version folder name under mirror/docs, e.g. 21-R3")
    ap.add_argument("--out", default="out/manifest.json")
    ap.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help=f"Command dir (relative to docs root, one of {COMMAND_DIRS}) to exclude, may repeat",
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if args.docs_root:
        docs_root = Path(args.docs_root).resolve()
    else:
        mirror_docs_dir = repo_root / "mirror" / "docs"
        docs_root = resolve_docs_root(mirror_docs_dir, args.version)

    manifest = build_manifest(docs_root, set(args.exclude_dir))
    manifest["docsRoot"] = str(docs_root.relative_to(repo_root)) if str(docs_root).startswith(str(repo_root)) else str(docs_root)
    manifest["excludedDirs"] = sorted(args.exclude_dir)
    manifest["counts"] = {
        "inScope": len(manifest["entries"]),
        "skipped": len(manifest["skipped"]),
        "needsReview": sum(1 for e in manifest["entries"] if "_review" in e),
    }

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"docs root: {docs_root}")
    print(f"in-scope commands: {manifest['counts']['inScope']}")
    print(f"skipped pages: {manifest['counts']['skipped']}")
    print(f"manifest written to: {out_path}")


if __name__ == "__main__":
    main()

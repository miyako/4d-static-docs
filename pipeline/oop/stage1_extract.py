#!/usr/bin/env python3
"""Stage O1 — extract the raw per-member record from the API HTML pages.

Segments each `mirror/docs/<version>/API/*.html` page into member sections and
captures, verbatim and without interpretation:

* the History table (feeds sinceVersion / deprecated / versionBehaviorChanges)
* the Parameter table (feeds the O2b cross-check against the parsed signature)
* the Description prose, paragraph by paragraph, with the `<code>` spans kept
  separately so constant mentions can be resolved in O3
* the returned-object shape tables (`Result` / `Returned object` / "contains the
  following properties"), feeding `returnsShape`
* the Example blocks, raw. Session B owns example processing; O1 only preserves
  them so B does not have to re-parse the HTML.
* See also links, feeding Layer-3 edges

Nothing here is normalized or merged — that is O3's job. Records are cached
under `cache/oop/raw/<id>.<sha1>.json`, keyed on the bytes of every
contributing source file, exactly as the classic pipeline's Stage 1 does.

Usage:
    python3 pipeline/oop/stage1_extract.py [--repo-root PATH] [--version 21-R3]
        [--no-cache] [--out out/oop_stage1_raw.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oopcommon as oop  # noqa: E402
from common.cache import hash_sources, read_cached, write_cached  # noqa: E402
from common.docsroot import resolve_docs_root  # noqa: E402
from common.htmlutil import norm_text, parse_table_defensive  # noqa: E402

# Headings that introduce a returned-object shape rather than ordinary prose.
SHAPE_HEADINGS = {"Result", "Returned object", "Returned value"}


def _markdown_div(article):
    div = article.find("div", class_=lambda c: c and "markdown" in c)
    return div if div is not None else article


def _code_spans(tag) -> list[str]:
    return [norm_text(c.get_text()) for c in tag.find_all("code")]


def _table_record(table, where: str) -> dict:
    parsed = parse_table_defensive(table, where)
    rows = []
    body_rows = [
        tr for tr in (table.find("tbody") or table).find_all("tr")
        if tr.find_parent("thead") is None
    ]
    for index, row in enumerate(parsed.rows):
        record = {"cells": row}
        if index < len(body_rows):
            codes = _code_spans(body_rows[index])
            if codes:
                record["codeSpans"] = codes
        rows.append(record)
    return {
        "headers": parsed.headers,
        "rows": rows,
        "warnings": [
            {"where": w.where, "reason": w.reason} for w in parsed.warnings
        ],
    }


def _split_member_sections(article, class_name: str) -> list[dict]:
    """Split a page into member sections keyed by their heading.

    Member headings are <h2> on 43 pages and <h3> on WebForm/WebFormItem, so
    the split level is decided per page from the headings actually present
    rather than hard-coded.
    """
    md = _markdown_div(article)
    children = list(md.find_all(recursive=False))
    levels = {
        tag.name
        for tag in children
        if tag.name in ("h2", "h3") and oop.is_member_heading(norm_text(tag.get_text()))
    }
    if not levels:
        return []
    split_level = "h2" if "h2" in levels else "h3"

    sections: list[dict] = []
    current = None
    for tag in children:
        if tag.name == split_level:
            raw = norm_text(tag.get_text())
            if oop.is_member_heading(raw):
                current = {
                    "headingRaw": raw,
                    "headingKey": oop.normalize_member_heading(raw),
                    "headingLevel": split_level,
                    "nodes": [],
                }
                sections.append(current)
            else:
                current = None
            continue
        if current is not None:
            current["nodes"].append(tag)
    return sections


def _extract_section(section: dict, where: str) -> dict:
    record = {
        "headingRaw": section["headingRaw"],
        "headingKey": section["headingKey"],
        "headingLevel": section["headingLevel"],
        "history": None,
        "syntaxLines": [],
        "paramTable": None,
        "summary": None,
        "descriptionBlocks": [],
        "returnsShapeTables": [],
        "examples": [],
        "seeAlso": [],
        "subsections": [],
    }
    current_heading = None  # the h3/h4/h5 sub-heading we are inside
    for node in section["nodes"]:
        name = node.name
        classes = node.get("class") or []

        if name == "details":
            table = node.find("table")
            if table is not None and record["history"] is None:
                record["history"] = _table_record(table, f"{where}#history")
            continue

        if name in ("h3", "h4", "h5"):
            current_heading = oop.strip_zws(norm_text(node.get_text())).strip()
            record["subsections"].append(
                {"level": name, "title": current_heading}
            )
            if current_heading.startswith("Example"):
                record["examples"].append(
                    {"title": current_heading, "blocks": []}
                )
            continue

        if name == "div" and "no-index" in classes:
            table = node.find("table")
            if table is not None and record["paramTable"] is None:
                record["paramTable"] = _table_record(table, f"{where}#params")
            continue

        if name == "div" and any(
            isinstance(c, str) and c.startswith("language-") for c in classes
        ):
            code = node.find("code")
            text = code.get_text() if code is not None else node.get_text()
            language = next(
                (c[len("language-"):] for c in classes if c.startswith("language-")),
                None,
            )
            block = {"language": language, "code": text}
            if record["examples"] and current_heading and current_heading.startswith(
                "Example"
            ):
                record["examples"][-1]["blocks"].append(block)
            else:
                record["examples"].append(
                    {"title": current_heading or "(unlabelled)", "blocks": [block]}
                )
            continue

        if name == "table":
            table_record = _table_record(table=node, where=f"{where}#table")
            # A few pages (TCPConnection, TCPListener, UDPSocket, IMAPNotifier,
            # 4D.File.new, 4D.Folder.new) emit the Parameter table as a bare
            # <table> instead of wrapping it in <div class="no-index">.
            if (
                record["paramTable"] is None
                and current_heading is None
                and table_record["headers"][:1] == ["Parameter"]
            ):
                record["paramTable"] = table_record
                continue
            if current_heading in SHAPE_HEADINGS or _is_shape_table(record):
                record["returnsShapeTables"].append(
                    {"underHeading": current_heading, "table": table_record}
                )
            else:
                record["subsections"].append(
                    {"level": "table", "title": current_heading, "table": table_record}
                )
            continue

        if name in ("p", "ul", "ol", "blockquote"):
            text = oop.strip_zws(norm_text(node.get_text()))
            if not text:
                continue
            block = {
                "tag": name,
                "text": text,
                "underHeading": current_heading,
                "codeSpans": _code_spans(node),
            }
            if current_heading is None and not record["syntaxLines"] and _looks_like_syntax(
                node, section["headingKey"]
            ):
                record["syntaxLines"].append(text)
                continue
            if current_heading is not None and current_heading.startswith("See also"):
                for link in node.find_all("a"):
                    record["seeAlso"].append(
                        {
                            "text": oop.strip_zws(norm_text(link.get_text())),
                            "href": link.get("href"),
                        }
                    )
                continue
            record["descriptionBlocks"].append(block)
            if record["summary"] is None and current_heading in (None, "Description"):
                record["summary"] = text
            continue

    _promote_shape_tables(record)
    return record


def _looks_like_syntax(node, heading_key: str) -> bool:
    text = oop.strip_zws(norm_text(node.get_text()))
    bare = heading_key[:-2] if heading_key.endswith("()") else heading_key
    # Some pages drop the leading dot in the syntax paragraph even though the
    # heading carries it (e.g. HTTPRequest ".agent" -> "agent : 4D.HTTPAgent").
    return text.startswith(bare) or (
        bare.startswith(".") and text.startswith(bare[1:])
    )


def _is_shape_table(record: dict) -> bool:
    return False


_SHAPE_PROSE = (
    "contains the following properties",
    "following properties:",
)


def _promote_shape_tables(record: dict) -> None:
    """A table right after "…contains the following properties:" describes the
    returned object even when it sits under a plain Description heading.
    """
    flagged = any(
        any(marker in block["text"] for marker in _SHAPE_PROSE)
        for block in record["descriptionBlocks"]
    )
    if not flagged:
        return
    kept = []
    for sub in record["subsections"]:
        if sub.get("level") == "table" and sub.get("table"):
            headers = [h.lower() for h in sub["table"]["headers"]]
            if "property" in headers:
                record["returnsShapeTables"].append(
                    {"underHeading": sub.get("title"), "table": sub["table"]}
                )
                continue
        kept.append(sub)
    record["subsections"] = kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--version", default=None)
    ap.add_argument("--docs-root", default=None)
    ap.add_argument("--out", default="out/oop_stage1_raw.json")
    ap.add_argument("--cache-dir", default="cache/oop/raw")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    docs_root = (
        Path(args.docs_root).resolve()
        if args.docs_root
        else resolve_docs_root(repo_root / "mirror" / "docs", args.version)
    )
    cache_dir = repo_root / args.cache_dir

    pages: dict[str, dict] = {}
    sections_by_class: dict[str, dict] = {}
    hits = misses = 0

    for page in oop.api_pages(docs_root):
        article = oop.load_api_page(page)
        class_name = oop.page_class_name(article)
        content_hash = hash_sources([page])
        cached = None if args.no_cache else read_cached(
            cache_dir, f"page.{class_name}", content_hash
        )
        if cached is not None:
            hits += 1
            record = cached
        else:
            misses += 1
            sections = _split_member_sections(article, class_name)
            record = {
                "class": class_name,
                "docPage": str(page.relative_to(repo_root)),
                "contentHash": content_hash,
                "sections": [
                    _extract_section(section, f"{class_name}:{section['headingKey']}")
                    for section in sections
                ],
                "nonMemberHeadings": oop.non_member_headings(article),
            }
            write_cached(cache_dir, f"page.{class_name}", content_hash, record)
        pages[class_name] = record
        sections_by_class[class_name] = {
            section["headingKey"]: section for section in record["sections"]
        }

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(pages, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    total_sections = sum(len(p["sections"]) for p in pages.values())
    with_history = sum(
        1 for p in pages.values() for s in p["sections"] if s["history"]
    )
    with_params = sum(
        1 for p in pages.values() for s in p["sections"] if s["paramTable"]
    )
    with_shape = sum(
        1 for p in pages.values() for s in p["sections"] if s["returnsShapeTables"]
    )
    with_examples = sum(
        1 for p in pages.values() for s in p["sections"] if s["examples"]
    )
    print(f"pages:            {len(pages)} (cache hits {hits}, misses {misses})")
    print(f"member sections:  {total_sections}")
    print(f"  with History:   {with_history}")
    print(f"  with Params:    {with_params}")
    print(f"  with shape tbl: {with_shape}")
    print(f"  with Examples:  {with_examples}")
    print(f"raw -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

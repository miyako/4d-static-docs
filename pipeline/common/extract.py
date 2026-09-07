"""Shared per-command HTML → raw-extraction-record logic (Stage 1 core).

Kept separate from stage1_extract.py's CLI so Stage 4.5 (LSP probes) and
ad-hoc debugging can import `extract_raw_record` directly.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from bs4 import NavigableString, Tag

from .htmlutil import norm_text, parse_table_defensive, read_html

_LEADING_MARKER_RE = re.compile(r"[^\w\s]{1,3}")


def _markdown_div(article: Tag) -> Tag:
    return article.find("div", class_=lambda c: c and "markdown" in c) or article


def _split_signature_lines(p: Tag) -> list[dict]:
    """Split a signature paragraph on <br/> into individual overload lines,
    keeping both the rendered text and the raw HTML of each line.
    """
    lines: list[list] = [[]]
    for node in p.contents:
        if getattr(node, "name", None) == "br":
            lines.append([])
        else:
            lines[-1].append(node)
    out = []
    for parts in lines:
        if not parts:
            continue
        text = norm_text("".join(str(x) if isinstance(x, NavigableString) else x.get_text() for x in parts))
        html = "".join(str(x) for x in parts)
        if text:
            out.append({"text": text, "html": html})
    return out


def _collect_signature_paragraphs(article: Tag) -> tuple[list[dict], Optional[Tag]]:
    """Return (signature_lines, first_param_table_container).

    Scans direct children of the markdown div, from just after <header>
    up to the first `<div class="no-index">` (which wraps the parameter
    table), collecting every <p> that looks like a syntax line (tolerating
    a short leading literal marker such as "*" before the bolded name).
    """
    md = _markdown_div(article)
    header = md.find("header")
    signature_lines: list[dict] = []
    first_table_div = None
    seen_header = header is None
    for child in md.find_all(recursive=False):
        if child is header:
            seen_header = True
            continue
        if not seen_header:
            continue
        if getattr(child, "name", None) == "div" and "no-index" in (child.get("class") or []):
            first_table_div = child
            break
        if getattr(child, "name", None) == "p":
            contents = [c for c in child.contents if getattr(c, "name", None) or str(c).strip()]
            idx = 0
            if contents and getattr(contents[idx], "name", None) is None and _LEADING_MARKER_RE.fullmatch(
                str(contents[idx]).strip() or "\0"
            ):
                idx += 1
            if idx < len(contents) and getattr(contents[idx], "name", None) == "strong":
                signature_lines.extend(_split_signature_lines(child))
        if getattr(child, "name", None) == "h2":
            break
    return signature_lines, first_table_div


def _extract_parameter_table(no_index_div: Optional[Tag], where: str):
    if no_index_div is None:
        return None
    table = no_index_div.find("table")
    if table is None:
        return None
    return parse_table_defensive(table, where)


def _extract_history(article: Tag, where: str):
    details = article.find("details")
    if details is None:
        return None
    summary = details.find("summary")
    if summary is None or "history" not in norm_text(summary.get_text()).lower():
        return None
    table = details.find("table")
    if table is None:
        return None
    parsed = parse_table_defensive(table, where)
    return parsed


def _section_id(h2: Tag) -> str:
    return h2.get("id") or re.sub(r"\W+", "-", norm_text(h2.get_text()).lower()).strip("-")


def _collect_sections(article: Tag) -> dict:
    """Every `<h2>`-headed section (description, example*, see-also,
    properties, historical-note, warning, etc.) keyed by its slug id, each
    holding both raw HTML and rendered text of everything up to the next h2.
    """
    md = _markdown_div(article)
    sections: dict[str, dict] = {}
    h2s = md.find_all("h2", recursive=False)
    for h2 in h2s:
        key = _section_id(h2)
        heading_text = norm_text(h2.get_text())
        content_nodes = []
        for sib in h2.find_next_siblings():
            if sib.name == "h2":
                break
            content_nodes.append(sib)
        html = "".join(str(n) for n in content_nodes)
        text = norm_text(" ".join(n.get_text(" ") for n in content_nodes))
        entry = sections.setdefault(key, {"heading": heading_text, "html": "", "text": ""})
        entry["html"] += html
        entry["text"] = (entry["text"] + " " + text).strip()
    return sections


def _extract_see_also(sections: dict) -> list[dict]:
    sa = sections.get("see-also")
    if not sa:
        return []
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(sa["html"], "lxml")
    return [
        {"text": norm_text(a.get_text()), "href": a.get("href")}
        for a in soup.find_all("a")
        if a.get_text(strip=True)
    ]


def _extract_properties(sections: dict) -> dict:
    props = sections.get("properties")
    if not props:
        return {}
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(props["html"], "lxml")
    table = soup.find("table")
    if table is None:
        return {}
    out = {}
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) >= 2:
            key = norm_text(cells[0].get_text())
            val = norm_text(cells[1].get_text())
            if key:
                out[key] = val
    return out


def extract_raw_record(article: Tag, manifest_entry: dict, source_paths: list[Path]) -> dict:
    """Produce Stage 1's raw-extraction record for one command.

    Every field is tagged with the HTML element/section it was mechanically
    pulled from (`provenance`), per the brief's requirement that nothing in
    this layer is inferred/interpreted — only Stage 3 does that, on top of
    this record.
    """
    warnings = []

    signature_lines, param_table_div = _collect_signature_paragraphs(article)
    param_table = _extract_parameter_table(param_table_div, where=f"{manifest_entry['id']}#parameters")
    if param_table:
        warnings.extend(
            {"where": w.where, "reason": w.reason, "raw_html": w.raw_html} for w in param_table.warnings
        )

    history = _extract_history(article, where=f"{manifest_entry['id']}#history")
    if history:
        warnings.extend({"where": w.where, "reason": w.reason, "raw_html": w.raw_html} for w in history.warnings)

    sections = _collect_sections(article)
    see_also = _extract_see_also(sections)
    properties = _extract_properties(sections)

    if not signature_lines:
        warnings.append(
            {
                "where": f"{manifest_entry['id']}#signature",
                "reason": "no syntax-line paragraph found before first h2/parameter table",
                "raw_html": "",
            }
        )

    record = {
        "id": manifest_entry["id"],
        "displayName": manifest_entry["displayName"],
        "kind": manifest_entry["kind"],
        "theme": manifest_entry.get("theme"),
        "sourcePaths": manifest_entry["sourcePaths"],
        "contentHash": manifest_entry["contentHash"],
        "versionBadge": manifest_entry.get("versionBadge"),
        "signatureLines": [
            {**line, "provenance": f"{manifest_entry['id']}#signature-paragraph"} for line in signature_lines
        ],
        "parameterTable": (
            {
                "headers": param_table.headers,
                "rows": param_table.rows,
                "provenance": f"{manifest_entry['id']}#parameters table",
            }
            if param_table
            else None
        ),
        "history": (
            {
                "headers": history.headers,
                "rows": history.rows,
                "provenance": f"{manifest_entry['id']}#history details/table",
            }
            if history
            else None
        ),
        "sections": {
            key: {"heading": v["heading"], "text": v["text"], "provenance": f"h2#{key}"}
            for key, v in sections.items()
        },
        "seeAlso": see_also,
        "properties": properties,
        "parseWarnings": warnings,
    }
    return record

"""Shared HTML parsing helpers for the 4D Command IR pipeline.

All stages that need to read a command's HTML page should go through here so
there is exactly one place that knows how the mirrored Docusaurus markup is
shaped (element classes, table layout quirks, etc.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag

_WS_RE = re.compile(r"\s+")


def read_html(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_article(html: str) -> Optional[Tag]:
    """Return the <article> element, parsed leniently, or None if absent."""
    soup = BeautifulSoup(html, "lxml")
    return soup.find("article")


def norm_text(s: str) -> str:
    """Collapse whitespace the way a browser would render it, trim ends."""
    return _WS_RE.sub(" ", s).strip()


def slugify_id(display_name: str) -> str:
    """Derive the IR `id` from a command's `displayName`.

    Matches the convention used in the hand-authored regression fixtures:
    whitespace and underscores become hyphens, case is preserved.
    e.g. "ORDER BY FORMULA" -> "ORDER-BY-FORMULA", "C_LONGINT" -> "C-LONGINT".
    """
    return re.sub(r"[\s_]+", "-", display_name.strip())


@dataclass
class TableWarning:
    where: str
    reason: str
    raw_html: str


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[dict[str, str]]
    warnings: list[TableWarning] = field(default_factory=list)


def _first_signature_paragraph(article: Tag) -> Optional[Tag]:
    """Return the first <p> in the markdown body whose content opens with a
    <strong> tag (the syntax-line pattern: "**Name** ( ... )" or
    "**Name** -> Type"). Skips over the optional leading History <details>
    block. Returns None if no such paragraph exists near the top.
    """
    markdown_div = article.find("div", class_=lambda c: c and "markdown" in c)
    scope = markdown_div or article
    header = scope.find("header")
    # Only look at the handful of elements right after the header, before
    # any <h2> section heading, so we don't accidentally match a bolded
    # phrase deep in prose on a non-command page.
    seen_header = header is None
    checked = 0
    for child in scope.find_all(["header", "h2", "p"], recursive=False):
        if child is header:
            seen_header = True
            continue
        if not seen_header:
            continue
        if child.name == "h2":
            break
        if child.name == "p":
            checked += 1
            contents = [c for c in child.contents if getattr(c, "name", None) or str(c).strip()]
            idx = 0
            # Tolerate a short leading literal marker before the command name
            # (category C: e.g. a positional "*" or a stray "<" rendering
            # artifact) — a real command's bolded name still follows right
            # after it.
            if (
                idx < len(contents)
                and getattr(contents[idx], "name", None) is None
                and re.fullmatch(r"[^\w\s]{1,3}", str(contents[idx]).strip() or "\0")
            ):
                idx += 1
            if idx < len(contents) and getattr(contents[idx], "name", None) == "strong":
                return child
            if checked >= 2:
                break
    return None


def is_command_page(article: Tag) -> bool:
    """Heuristic: real command pages open (right after the header, modulo an
    optional History block) with a paragraph shaped like a syntax line: a
    bolded command name followed by "(...)" params or "-> Type". Index and
    listing pages (command-index.html, category pages, constant-list.html,
    database-method callback docs, OOP class pages) don't have this shape.
    """
    header = article.find("header")
    h1 = header.find("h1") if header else article.find("h1")
    if h1 is None or not norm_text(h1.get_text()):
        return False
    return _first_signature_paragraph(article) is not None


def signature_name_mismatch(article: Tag) -> Optional[str]:
    """Return the signature paragraph's leading <strong> text if it differs
    from the <h1> title, else None. Used to flag (not exclude) pages where
    the two disagree (seen in the wild, e.g. a stale/typo'd <h1>), so Stage 1
    can carry both and a human can decide which is canonical.
    """
    title = command_title(article)
    sig_p = _first_signature_paragraph(article)
    if sig_p is None:
        return None
    strong = sig_p.find("strong")
    strong_text = norm_text(strong.get_text()) if strong else ""
    if strong_text and strong_text.lower() != title.lower():
        return strong_text
    return None


def breadcrumb_theme(article: Tag) -> Optional[str]:
    """Extract the theme name from the breadcrumb nav, if present.

    Looks for a breadcrumb link whose href contains "/theme/" (classic
    per-theme grouping used under commands/). Returns the link's visible
    text, or None if this command page isn't grouped by theme (e.g. View Pro
    pages, which are grouped alphabetically via commands-legacy/ instead).
    """
    nav = article.find("nav", class_=lambda c: c and "breadcrumbs" in c)
    if nav is None:
        return None
    for a in nav.find_all("a"):
        href = a.get("href", "")
        if "theme/" in href:
            span = a.find("span")
            return norm_text((span or a).get_text())
    return None


def version_badge(article: Tag) -> Optional[str]:
    span = article.find("span", class_=lambda c: c and "version-badge" in c)
    if span is None:
        return None
    text = norm_text(span.get_text())
    return text.split(":", 1)[1].strip() if ":" in text else text


def command_title(article: Tag) -> str:
    header = article.find("header")
    h1 = header.find("h1") if header else article.find("h1")
    return norm_text(h1.get_text()) if h1 else ""


def parse_table_defensive(table: Tag, where: str) -> ParsedTable:
    """Parse an HTML table into header-keyed rows, expanding rowspan/colspan
    and never raising on malformed structure. Anything that can't be resolved
    cleanly is recorded as a warning with the raw HTML kept alongside, rather
    than dropped.
    """
    warnings: list[TableWarning] = []
    thead = table.find("thead")
    headers: list[str] = []
    if thead is not None:
        header_cells = thead.find_all(["th", "td"])
        headers = [norm_text(c.get_text()) or f"col{i}" for i, c in enumerate(header_cells)]
    else:
        first_row = table.find("tr")
        if first_row is not None:
            header_cells = first_row.find_all(["th", "td"])
            if header_cells and all(c.name == "th" for c in header_cells):
                headers = [norm_text(c.get_text()) or f"col{i}" for i, c in enumerate(header_cells)]

    if not headers:
        warnings.append(
            TableWarning(where=where, reason="no header row detected", raw_html=str(table))
        )

    tbody = table.find("tbody") or table
    body_rows = [
        tr for tr in tbody.find_all("tr", recursive=True)
        if tr.find_parent("thead") is None
    ]

    # Column-carry buffers for rowspan handling: index -> (remaining_rows, text)
    carry: dict[int, list] = {}
    rows: list[dict[str, str]] = []
    for tr in body_rows:
        cells = tr.find_all(["td", "th"], recursive=False)
        values: list[str] = []
        col = 0

        def place(col_idx, text, span):
            while len(values) <= col_idx:
                values.append("")
            values[col_idx] = text
            if span > 1:
                carry[col_idx] = [span - 1, text]

        # apply any carried-over rowspans that land before real cells
        cell_iter = iter(cells)
        current = next(cell_iter, None)
        max_col = max(list(carry.keys()) + [len(cells) - 1 + col], default=-1)
        col = 0
        while current is not None or any(v[0] > 0 for v in carry.values()):
            if col in carry and carry[col][0] > 0:
                remaining, text = carry[col]
                place(col, text, 0)
                carry[col][0] = remaining - 1
                col += 1
                continue
            if current is None:
                break
            text = norm_text(current.get_text())
            colspan = int(current.get("colspan", 1) or 1)
            rowspan = int(current.get("rowspan", 1) or 1)
            for i in range(colspan):
                place(col + i, text, rowspan if i == 0 else 1)
            col += colspan
            current = next(cell_iter, None)

        if not values:
            continue
        if headers and len(values) != len(headers):
            warnings.append(
                TableWarning(
                    where=where,
                    reason=f"row has {len(values)} cells, header has {len(headers)}",
                    raw_html=str(tr),
                )
            )
        row = {}
        for i, v in enumerate(values):
            key = headers[i] if i < len(headers) else f"col{i}"
            row[key] = v
        rows.append(row)

    return ParsedTable(headers=headers, rows=rows, warnings=warnings)

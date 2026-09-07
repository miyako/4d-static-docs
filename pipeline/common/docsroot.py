"""Resolve which local docs snapshot (version folder) the pipeline runs against."""
from __future__ import annotations

import re
from pathlib import Path

# Command-directory names known to hold real per-command HTML pages, relative
# to a resolved docs-version root. Discovered by inspection of the mirror:
#   - "commands"            classic 4D language commands
#   - "WritePro/commands"   4D Write Pro ("WP ...") commands
#   - "ViewPro/commands"    4D View Pro ("VP ...") commands, indexed
#                           alphabetically via commands-legacy/*.html rather
#                           than by theme. Included by default because they
#                           are classic procedural commands (not OOP class
#                           pages), but flagged with theme "View Pro" so they
#                           can be filtered out downstream if this pass should
#                           be scoped narrower than "all classic commands".
COMMAND_DIRS = ["commands", "WritePro/commands", "ViewPro/commands"]

# Filenames inside the command directories above that are index/listing pages,
# not real command docs, and must never be treated as a command.
KNOWN_NON_COMMAND_FILES = {"command-index.html"}

_VERSION_DIR_RE = re.compile(r"^(\d+)(?:-R(\d+))?$")


def _version_sort_key(name: str):
    m = _VERSION_DIR_RE.match(name)
    if not m:
        return None
    major = int(m.group(1))
    revision = int(m.group(2)) if m.group(2) else 0
    return (major, revision)


def _badge_text(html_path: Path) -> str | None:
    if not html_path.exists():
        return None
    text = html_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Version:\s*([^<]*)", text)
    return m.group(1).strip() if m else None


def resolve_docs_root(mirror_docs_dir: Path, requested_version: str | None = None) -> Path:
    """Pick the docs-version root to process.

    If `requested_version` is given, use `mirror_docs_dir/<requested_version>`
    directly (must exist). Otherwise, scan version-numbered subdirectories
    (e.g. "18", "20", "21", "21-R3") and pick the highest one whose version
    badge does not contain "BETA". The un-versioned top-level `commands/`
    directory (which mirrors the in-development next release, badged e.g.
    "21 R4 BETA") is deliberately never auto-selected.
    """
    if requested_version:
        root = mirror_docs_dir / requested_version
        if not root.is_dir():
            raise FileNotFoundError(f"Requested docs version not found: {root}")
        return root

    candidates = []
    for child in mirror_docs_dir.iterdir():
        if not child.is_dir():
            continue
        key = _version_sort_key(child.name)
        if key is None:
            continue
        probe = child / "commands" / "abs.html"
        badge = _badge_text(probe)
        if badge is None:
            continue
        if "beta" in badge.lower():
            continue
        candidates.append((key, child, badge))

    if not candidates:
        raise FileNotFoundError(
            f"No non-beta version folder with a readable badge found under {mirror_docs_dir}"
        )

    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


def command_dirs(docs_root: Path):
    for rel in COMMAND_DIRS:
        d = docs_root / rel
        if d.is_dir():
            yield rel, d

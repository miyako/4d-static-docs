"""Shared helpers for the OOP IR pipeline (stages O0-O5).

Deliberately thin: anything generic about the docs mirror or HTML shape lives
in `pipeline/common/*` and is imported from there, not forked here. What lives
here is only what is specific to the OOP corpus: the two-source join between
`references/syntaxEN.json` and `mirror/docs/<version>/API/*.html`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from common.htmlutil import norm_text, parse_article, read_html  # noqa: E402

# The API directory, relative to a resolved docs-version root.
API_DIR = "API"

ZERO_WIDTH_SPACE = "\u200b"

# syntaxEN.json top-level keys that are not OOP classes.
#   _command_ : the 1353 classic commands, already covered by out/4d-command-ir.json
#   4D        : the class-store constructor namespace (4D.<X>.new()), handled separately
NON_CLASS_KEYS = {"_command_"}
CLASS_STORE_KEY = "4D"

# Sentinel key inside a class map that records its superclass rather than a member.
INHERITED_FROM_KEY = "_inheritedFrom_"

# API page <h1> titles that differ from the corresponding syntaxEN.json key.
# Verified by inspection of all 45 pages in the 21-R3 snapshot.
PAGE_TITLE_TO_CLASS = {
    "Directory Class": "Directory",
    "Document Class": "Document",
    "ZIPArchive": "ZipArchive",
    "ZIPFile": "ZipFile",
    "ZIPFolder": "ZipFolder",
    # ClassStoreClass.html documents the `4D.` / `cs.` class stores themselves,
    # i.e. the namespace whose members are the 4D.<X>.new() constructors that
    # syntaxEN.json files under its "4D" key.
    "ClassStore": CLASS_STORE_KEY,
}

# Headings that appear at member-heading level but are section headings, not
# members. Matched after zero-width-space stripping.
NON_MEMBER_HEADINGS = {
    "Description",
    "Example",
    "See also",
    "Commands and functions",
    "Functions and properties",
    "History",
    "Properties",
    "Functions",
    "[index]",
}

# Documented pseudo-members whose name is not fixed: the heading stands for
# "any attribute / dataclass / class / component name", so there is no fixed
# signature to extract. Modelled as dynamicMember entries rather than dropped.
# Value is the evidence recorded in the reconciliation report.
DYNAMIC_MEMBER_HEADINGS = {
    ("DataClass", ".attributeName"): "attribute name comes from the user's data model",
    ("DataStore", ".dataclassName"): "dataclass name comes from the user's data model",
    ("Entity", ".attributeName"): "attribute name comes from the user's data model",
    ("EntitySelection", ".attributeName"): "attribute name comes from the user's data model",
    ("4D", ".classStoreName"): "names a class store (4D or cs), not a fixed member",
    ("4D", ".classClassName"): "names a user or built-in class inside a class store",
    ("WebForm", ".componentName"): "names a component in the web form, not a fixed member",
}

_PARAM_TAIL_RE = re.compile(r"\(.*\)\s*$", re.S)


def load_syntax_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def oop_class_names(syntax: dict) -> list[str]:
    """The 45 built-in class keys, excluding the classic corpus and 4D store."""
    return sorted(
        k for k in syntax if k not in NON_CLASS_KEYS and k != CLASS_STORE_KEY
    )


def class_members(syntax: dict, class_name: str) -> dict:
    """Members of one class, with the _inheritedFrom_ sentinel filtered out."""
    return {
        k: v
        for k, v in syntax.get(class_name, {}).items()
        if k != INHERITED_FROM_KEY and isinstance(v, dict)
    }


def superclass_of(syntax: dict, class_name: str) -> str | None:
    entry = syntax.get(class_name, {})
    value = entry.get(INHERITED_FROM_KEY)
    return value if isinstance(value, str) else None


def superclass_chain(syntax: dict, class_name: str) -> list[str]:
    """Ancestor class names, nearest first. Cycle-safe."""
    chain: list[str] = []
    seen = {class_name}
    current = superclass_of(syntax, class_name)
    while current and current not in seen:
        chain.append(current)
        seen.add(current)
        current = superclass_of(syntax, current)
    return chain


def constructor_members(syntax: dict) -> dict[str, dict]:
    """Map "4D.<Class>.new()" -> the syntaxEN record for every constructor."""
    out: dict[str, dict] = {}
    for target_class, members in syntax.get(CLASS_STORE_KEY, {}).items():
        if not isinstance(members, dict):
            continue
        for member_key, record in members.items():
            out[f"{CLASS_STORE_KEY}.{target_class}.{member_key}"] = record
    return out


def api_pages(docs_root: Path) -> Iterator[Path]:
    yield from sorted((docs_root / API_DIR).glob("*.html"))


def page_class_name(article) -> str:
    h1 = article.find("h1")
    title = norm_text(h1.get_text()).replace(ZERO_WIDTH_SPACE, "") if h1 else ""
    return PAGE_TITLE_TO_CLASS.get(title, title)


def strip_zws(text: str) -> str:
    return text.replace(ZERO_WIDTH_SPACE, "")


def normalize_member_heading(heading: str) -> str:
    """Reduce a member heading to its joinable key.

    "`.copyTo`( destinationFolder ; ... )" -> ".copyTo()"
    "4D.Blob.new()"                        -> "4D.Blob.new()"
    ".length"                              -> ".length"

    Parameter lists are dropped because syntaxEN keys carry only "name()".
    """
    text = strip_zws(heading).strip()
    text = text.replace("`", "")
    if text.endswith(")"):
        text = _PARAM_TAIL_RE.sub("()", text)
    return text.strip()


def is_member_heading(text: str) -> bool:
    text = strip_zws(text).strip()
    if text in NON_MEMBER_HEADINGS:
        return False
    return text.startswith(".") or text.startswith("4D.") or text.startswith("cs.")


def member_headings(article) -> list[dict]:
    """Every member-shaped heading on an API page, with its evidence.

    Member sections are <h2> on 43 of the 45 pages; WebForm and WebFormItem use
    <h3> instead. Both levels are accepted, and the level actually used is
    recorded so the reconciliation report can evidence the artifact rather than
    hide it.
    """
    out = []
    for tag in article.find_all(["h2", "h3"]):
        raw = norm_text(tag.get_text())
        if not is_member_heading(raw):
            continue
        out.append(
            {
                "raw": raw,
                "key": normalize_member_heading(raw),
                "level": tag.name,
                "hadZeroWidthSpace": ZERO_WIDTH_SPACE in raw,
            }
        )
    return out


def non_member_headings(article) -> list[dict]:
    out = []
    for tag in article.find_all(["h2", "h3"]):
        raw = norm_text(tag.get_text())
        if is_member_heading(raw):
            continue
        out.append({"raw": raw, "level": tag.name})
    return out


def load_api_page(path: Path):
    article = parse_article(read_html(path))
    if article is None:
        raise ValueError(f"no <article> element in {path}")
    return article


def member_kind(class_name: str, member_key: str) -> str:
    """Map a syntaxEN member key to the IR `CommandEntry.kind` value."""
    if class_name == CLASS_STORE_KEY:
        return "oop_constructor"
    return "oop_function" if member_key.endswith(")") else "oop_property"


def member_id(class_name: str, member_key: str) -> str:
    """Receiver-qualified IR id.

    Constructors are already fully qualified in the class store
    ("4D.Blob.new()"). Instance/class members become "<Class>.<member>" with
    the trailing "()" dropped: "Collection.length", "Collection.query".

    Classic ids are SCREAMING-KEBAB / Capitalized-Words and contain no dots, so
    these two id spaces cannot collide; the assembler asserts it anyway.
    """
    bare = member_key[:-2] if member_key.endswith("()") else member_key
    return bare if class_name == CLASS_STORE_KEY else f"{class_name}.{bare}"


def iter_syntax_members(syntax: dict):
    """Yield (id, class, memberKey, record) for every syntaxEN OOP member.

    Covers the 45 built-in classes plus the 19 class-store constructors, and
    excludes the classic `_command_` corpus and the `_inheritedFrom_`
    sentinels.
    """
    for class_name in oop_class_names(syntax):
        for member_key, record in class_members(syntax, class_name).items():
            yield member_id(class_name, member_key), class_name, member_key, record
    for target_class, members in syntax.get(CLASS_STORE_KEY, {}).items():
        if not isinstance(members, dict):
            continue
        for member_key, record in members.items():
            key = f"{CLASS_STORE_KEY}.{target_class}.{member_key}"
            yield member_id(CLASS_STORE_KEY, key), CLASS_STORE_KEY, key, record

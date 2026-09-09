#!/usr/bin/env python3
"""Stage O7 (Phase 4) -- harvest the hand-written `Example` sections from the
4D OOP API documentation pages into `out/oop_doc_examples.json`.

Why this re-parses the HTML instead of reading `out/oop_stage1_raw.json`:
O1 preserves example blocks via BeautifulSoup's `get_text()`, which drops the
`<br/>` between the Docusaurus/Prism `<span class="token-line">` elements that
carry each source line. The result is every snippet collapsed onto ONE line --
still "an example", but no longer compilable 4D and no longer byte-faithful to
the page. Since Phase 4's whole premise is that these snippets are real,
idiomatic, *compiler-verifiable* 4D, the line structure is load-bearing, so
this stage reads the token-line spans directly. A gate below re-derives O1's
whitespace-collapsed form from the harvested text and requires it to match
O1's stored `code`, so this stage can never silently disagree with O1 about
WHAT was harvested while fixing HOW it was harvested.

Attribution: the IR models an inherited member once, on the class that
declares it (`.exists` lives on `Document`, not `File`), but subclass pages
re-document inherited members with their own, more specific examples. Each
harvested example is therefore attributed to BOTH:

* `memberId`         -- the IR entry it documents (`Document.exists`)
* `attributedClassId`-- the class whose page it was written for (`File`)

so a consumer answering "how do I test whether a file exists" can prefer the
`File` example over the `Document` one, without re-scraping anything.

Usage:
    python3 pipeline/oop/stage7_doc_examples.py [--repo-root PATH]
        [--version 21-R3] [--out out/oop_doc_examples.json]

This stage is pure Python: no tool4d, no network. Compiler verification of the
harvested snippets is a separate stage (`stage8_verify_examples.py`) so a
clean clone can still reproduce this artifact.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oopcommon as oop  # noqa: E402
from common.docsroot import resolve_docs_root  # noqa: E402
from common.htmlutil import norm_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = REPO_ROOT / "out" / "oop_doc_examples.json"
IR_PATH = REPO_ROOT / "out" / "4d-oop-ir.json"
MANIFEST_PATH = REPO_ROOT / "out" / "oop_manifest.json"
STAGE1_PATH = REPO_ROOT / "out" / "oop_stage1_raw.json"

# Sub-headings that introduce example code. The pages are inconsistent
# ("Example", "Example 1", "Examples", "Example: reading a file"), so this is
# a prefix test, matching O1's own `startswith("Example")` rule.
EXAMPLE_HEADING_RE = re.compile(r"^examples?\b", re.I)


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def _markdown_div(article):
    div = article.find("div", class_=lambda c: c and "markdown" in c)
    return div if div is not None else article


def _code_lines(block_div) -> list[str]:
    """Return the source lines of one Prism-rendered code block, verbatim.

    Docusaurus renders each line as `<span class="token-line">...</span><br/>`
    inside `<code>`. `get_text()` on the `<code>` concatenates those without
    separators (that is the newline loss this stage exists to avoid), so the
    token-line spans are read individually. Pages that predate that markup, or
    that use a plain `<pre><code>`, fall back to splitting the raw text.
    """
    code = block_div.find("code")
    host = code if code is not None else block_div
    lines = [
        span.get_text()
        for span in host.find_all("span", class_="token-line", recursive=False)
    ]
    if not lines:
        lines = host.get_text().split("\n")
    # Trailing blank lines are rendering artifacts, not content; leading
    # indentation is content and is preserved exactly.
    while lines and not lines[-1].strip():
        lines.pop()
    return [line.rstrip("\n") for line in lines]


def _block_language(block_div) -> str | None:
    for cls in block_div.get("class") or []:
        if isinstance(cls, str) and cls.startswith("language-"):
            return cls[len("language-"):]
    return None


def _is_code_block(tag) -> bool:
    if tag.name != "div":
        return False
    return any(
        isinstance(c, str) and c.startswith("language-") for c in (tag.get("class") or [])
    )


def harvest_page(article, docs_rel: str, class_name: str) -> list[dict]:
    """Return every code block on one API page, tagged with the member section
    and the example sub-heading it appeared under, plus the prose paragraph
    immediately preceding it (the caption)."""
    md = _markdown_div(article)
    children = list(md.find_all(recursive=False))
    levels = {
        tag.name
        for tag in children
        if tag.name in ("h2", "h3") and oop.is_member_heading(norm_text(tag.get_text()))
    }
    split_level = "h2" if "h2" in levels else ("h3" if "h3" in levels else None)

    out: list[dict] = []
    member_key: str | None = None
    sub_heading: str | None = None
    last_prose: str | None = None
    seq: dict[str, int] = {}

    for tag in children:
        name = tag.name
        if split_level and name == split_level:
            raw = norm_text(tag.get_text())
            member_key = (
                oop.normalize_member_heading(raw) if oop.is_member_heading(raw) else None
            )
            sub_heading = None
            last_prose = None
            continue
        if name in ("h2", "h3", "h4", "h5"):
            sub_heading = oop.strip_zws(norm_text(tag.get_text())).strip()
            last_prose = None
            continue
        if name in ("p", "blockquote"):
            text = oop.strip_zws(norm_text(tag.get_text())).strip()
            if text:
                last_prose = text
            continue
        if _is_code_block(tag):
            if member_key is None:
                # Page-level preamble code (e.g. the class overview), not tied
                # to a member. Recorded as unattributed rather than dropped.
                key = "(page)"
            else:
                key = member_key
            seq[key] = seq.get(key, 0) + 1
            out.append(
                {
                    "classId": class_name,
                    "memberKey": member_key,
                    "docPage": docs_rel,
                    "title": sub_heading,
                    "isExampleSection": bool(
                        sub_heading and EXAMPLE_HEADING_RE.match(sub_heading)
                    ),
                    "caption": last_prose,
                    "language": _block_language(tag),
                    "lines": _code_lines(tag),
                    "index": seq[key],
                }
            )
            continue

    return out


def build_attribution(ir: dict, manifest: dict):
    """Return (resolve, member_ids).

    `resolve(class_id, member_key)` -> (member_id, declaring_class_id) or
    (None, None). A member documented on a subclass page resolves to the
    declaring class's IR id by walking the `classes{}.superclass` chain, which
    is how an inherited-member example gets attached to the entry that
    actually exists in the IR.
    """
    by_page_key: dict[tuple[str, str], str] = {}
    for entry in manifest["entries"]:
        by_page_key[(entry["docPage"], entry["memberKey"])] = entry["id"]

    by_class_member: dict[tuple[str, str], str] = {}
    for command in ir["commands"]:
        cls = command["receiver"]["classId"]
        by_class_member[(cls, command["memberName"])] = command["id"]
        if command["kind"] == "oop_constructor":
            # `4D.File.new` is declared under receiver class "File" but its
            # doc heading is "4D.File.new()" on FileClass.html.
            by_class_member[(cls, f"4D.{cls}.new")] = command["id"]

    classes = ir["classes"]

    def chain(class_id: str):
        seen = set()
        cur = class_id
        while cur and cur not in seen:
            seen.add(cur)
            yield cur
            cur = (classes.get(cur) or {}).get("superclass")

    def resolve(class_id: str, member_key: str, doc_page: str):
        direct = by_page_key.get((doc_page, member_key))
        if direct:
            return direct, ir_declaring(direct)
        # Normalize ".slice()" / "slice()" / ".size" to the IR's ".slice" form.
        bare = member_key.strip()
        bare = re.sub(r"\(\s*\)$", "", bare)
        if not bare.startswith("."):
            if bare.startswith("4D."):
                pass
            else:
                bare = "." + bare
        for cls in chain(class_id):
            hit = by_class_member.get((cls, bare))
            if hit:
                return hit, cls
        return None, None

    def ir_declaring(member_id: str) -> str:
        for command in ir["commands"]:
            if command["id"] == member_id:
                return command["receiver"]["classId"]
        return ""

    return resolve


def check_against_stage1(harvested: list[dict], stage1: dict) -> dict:
    """Gate: every code block O1 recorded must be present here with identical
    content once whitespace-collapsed.

    This is the equality check the review lesson demands at a lossy hand-off:
    it proves this stage re-parsed the SAME blocks O1 saw and only restored
    information O1 destroyed (the `<br/>` line separators), rather than
    silently harvesting a different set of snippets under a nicer format.

    Containment, not equality, is the correct relation here: O1 discards code
    blocks that sit outside a member `<h2>` section (page preambles on
    TCPConnection, Function, Method, Formula, WebSocket, ... -- 40 blocks in
    total), and this stage deliberately keeps them as `unattributed`. Extra
    blocks here are therefore recovered content, not a discrepancy; a block O1
    saw and this stage did NOT is a real failure.
    """
    from collections import Counter

    def collapse(text: str) -> str:
        return " ".join(text.split())

    mine: dict[str, Counter] = {}
    for ex in harvested:
        # O1's `code.get_text()` concatenates the token-line spans with NO
        # separator (that is precisely the lost `<br/>`), so the harvested
        # lines are re-joined the same way before collapsing -- otherwise the
        # gate would flag its own fix as a difference.
        mine.setdefault(ex["docPage"], Counter())[collapse("".join(ex["lines"]))] += 1

    theirs: dict[str, Counter] = {}
    for cls in stage1.values():
        page = cls["docPage"]
        for section in cls["sections"]:
            for example in section.get("examples") or []:
                for block in example.get("blocks") or []:
                    theirs.setdefault(page, Counter())[collapse(block["code"])] += 1

    problems = []
    recovered = 0
    for page in sorted(set(mine) | set(theirs)):
        here, there = mine.get(page, Counter()), theirs.get(page, Counter())
        dropped = there - here
        if dropped:
            problems.append(
                {
                    "docPage": page,
                    "countHere": sum(here.values()),
                    "countStage1": sum(there.values()),
                    "inStage1ButNotHere": list(dropped.elements())[:3],
                }
            )
        recovered += sum((here - there).values())
    return {
        "status": "pass" if not problems else "fail",
        "relation": "every out/oop_stage1_raw.json code block is present here",
        "recoveredBeyondStage1": recovered,
        "problems": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--version")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    docs_root = resolve_docs_root(repo_root / "mirror" / "docs", args.version)
    ir = load_json(IR_PATH)
    manifest = load_json(MANIFEST_PATH)
    stage1 = load_json(STAGE1_PATH)
    resolve = build_attribution(ir, manifest)

    harvested: list[dict] = []
    for page in sorted(oop.api_pages(docs_root)):
        article = oop.load_api_page(page)
        if article is None:
            continue
        class_name = oop.page_class_name(article)
        rel = str(page.relative_to(repo_root))
        harvested.extend(harvest_page(article, rel, class_name))

    gate = check_against_stage1(harvested, stage1)

    examples = []
    unattributed = []
    for ex in harvested:
        code = "\n".join(ex["lines"])
        if not code.strip():
            continue
        record = {
            "docPage": ex["docPage"],
            "attributedClassId": ex["classId"],
            "title": ex["title"],
            "caption": ex["caption"],
            "language": ex["language"],
            "code": code,
            "isExampleSection": ex["isExampleSection"],
        }
        member_id = None
        declaring = None
        if ex["memberKey"]:
            doc_rel = ex["docPage"].split("/", 3)[-1]
            member_id, declaring = resolve(
                ex["classId"], ex["memberKey"], f"API/{Path(ex['docPage']).name}"
            )
        if member_id is None:
            record["memberKey"] = ex["memberKey"]
            unattributed.append(record)
            continue
        record["memberId"] = member_id
        record["declaringClassId"] = declaring
        record["inherited"] = declaring != ex["classId"]
        record["exampleId"] = f"{member_id}#{ex['classId']}#{ex['index']}"
        examples.append(record)

    # Deterministic order: by member, then by the class page it came from,
    # then by position on that page.
    examples.sort(key=lambda r: (r["memberId"], r["attributedClassId"], r["exampleId"]))

    payload = {
        "docsRoot": str(docs_root.relative_to(repo_root)),
        "counts": {
            "codeBlocks": len(harvested),
            "attributed": len(examples),
            "unattributed": len(unattributed),
            "inExampleSections": sum(1 for e in examples if e["isExampleSection"]),
            "membersWithExample": len({e["memberId"] for e in examples}),
            "inheritedAttributions": sum(1 for e in examples if e["inherited"]),
        },
        "stage1ParityGate": gate,
        "examples": examples,
        "unattributed": unattributed,
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    counts = payload["counts"]
    print(f"code blocks:           {counts['codeBlocks']}")
    print(f"attributed to member:  {counts['attributed']}")
    print(f"  of which inherited:  {counts['inheritedAttributions']}")
    print(f"  in Example sections: {counts['inExampleSections']}")
    print(f"distinct members:      {counts['membersWithExample']}")
    print(f"unattributed:          {counts['unattributed']}")
    print(f"O1 parity gate:        {gate['status']} "
          f"(+{gate['recoveredBeyondStage1']} blocks O1 dropped)")
    print(f"-> {out_path.relative_to(repo_root)}")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

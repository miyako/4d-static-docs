#!/usr/bin/env python3
"""Phase 1.2 — reconcile the two OOP sources before any extraction happens.

Joins, per class, the member headings on `mirror/docs/<version>/API/*.html`
against the member keys in `references/syntaxEN.json`, and classifies every
mismatch into exactly one category with the evidence that produced it. Nothing
is dropped silently: the sum of matched + every delta category equals the total
of both input surfaces.

Categories
----------
matched                    present in both sources
inherited_from_superclass  documented on a subclass page; declared on an
                           ancestor class in syntaxEN (via _inheritedFrom_)
dynamic_member             documented pseudo-member with no fixed name
                           (.attributeName, .dataclassName)
syntaxen_missing           documented in HTML, absent from syntaxEN and not
                           explainable by inheritance or dynamism
doc_missing                present in syntaxEN, no heading on the class page

Two further artifact classes are recorded as annotations on matched pairs
rather than as deltas, because they are normalizations this joiner performs
rather than genuine source disagreements:
  heading_level_artifact   member documented as <h3> instead of <h2>
  name_normalization       heading needed zero-width-space stripping and/or
                           parameter-list truncation to join

Usage:
    python3 pipeline/oop/stage0_reconcile.py [--repo-root PATH]
        [--version 21-R3] [--docs-root PATH] [--syntax-json PATH]
        [--out out/oop_source_diff.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.docsroot import resolve_docs_root  # noqa: E402  (pipeline/common)

import oopcommon as oop  # noqa: E402  (pipeline/oop/oopcommon.py)


def reconcile(docs_root: Path, syntax: dict) -> dict:
    constructors = oop.constructor_members(syntax)
    per_class = []
    counts = {
        "matched": 0,
        "inherited_from_superclass": 0,
        "dynamic_member": 0,
        "syntaxen_missing": 0,
        "doc_missing": 0,
    }
    annotations = {"heading_level_artifact": 0, "name_normalization": 0}
    non_member_headings_all = []
    pages_seen = set()

    for page in oop.api_pages(docs_root):
        article = oop.load_api_page(page)
        class_name = oop.page_class_name(article)
        pages_seen.add(class_name)
        rel_page = f"{oop.API_DIR}/{page.name}"

        headings = oop.member_headings(article)
        for h in oop.non_member_headings(article):
            non_member_headings_all.append(dict(h, page=rel_page, klass=class_name))

        if class_name == oop.CLASS_STORE_KEY:
            # ClassStoreClass.html documents the class stores themselves; the
            # 4D.<X>.new() constructors are documented on each target class's
            # own page, so this page contributes no member headings to join.
            syn_keys: dict[str, str] = {}
        else:
            syn_keys = {"." + k: k for k in oop.class_members(syntax, class_name)}
            for full_id, _ in constructors.items():
                # "4D.Blob.new()" is documented on BlobClass.html.
                target = full_id.split(".")[1]
                if target == class_name:
                    syn_keys[full_id] = full_id

        chain = oop.superclass_chain(syntax, class_name)
        matched_keys = set()
        entries = []

        for h in headings:
            key = h["key"]
            record = {
                "member": key,
                "heading": h["raw"],
                "headingLevel": h["level"],
                "page": rel_page,
            }
            normalizations = []
            if h["hadZeroWidthSpace"]:
                normalizations.append("stripped U+200B zero-width space")
            if h["raw"] != key:
                normalizations.append("truncated parameter list to '()'")
            if h["level"] != "h2":
                normalizations.append(f"member documented as <{h['level']}>, not <h2>")

            if key in syn_keys:
                matched_keys.add(key)
                counts["matched"] += 1
                if h["level"] != "h2":
                    annotations["heading_level_artifact"] += 1
                if h["hadZeroWidthSpace"] or h["raw"] != key:
                    annotations["name_normalization"] += 1
                record["category"] = "matched"
                if normalizations:
                    record["normalizations"] = normalizations
                entries.append(record)
                continue

            # Not in this class's own syntaxEN map: try the superclass chain.
            declaring = None
            for ancestor in chain:
                if key[1:] in oop.class_members(syntax, ancestor):
                    declaring = ancestor
                    break
            if declaring is not None:
                counts["inherited_from_superclass"] += 1
                record["category"] = "inherited_from_superclass"
                record["declaredOn"] = declaring
                record["evidence"] = (
                    f"syntaxEN.json['{class_name}']['_inheritedFrom_'] resolves to "
                    f"'{declaring}', which declares '{key[1:]}'"
                )
                entries.append(record)
                continue

            if (class_name, key) in oop.DYNAMIC_MEMBER_HEADINGS:
                counts["dynamic_member"] += 1
                record["category"] = "dynamic_member"
                record["evidence"] = (
                    "heading names a placeholder, not a fixed member: "
                    + oop.DYNAMIC_MEMBER_HEADINGS[(class_name, key)]
                )
                entries.append(record)
                continue

            counts["syntaxen_missing"] += 1
            record["category"] = "syntaxen_missing"
            record["evidence"] = (
                f"heading present on {rel_page}; no key '{key[1:]}' in "
                f"syntaxEN.json['{class_name}'] nor in its superclass chain "
                f"{chain or '[]'}"
            )
            entries.append(record)

        for key in sorted(set(syn_keys) - matched_keys):
            counts["doc_missing"] += 1
            entries.append(
                {
                    "member": key,
                    "category": "doc_missing",
                    "page": rel_page,
                    "evidence": (
                        f"syntaxEN.json declares '{key}' for class "
                        f"'{class_name}' but {rel_page} has no matching "
                        f"<h2>/<h3> heading"
                    ),
                }
            )

        per_class.append(
            {
                "class": class_name,
                "page": rel_page,
                "superclass": oop.superclass_of(syntax, class_name),
                "headings": len(headings),
                "syntaxEnMembers": len(syn_keys),
                "entries": entries,
            }
        )

    # Classes present in syntaxEN with no API page of their own. These are
    # abstract bases (e.g. Transporter) whose members are documented only on
    # their subclasses' pages, where they surface as
    # `inherited_from_superclass` deltas.
    orphan_classes = []
    for name in oop.oop_class_names(syntax):
        if name in pages_seen:
            continue
        subclasses = [
            c for c in oop.oop_class_names(syntax)
            if name in oop.superclass_chain(syntax, c)
        ]
        orphan_classes.append(
            {
                "class": name,
                "members": len(oop.class_members(syntax, name)),
                "documentedVia": subclasses,
                "evidence": (
                    f"no API/{name}*.html page; every member appears on the "
                    f"pages of {subclasses} as an inherited member"
                ),
            }
        )

    syntax_member_total = sum(
        len(oop.class_members(syntax, c)) for c in oop.oop_class_names(syntax)
    ) + len(constructors)
    orphan_members = sum(o["members"] for o in orphan_classes)

    return {
        "perClass": per_class,
        "nonMemberHeadings": non_member_headings_all,
        "orphanClasses": orphan_classes,
        "counts": counts,
        "annotations": annotations,
        "accounting": {
            "syntaxEnMembers": syntax_member_total,
            "matchedToADocHeading": counts["matched"],
            "declaredOnAnOrphanBaseClass": orphan_members,
            "unaccountedSyntaxEnMembers": (
                syntax_member_total - counts["matched"] - orphan_members
            ),
            "docHeadings": (
                counts["matched"]
                + counts["inherited_from_superclass"]
                + counts["dynamic_member"]
                + counts["syntaxen_missing"]
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--docs-root", default=None)
    ap.add_argument("--version", default=None)
    ap.add_argument("--syntax-json", default="references/syntaxEN.json")
    ap.add_argument("--out", default="out/oop_source_diff.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if args.docs_root:
        docs_root = Path(args.docs_root).resolve()
    else:
        docs_root = resolve_docs_root(repo_root / "mirror" / "docs", args.version)

    syntax_path = repo_root / args.syntax_json
    syntax = oop.load_syntax_json(syntax_path)
    report = reconcile(docs_root, syntax)
    report["docsRoot"] = str(docs_root.relative_to(repo_root))
    report["syntaxJson"] = args.syntax_json
    report["classes"] = len(report["perClass"])

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    counts = report["counts"]
    print(f"docs root:   {docs_root}")
    print(f"syntax json: {syntax_path}")
    print(f"classes:     {report['classes']}")
    for key in ("matched", "inherited_from_superclass", "dynamic_member",
                "syntaxen_missing", "doc_missing"):
        print(f"  {key:<26} {counts[key]}")
    print("  annotations on matched pairs:")
    for key, value in report["annotations"].items():
        print(f"    {key:<24} {value}")
    print(f"  non-member headings ignored: {len(report['nonMemberHeadings'])}")
    print("  accounting:")
    for key, value in report["accounting"].items():
        print(f"    {key:<30} {value}")
    if report["orphanClasses"]:
        for orphan in report["orphanClasses"]:
            print(
                f"    orphan base class {orphan['class']}: "
                f"{orphan['members']} members via {orphan['documentedVia']}"
            )
    print(f"written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stage O0 — enumerate the OOP corpus.

Produces one manifest row per (class, member), joining the two sources:

  * `references/syntaxEN.json`  — the typed spine (signature, params, summary)
  * `mirror/docs/<version>/API/*.html` — the prose enrichment page

Each row carries a content hash over **both** contributing sources, so O1/O3
caching invalidates when either the syntax capture or the docs mirror changes.

Also records the version pinning explicitly: `syntaxEN.json` carries no version
marker of its own, so the manifest states which docs snapshot it is declared to
match, plus its sha1, and `--syntax-json` makes a future capture swappable.

Scope decisions and the source reconciliation that justifies them live in
`pipeline/oop/SCOPE.md` and `out/oop_source_diff.json`. Everything excluded
lands in `skipped[]`; nothing is dropped silently.

Usage:
    python3 pipeline/oop/stage0_manifest.py [--repo-root PATH]
        [--version 21-R3] [--docs-root PATH] [--syntax-json PATH]
        [--syntax-version 21-R3] [--out out/oop_manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.cache import hash_sources  # noqa: E402

import oopcommon as oop  # noqa: E402

# Doc trees deliberately excluded from the OOP corpus. Logged, per SCOPE.md.
EXCLUDED_DOC_TREES = [
    (
        "aikit",
        "4D AIKit is a component, not the base language; it also cannot be "
        "provisioned in the throwaway check project, so its entries could "
        "never be compiler-verified.",
    ),
    (
        "Concepts",
        "Language grammar (class declaration, Function/property keywords, "
        "#DECLARE), not member signatures. Captured as a Layer-2 sub-grammar "
        "where needed for call synthesis.",
    ),
    (
        "ORDA",
        "Narrative guide pages; the ORDA class reference itself lives in "
        "API/ and is in scope.",
    ),
]

EXCLUDED_SYNTAX_KEYS = [
    (
        "_command_",
        "The 1353 classic commands — already covered by out/4d-command-ir.json.",
    ),
]


def member_kind(class_name: str, member_key: str) -> str:
    if class_name == oop.CLASS_STORE_KEY:
        return "oop_constructor"
    return "oop_function" if member_key.endswith(")") else "oop_property"


def member_id(class_name: str, member_key: str) -> str:
    """Receiver-qualified id.

    Constructors are already fully qualified in the class store ("4D.Blob.new").
    Instance/class members are "<Class>.<member>" with the parentheses dropped:
    "Collection.length", "Collection.query".
    """
    bare = member_key[:-2] if member_key.endswith("()") else member_key
    if class_name == oop.CLASS_STORE_KEY:
        return bare
    return f"{class_name}.{bare}"


def build_manifest(docs_root: Path, syntax: dict, syntax_path: Path,
                   declared_syntax_version: str) -> dict:
    # class -> its API page, resolved from each page's own <h1>.
    page_for_class: dict[str, str] = {}
    for page in oop.api_pages(docs_root):
        article = oop.load_api_page(page)
        page_for_class[oop.page_class_name(article)] = f"{oop.API_DIR}/{page.name}"

    entries = []
    skipped = []
    seen_ids: dict[str, str] = {}

    for tree, reason in EXCLUDED_DOC_TREES:
        if (docs_root / tree).is_dir():
            skipped.append({"path": f"{tree}/", "reason": reason})
    for key, reason in EXCLUDED_SYNTAX_KEYS:
        if key in syntax:
            skipped.append({"syntaxKey": key, "reason": reason})

    def add(class_name: str, member_key: str, record: dict, doc_page: str | None,
            declaring_class: str, constructor_target: str | None = None):
        entry_id = member_id(class_name, member_key)
        if entry_id in seen_ids:
            skipped.append(
                {
                    "id": entry_id,
                    "reason": f"duplicate id, first seen for {seen_ids[entry_id]}",
                }
            )
            return
        seen_ids[entry_id] = f"{class_name}.{member_key}"

        sources = [syntax_path]
        if doc_page:
            sources.append(docs_root / doc_page)

        entry = {
            "id": entry_id,
            "class": class_name,
            "declaringClass": declaring_class,
            "memberKey": member_key,
            "memberName": "." + (member_key[:-2] if member_key.endswith("()") else member_key)
            if class_name != oop.CLASS_STORE_KEY
            else ".new",
            "kind": member_kind(class_name, member_key),
            "docPage": doc_page,
            "syntaxLines": len(record.get("Syntax", "").split("<br/>")),
            "hasParamsTable": bool(record.get("Params")),
            "contentHash": hash_sources(sources),
        }
        if constructor_target:
            entry["constructs"] = constructor_target
        entries.append(entry)

    for class_name in oop.oop_class_names(syntax):
        doc_page = page_for_class.get(class_name)
        if doc_page is None:
            # Abstract base documented only through its subclasses (Transporter).
            skipped.append(
                {
                    "class": class_name,
                    "reason": (
                        "no API page of its own; members are documented on its "
                        "subclasses' pages. Kept in scope, enriched from those "
                        "pages via the inheritance edge."
                    ),
                    "inScope": True,
                }
            )
        for member_key, record in oop.class_members(syntax, class_name).items():
            add(class_name, member_key, record, doc_page, class_name)

    # Constructors: documented on the target class's page, not ClassStoreClass.
    for target_class, members in syntax.get(oop.CLASS_STORE_KEY, {}).items():
        if not isinstance(members, dict):
            continue
        doc_page = page_for_class.get(target_class)
        for member_key, record in members.items():
            add(
                oop.CLASS_STORE_KEY,
                f"{oop.CLASS_STORE_KEY}.{target_class}.{member_key}",
                record,
                doc_page,
                oop.CLASS_STORE_KEY,
                constructor_target=target_class,
            )

    # Dynamic pseudo-members: documented, in scope, but with no syntaxEN record.
    for (class_name, member), reason in oop.DYNAMIC_MEMBER_HEADINGS.items():
        entries.append(
            {
                "id": f"{class_name}{member}",
                "class": class_name,
                "declaringClass": class_name,
                "memberKey": member[1:],
                "memberName": member,
                "kind": "oop_property",
                "dynamicMember": True,
                "docPage": page_for_class.get(class_name),
                "syntaxLines": 0,
                "hasParamsTable": False,
                "contentHash": hash_sources(
                    [docs_root / page_for_class[class_name]]
                    if page_for_class.get(class_name)
                    else []
                ),
                "note": reason,
            }
        )

    entries.sort(key=lambda e: e["id"])
    return {"entries": entries, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--docs-root", default=None)
    ap.add_argument("--version", default=None)
    ap.add_argument("--syntax-json", default="references/syntaxEN.json")
    ap.add_argument(
        "--syntax-version",
        default="21-R3",
        help="Docs version the --syntax-json capture is declared to match. "
             "syntaxEN.json carries no version marker of its own, so this "
             "pinning is recorded rather than inferred.",
    )
    ap.add_argument("--out", default="out/oop_manifest.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if args.docs_root:
        docs_root = Path(args.docs_root).resolve()
    else:
        from common.docsroot import resolve_docs_root

        docs_root = resolve_docs_root(repo_root / "mirror" / "docs", args.version)

    syntax_path = repo_root / args.syntax_json
    syntax = oop.load_syntax_json(syntax_path)

    manifest = build_manifest(docs_root, syntax, syntax_path, args.syntax_version)
    manifest["docsRoot"] = str(docs_root.relative_to(repo_root))
    manifest["syntaxSource"] = {
        "path": args.syntax_json,
        "sha1": hashlib.sha1(syntax_path.read_bytes()).hexdigest(),
        "declaredDocsVersion": args.syntax_version,
        "note": (
            "syntaxEN.json carries no version marker. The repository owner "
            "confirmed this capture is from 21-R3, matching mirror/docs/21-R3/. "
            "Swap a future capture in with --syntax-json and update "
            "--syntax-version."
        ),
    }
    if docs_root.name != args.syntax_version:
        manifest["syntaxSource"]["_review"] = (
            f"docs root is {docs_root.name} but the syntax capture is declared "
            f"as {args.syntax_version} — the two sources are not pinned to the "
            f"same version"
        )

    by_kind: dict[str, int] = {}
    for entry in manifest["entries"]:
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
    manifest["counts"] = {
        "inScope": len(manifest["entries"]),
        "byKind": by_kind,
        "dynamicMembers": sum(
            1 for e in manifest["entries"] if e.get("dynamicMember")
        ),
        "classes": len(oop.oop_class_names(syntax)),
        "skipped": len(manifest["skipped"]),
    }

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"docs root:   {docs_root}")
    print(f"syntax json: {syntax_path} (declared {args.syntax_version})")
    print(f"members in scope: {manifest['counts']['inScope']}")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind:<18} {count}")
    print(f"  (of which dynamic: {manifest['counts']['dynamicMembers']})")
    print(f"skipped entries: {manifest['counts']['skipped']}")
    print(f"written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

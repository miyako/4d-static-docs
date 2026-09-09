#!/usr/bin/env python3
"""Stage O4 — build the Layer-2 `classes{}` table and Layer-3 relationships.

Machine-derivable class facts (doc page, superclass, member list, whether a
constructor exists) come from the sources. The one field with no machine-
readable source is `instantiation` — how a caller obtains an instance — which
is stated only in prose, so it is hand-authored in
`pipeline/oop/class_instantiation.json` with a `_reason` citing its evidence
and merged here.

`instantiation` is what example synthesis depends on: without it a generator
knows a member's signature but has no way to produce a receiver to call it on.

Relationships emitted:
    member_of           member -> its class
    returns_instance_of member -> the class of the object it returns
    obtained_via        class  -> the member/command that produces an instance
    (classic_equivalent is emitted separately into out/4d-ir-crosslinks.json)

Usage:
    python3 pipeline/oop/stage4_classes.py [--repo-root PATH]
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

_CLASS_TYPE_RE = re.compile(r"^(?:4D\.|cs\.)?([A-Za-z][A-Za-z0-9]*)$")


def class_of_type(type_name: str | None, known: set[str]) -> str | None:
    """Map a declared return type onto a class id, when it names one."""
    if not type_name:
        return None
    value = type_name.strip()
    if value in ("Collection", "Object", "Text", "Integer", "Real", "Boolean"):
        return value if value in known else None
    match = _CLASS_TYPE_RE.match(value)
    if not match:
        return None
    candidate = match.group(1)
    return candidate if candidate in known else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--syntax-json", default="references/syntaxEN.json")
    ap.add_argument("--manifest", default="out/oop_manifest.json")
    ap.add_argument("--raw", default="out/oop_stage1_raw.json")
    ap.add_argument("--entries-dir", default="out/oop_stage3_ir_full")
    ap.add_argument("--instantiation", default="pipeline/oop/class_instantiation.json")
    ap.add_argument("--out-classes", default="out/oop_classes.json")
    ap.add_argument("--out-relationships", default="out/oop_relationships.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    syntax = oop.load_syntax_json(repo_root / args.syntax_json)
    manifest = json.loads((repo_root / args.manifest).read_text(encoding="utf-8"))
    raw = json.loads((repo_root / args.raw).read_text(encoding="utf-8"))
    authored = json.loads(
        (repo_root / args.instantiation).read_text(encoding="utf-8")
    )
    entries = {}
    for path in sorted((repo_root / args.entries_dir).glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        entries[entry["id"]] = entry

    class_names = list(oop.oop_class_names(syntax)) + [oop.CLASS_STORE_KEY]
    known = set(class_names) | {
        k for k in authored if not k.startswith("_")
    }

    members_by_class: dict[str, list[str]] = {name: [] for name in class_names}
    constructor_of: dict[str, str] = {}
    for record in manifest["entries"]:
        owner = record.get("declaringClass") or record["class"]
        if record["kind"] == "oop_constructor":
            target = record.get("constructs")
            if target:
                constructor_of[target] = record["id"]
                members_by_class.setdefault(target, []).append(record["id"])
                continue
        members_by_class.setdefault(owner, []).append(record["id"])

    classes: dict[str, dict] = {}
    missing_instantiation: list[str] = []

    for name in sorted(known):
        if name.startswith("_"):
            continue
        hand = authored.get(name)
        if hand is None:
            missing_instantiation.append(name)
            continue
        page = raw.get(name)
        record: dict = {
            "id": name,
            "displayName": name,
            "docPage": page["docPage"] if page else None,
            "typeName": hand.get("typeName", name),
            "instantiation": hand["instantiation"],
        }
        superclass = hand.get("superclass") or oop.superclass_of(syntax, name)
        if superclass:
            record["superclass"] = superclass
        for flag in ("isAbstract", "isSingleton", "isStatic"):
            if hand.get(flag):
                record[flag] = True
        if hand.get("isTemplate"):
            template: dict = {}
            if hand.get("templateNote"):
                template["note"] = hand["templateNote"]
            if "<DataClass>" in name:
                template["pattern"] = name.replace("<DataClass>", "<TableName>")
            record["isTemplate"] = template
        if hand.get("sharedSemantics"):
            record["sharedSemantics"] = hand["sharedSemantics"]
        if constructor_of.get(name):
            record["constructor"] = constructor_of[name]
        members = sorted(members_by_class.get(name, []))
        if members:
            record["members"] = members
        note_parts = [hand.get("_reason"), hand.get("templateNote")]
        note = " ".join(p for p in note_parts if p)
        if note:
            record["note"] = note
        classes[name] = record

    relationships: list[dict] = []
    for entry_id, entry in entries.items():
        class_id = entry["receiver"]["classId"]
        if entry["kind"] == "oop_constructor":
            class_id = entry["receiver"]["classId"]
        relationships.append(
            {
                "type": "member_of",
                "from": {"command": entry_id},
                "to": {"classId": class_id},
            }
        )
        return_types = []
        if entry["kind"] == "oop_property":
            return_types.append(entry["accessor"]["type"].get("name"))
        else:
            for overload in entry.get("overloads", []):
                returns = overload.get("returns")
                if returns:
                    return_types.append(returns.get("name"))
        for type_name in {t for t in return_types if t}:
            target = class_of_type(type_name, known)
            if target and target != class_id:
                relationships.append(
                    {
                        "type": "returns_instance_of",
                        "from": {"command": entry_id},
                        "to": {"classId": target},
                    }
                )

    seen = set()
    deduped = []
    for edge in relationships:
        key = (edge["type"], json.dumps(edge["from"], sort_keys=True),
               json.dumps(edge["to"], sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)

    for class_id, record in classes.items():
        for recipe in record["instantiation"]["recipes"]:
            producer = recipe.get("producedBy")
            if not producer:
                continue
            ref = (
                {"command": producer} if producer in entries
                else {"command": producer, "corpus": "classic"}
            )
            deduped.append(
                {
                    "type": "obtained_via",
                    "from": {"classId": class_id},
                    "to": ref,
                    "note": recipe["expression"],
                }
            )

    (repo_root / args.out_classes).write_text(
        json.dumps(classes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (repo_root / args.out_relationships).write_text(
        json.dumps(deduped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    by_type: dict[str, int] = {}
    for edge in deduped:
        by_type[edge["type"]] = by_type.get(edge["type"], 0) + 1
    print(f"classes:        {len(classes)}")
    print(f"  with a constructor: {sum(1 for c in classes.values() if 'constructor' in c)}")
    print(f"  templates:          {sum(1 for c in classes.values() if c.get('isTemplate'))}")
    print(f"  abstract:           {sum(1 for c in classes.values() if c.get('isAbstract'))}")
    print(f"relationships:  {len(deduped)}")
    for kind, count in sorted(by_type.items()):
        print(f"  {kind:20s} {count}")
    if missing_instantiation:
        print(
            "ERROR: no authored instantiation for: "
            + ", ".join(missing_instantiation)
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

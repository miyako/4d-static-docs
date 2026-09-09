#!/usr/bin/env python3
"""Stage O6 — emit `out/4d-ir-crosslinks.json`.

Per decision 1 of the plan the two corpora are separate documents, so edges
that span them live in their own small file rather than inside either IR. Each
edge is a `classic_equivalent` relationship whose endpoints carry an explicit
`corpus` so a consumer knows which document to resolve the id in.

Two sources feed it, both evidence-backed rather than name-guessed:

* the hand-authored instantiation recipes, whose `producedBy` often names a
  classic command (File, Folder, New collection, Session, WEB Server, ...) —
  these are the strongest links, because the classic command is literally how
  you obtain the OOP object;
* an explicit curated table of classic/OOP pairs that do the same job.

Name-similarity matching is deliberately not used: "Collection.copy" and the
classic "COPY ARRAY" are not equivalents, and a heuristic that pairs them
would pollute the file with plausible-looking noise.

Usage:
    python3 pipeline/oop/stage6_crosslinks.py [--repo-root PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (oop id, classic id, note). Curated: each pair is a documented same-job
# equivalence, not a name match.
CURATED_EQUIVALENTS = [
    ("Collection.length", "Size-of-array",
     "Both give the element count; Size of array also resizes, .length is read-only."),
    ("Collection.sort", "SORT-ARRAY",
     "Collection.sort returns a new collection; SORT ARRAY sorts an array in place."),
    ("Collection.push", "APPEND-TO-ARRAY", "Append one element to the end."),
    ("Collection.indices", "Find-in-array", "Locate elements by value."),
    ("Document.getText", "Document-to-text",
     "Read a whole document as text; the OOP form takes the charset and break mode as arguments."),
    ("File.setText", "TEXT-TO-DOCUMENT", "Write text to a document."),
    ("File.delete", "DELETE-DOCUMENT", "Delete a file from disk."),
    ("Document.copyTo", "COPY-DOCUMENT", "Copy a file."),
    ("File.moveTo", "MOVE-DOCUMENT", "Move a file."),
    ("File.open", "Open-document",
     "Open a document; the classic command returns a document reference, .open() returns a 4D.FileHandle."),
    ("Folder.create", "CREATE-FOLDER", "Create a directory on disk."),
    ("Folder.delete", "DELETE-FOLDER", "Delete a directory."),
    ("DataClass.query", "QUERY",
     "ORDA query returns an entity selection; the classic query sets the current selection."),
    ("DataClass.all", "ALL-RECORDS", "Select every record of the table."),
    ("Entity.save", "SAVE-RECORD",
     "ORDA save returns a status object; SAVE RECORD reports through the OK system variable."),
    ("Entity.drop", "DELETE-RECORD", "Delete one record."),
    ("Entity.lock", "LOAD-RECORD",
     "Pessimistic locking; the ORDA form returns a status object describing the lock."),
    ("EntitySelection.length", "Records-in-selection", "Count of the selection."),
    ("EntitySelection.orderBy", "ORDER-BY", "Sort a selection."),
    ("WebServer.start", "WEB-START-SERVER", "Start the web server."),
    ("WebServer.stop", "WEB-STOP-SERVER", "Stop the web server."),
    ("Session.storage", "Session-storage",
     "The shared storage object of the current session."),
    ("Session.info", "Session-info", "Descriptive information about a session."),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--oop-ir", default="out/4d-oop-ir.json")
    ap.add_argument("--classic-ir", default="out/4d-command-ir.json")
    ap.add_argument("--out", default="out/4d-ir-crosslinks.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    oop_ir = json.loads((repo_root / args.oop_ir).read_text(encoding="utf-8"))
    classic_ir = json.loads((repo_root / args.classic_ir).read_text(encoding="utf-8"))

    oop_ids = {entry["id"] for entry in oop_ir["commands"]}
    classic_ids = {entry["id"] for entry in classic_ir["commands"]}
    # Recipes were authored citing the command as it is spelled in the docs
    # ("New collection"), while classic ids are kebab-cased ("New-collection").
    classic_by_display = {
        entry["displayName"]: entry["id"] for entry in classic_ir["commands"]
    }

    edges: list[dict] = []
    unresolved: list[dict] = []

    for oop_id, classic_id, note in CURATED_EQUIVALENTS:
        if oop_id not in oop_ids or classic_id not in classic_ids:
            unresolved.append(
                {
                    "oop": oop_id,
                    "classic": classic_id,
                    "reason": (
                        "oop id not in the OOP IR" if oop_id not in oop_ids
                        else "classic id not in the classic IR"
                    ),
                }
            )
            continue
        edges.append(
            {
                "type": "classic_equivalent",
                "from": {"command": oop_id, "corpus": "oop"},
                "to": {"command": classic_id, "corpus": "classic"},
                "note": note,
            }
        )

    obtained: list[dict] = []
    for class_id, record in oop_ir["classes"].items():
        for recipe in record["instantiation"]["recipes"]:
            producer = recipe.get("producedBy")
            if not producer:
                continue
            if producer in oop_ids:
                # Intra-corpus: already an obtained_via edge inside the OOP IR.
                continue
            target = producer if producer in classic_ids else classic_by_display.get(producer)
            if target is None:
                unresolved.append(
                    {
                        "classId": class_id,
                        "producedBy": producer,
                        "reason": "producedBy names neither a classic command id/displayName nor an OOP member",
                    }
                )
                continue
            obtained.append(
                {
                    "type": "obtained_via",
                    "from": {"classId": class_id, "corpus": "oop"},
                    "to": {"command": target, "corpus": "classic"},
                    "note": recipe["expression"],
                }
            )

    document = {
        "_source": (
            "Cross-corpus edges between out/4d-command-ir.json (classic) and "
            "out/4d-oop-ir.json (OOP). Generated by "
            "pipeline/oop/stage6_crosslinks.py."
        ),
        "_note": (
            "Endpoints carry an explicit `corpus` because the two IRs are "
            "separate documents. classic_equivalent edges are curated, never "
            "inferred from name similarity."
        ),
        "relationships": edges + obtained,
        "unresolved": unresolved,
    }
    out_path = repo_root / args.out
    out_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"classic_equivalent edges: {len(edges)}")
    print(f"obtained_via edges (OOP class <- classic command): {len(obtained)}")
    if unresolved:
        print(f"unresolved: {len(unresolved)}")
        for item in unresolved:
            left = item.get("oop") or item.get("classId")
            right = item.get("classic") or item.get("producedBy")
            print(f"  {left} <-> {right}: {item['reason']}")
    print(f"crosslinks -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

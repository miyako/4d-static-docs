#!/usr/bin/env python3
"""Compiler controls for R5 class spellings and retained semantic corrections."""
from __future__ import annotations

import json
import os
from pathlib import Path

import stage6_synth_examples as synth


def main() -> int:
    if not os.environ.get("TOOL4D_PATH"):
        raise SystemExit("Set TOOL4D_PATH to the matching compiler explicitly.")
    provenance = synth.oop.compiler_provenance()
    cases = [
        ("File", "4D.File", 'File("/PACKAGE/README.md")', True),
        ("QuotaCompilerName", "4D.QuotaManagerClass", "Session.quotas", True),
        ("QuotaDocName", "4D.QuotaManager", "Session.quotas", False),
        ("UnknownControl", "4D.NoSuchQuotaControl", "Session.quotas", False),
        ("FolderConstructor", "4D.Folder", '4D.Folder.new("/PACKAGE"; fk posix path)', True),
        ("FolderStar", "4D.Folder", '4D.Folder.new("/PACKAGE"; fk posix path; *)', False),
        ("FolderShortcut", "4D.Folder", 'Folder("/PACKAGE"; fk posix path; *)', True),
        ("IMAPNoArgs", "4D.IMAPNotifier", "4D.IMAPNotifier.new()", True),
        ("IMAPExtraArgs", "4D.IMAPNotifier", "4D.IMAPNotifier.new(Null; Formula(1))", False),
        ("MultiSortCollection", "Collection", "New collection.multiSort(New collection)", True),
        ("MultiSortInteger", "Collection", "New collection.multiSort(ck ascending)", False),
        ("ZipFileCorrect", "4D.ZipFile", 'ZIP Read archive(File("/PACKAGE/a.zip")).root.files()[0]', True),
        ("ZipFileWrong", "4D.ZipFile", 'ZIP Read archive(File("/PACKAGE/a.zip")).root.file("a")', False),
        ("OrderByScalar", "Collection", "New collection.orderByMethod(Formula(True); 1)", True),
        ("OrderByText", "Collection", 'New collection.orderByMethod(Formula(True); "extra")', True),
        ("OrderByFormula", "Collection", "New collection.orderByMethod(Formula(True); Formula(1))", True),
        ("TCPPortInteger", "4D.TCPConnection", '4D.TCPConnection.new("127.0.0.1"; 10000; New object)', True),
        ("TCPPortReal", "4D.TCPConnection", '4D.TCPConnection.new("127.0.0.1"; 10000.5; New object)', True),
        ("TCPPortText", "4D.TCPConnection", '4D.TCPConnection.new("127.0.0.1"; "not a port"; New object)', True),
        ("TCPPortCollection", "4D.TCPConnection", '4D.TCPConnection.new("127.0.0.1"; New collection; New object)', True),
    ]
    ir = synth.load_json(synth.IR_PATH)
    for class_id, record in ir["classes"].items():
        if class_id in ("4D", "cs") or record.get("isTemplate"):
            continue
        cases.append((f"Class_{class_id}", record["typeName"], None, True))
    paths = []
    try:
        for index, (label, type_name, expression, _) in enumerate(cases):
            path = synth.METHODS_DIR / f"OOPType_{index:02d}_{label[:16]}.4dm"
            text = f"var $receiver : {type_name}\n"
            if expression:
                text += f"$receiver:={expression}\n"
            path.write_text(text)
            paths.append(path)
        diags = synth.diagnostics_by_relpath(synth.run_check_syntax())
        results = []
        for (label, type_name, _, expected), path in zip(cases, paths):
            rel = f"Sources/Methods/{path.name}"
            if rel not in diags:
                raise SystemExit(f"Compiler omitted {rel}; cannot verify type name.")
            diagnostics = diags[rel]
            clean = not diagnostics
            results.append({
                "case": label, "typeName": type_name, "expectedClean": expected,
                "clean": clean, "passed": clean == expected,
                "diagnostics": diagnostics,
                **({"compilerLimitation": "R5 check-syntax accepts this unsuitable port input. Compile acceptance does not validate serverPort semantics."}
                   if label in ("TCPPortText", "TCPPortCollection") else {}),
            })
        report = {
            "tool4dPath": os.environ["TOOL4D_PATH"],
            "compilerProvenance": provenance,
            "cases": results, "passed": all(r["passed"] for r in results),
        }
        (synth.ROOT / "out/oop_type_name_crosscheck.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Join mechanical source flags with authored semantic/compiler dispositions."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


def source(path):
    return {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}


def key(item):
    return item["id"], item["kind"], item.get("param")


def disposition(item):
    kind = item["kind"]
    if kind in {"param_variadic_spelling", "param_case_mismatch", "return_nullable_only_in_table"}:
        return "reviewed_source_convention"
    if kind in {"param_missing_in_table", "param_table_missing"}:
        return "completed_from_signature_and_reviewed_overlay"
    if kind == "type_mismatch" and item["id"] == "Collection.orderByMethod":
        return "reviewed_expression_any_convention"
    if kind == "type_mismatch" and item["id"] == "4D.TCPConnection.new":
        return "resolved_in_ir_integer_port_raw_syntax_preserved"
    raise ValueError(f"New unreviewed parameter conflict: {item}")


def main():
    current = read("out/oop_param_conflicts.json")
    prior = read("references/21-R4-oop-param-conflicts.json")
    before = {key(item): item for item in prior["items"]}
    after = {key(item): item for item in current["items"]}
    mechanical = [
        dict(item, origin="preexisting_r4" if key(item) in before else "new_r5",
             disposition=disposition(item),
             changedSinceR4=key(item) in before and item != before[key(item)])
        for item in current["items"]
    ]
    authored = read("pipeline/reviews/21-R5-conflicts.json")
    oop_review = read("out/oop_refresh_review.json")
    oop_hover = read("out/oop_hover_crosscheck.json")
    semantic = []
    for entry in authored["semanticConflicts"]:
        semantic.append(dict(entry, sources=[source(path) for path in entry["sources"]]))
    report = {
        "version": "21-R5", "status": "BETA", "compilerBuild": "21R5.100156",
        "scope": "All OOP O2b flags and known reviewed cross-command, within-page and compiler contradictions. Mechanical flags are not a count of confirmed documentation bugs; source reconciliation and hover gaps remain separate reports.",
        "provenance": {
            "docs": read("mirror/snapshot.json"),
            "syntax": read("references/syntaxEN-21-R5.provenance.json"),
            "r4Run": {"repository": "miyako/4d-static-docs", "runId": 42352232807, "artifact": "docs-extraction-42352232807-1"},
            "r4Report": source("references/21-R4-oop-param-conflicts.json"),
            "r4Provenance": read("references/21-R4-extraction.provenance.json"),
            "r5Report": source("out/oop_param_conflicts.json"),
        },
        "r4ParameterReport": prior,
        "counts": {
            "r4MechanicalFlags": len(before), "r5MechanicalFlags": len(after),
            "newMechanicalFlags": len(after.keys() - before.keys()),
            "removedMechanicalFlags": len(before.keys() - after.keys()),
            "changedMechanicalFlags": sum(before[k] != after[k] for k in before.keys() & after.keys()),
            "mechanicalByDisposition": dict(Counter(item["disposition"] for item in mechanical)),
            "semanticByDisposition": dict(Counter(item["disposition"] for item in semantic)),
        },
        "mechanicalFlags": mechanical,
        "removedMechanicalFlags": [before[k] for k in sorted(before.keys() - after.keys())],
        "semanticConflicts": semantic,
        "compilerGateLimitations": [
            dict(entry, evidence=[source(path) for path in entry["evidence"]])
            for entry in authored["compilerGateLimitations"]
        ],
        "historicalPipelineDefects": authored["historicalPipelineDefects"],
        "oopReviewedIssues": {
            "source": source("out/oop_refresh_review.json"),
            "distinctReviewedIssues": oop_review["conflictInventory"]["distinctReviewedIssueCount"],
            "note": "17 OOP items include the ten mechanical flags and eight manual findings with one overlap. They are not 17 newly introduced R5 bugs; historical pipeline defects and modeled domain constraints are included.",
            "manualCompilerAndDocumentationIssues": oop_review["conflictInventory"]["manualCompilerAndDocumentationIssues"],
        },
        "oopGateLimitations": {
            "tcpPort": "checkSyntax accepts Integer, Real, Text and Collection port expressions. Retain the documented Integer domain; acceptance cannot prove valid runtime ports.",
            "hover": oop_review["validation"]["G5"],
            "documentationExamples": oop_review["validation"]["docExamples"],
            "note": "Three evidenced hover disagreements, ten index gaps, seven dynamic stand-ins and 230 unverified snippets are explicitly separate from unexplained errors and mechanical conflict counts.",
        },
        "explainedOopHoverDiscrepancies": {
            "compilerProvenance": oop_hover["compilerProvenance"],
            "probes": source("out/oop_type_name_crosscheck.json"),
            "items": [entry for entry in oop_hover["results"]
                      if entry["status"] == "explained-disagreement"],
        },
        "oopFullProjectCompilerEvidence": {
            "provenance": read("out/oop_project_compiler_provenance.json"),
            "report": source("out/oop_project_compiler_report.json"),
            "note": "The earlier G4 report retained target diagnostics only. A supplemental fresh R5 pass retains all 530 files, including both callback helpers; zero diagnostics.",
        },
        "relatedReports": [
            "out/oop_source_diff.json", "out/oop_param_conflicts.json",
            "out/oop_hover_crosscheck.json", "out/classic_hover_crosscheck.json",
            "out/classic_r5_review.json",
            "out/classic_r5_controls.json", "out/classic_compiler_provenance.json",
        ],
    }
    (ROOT / "out/r5_conflict_inventory.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compare a preserved OOP baseline with current sources, without page-hash noise."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text())


def sections(raw):
    return {
        (class_id, section["headingKey"]): section
        for class_id, page in raw.items() for section in page["sections"]
    }


def conflict_inventory(current, previous):
    def key(item):
        return (item["id"], item["kind"], item.get("param", ""))

    decisions = {
        ("Collection.average", "return_nullable_only_in_table", ""):
            ("nullable_return_enriched", "Retain Real return and set returnsNullable=true from the documented undefined result."),
        ("Collection.concat", "param_variadic_spelling", "valueN"):
            ("source_spelling_retained", "The table's value denotes the variadic valueN tail; retain syntax spelling and cardinality."),
        ("Collection.extract", "param_case_mismatch", "targetPath"):
            ("case_normalized", "Case-insensitive table join; retain the syntax name targetPath."),
        ("Collection.extract", "param_missing_in_table", "propertyPathOrTargetPathN"):
            ("documented_variadic_tail_preserved", "Retain the declared optional repeating Text tail (minimum zero); the table describes propertyPath/targetpath instead of naming the composite tail."),
        ("Collection.orderByMethod", "type_mismatch", "extraParam"):
            ("pseudo_type_convention_retained", "Expression is an expression-value pseudo-type, not a concrete Function restriction. R5 accepts Integer, Text and Formula extra arguments; this is consistent with the table's any type. Preserve raw/source pseudo-type."),
        ("Collection.push", "param_variadic_spelling", "elementN"):
            ("source_spelling_retained", "The table's element denotes the variadic elementN tail; retain syntax spelling and cardinality."),
        ("Collection.unshift", "param_variadic_spelling", "valueN"):
            ("source_spelling_retained", "The table's value denotes the variadic valueN tail; retain syntax spelling and cardinality."),
        ("4D.File.new", "param_table_missing", ""):
            ("constant_enums_supplied_by_overlay", "No constructor parameter table; use documented classic File shortcut constant domains via the evidenced overlay. All enum variants compile."),
        ("4D.Folder.new", "param_table_missing", ""):
            ("constant_enums_supplied_by_overlay", "No constructor parameter table; use documented classic Folder shortcut constant domains via the evidenced overlay. Separately remove the compiler-rejected constructor star."),
        ("4D.TCPConnection.new", "type_mismatch", "serverPort"):
            ("documented_integer_domain_selected", "Retain the Integer overlay from the parameter table and verbatim Number rawSyntax. R5 accepts Integer, Real, Text and Collection port expressions, so static checking cannot arbitrate the numeric domain or validate runtime port suitability."),
    }
    before = {key(i): i for i in previous["items"]}
    after = {key(i): i for i in current["items"]}
    missing = set(after) - set(decisions)
    if missing:
        raise SystemExit(f"Unreviewed OOP conflicts: {sorted(missing)}")
    items = [
        {**item, "reviewDisposition": decisions[key(item)][0],
         "reviewReason": decisions[key(item)][1],
         "compilerEvidence": "out/oop_lsp_crosscheck_report.json",
         **({"targetedControls": "out/oop_type_name_crosscheck.json"}
            if item["id"] in ("Collection.orderByMethod", "4D.TCPConnection.new") else {})}
        for item in current["items"]
    ]
    manual = [
        {"issue": "folder_constructor_star", "members": ["4D.Folder.new"],
         "disposition": "Remove semantic star; preserve raw syntax. Constructor star fails, corresponding classic Folder shortcut star passes.",
         "evidence": "pipeline/oop/semantic_overlays/4D.Folder.new.json"},
        {"issue": "tcp_server_port_type", "members": ["4D.TCPConnection.new"],
         "overlapsMechanicalFlag": True, "disposition": decisions[("4D.TCPConnection.new", "type_mismatch", "serverPort")][1],
         "evidence": "pipeline/oop/semantic_overlays/4D.TCPConnection.new.json"},
        {"issue": "collection_multisort_enum", "members": ["Collection.multiSort"],
         "disposition": "Retype colsToSort as Collection, not ck ascending/descending enum; Collection passes and integer constant fails.",
         "evidence": "pipeline/oop/semantic_overlays/Collection.multiSort.json"},
        {"issue": "imap_notifier_receiver_recipe", "classes": ["IMAPNotifier"],
         "disposition": "Use zero-argument new(); previous two-argument receiver recipe produces too-many-parameters error.",
         "evidence": "pipeline/oop/class_instantiation.json"},
        {"issue": "zipfile_receiver_recipe", "classes": ["ZipFile"],
         "disposition": "Use archive.root.files()[0]; root.file() returns 4D.File and fails a 4D.ZipFile cast.",
         "evidence": "pipeline/oop/class_instantiation.json"},
        {"issue": "quota_type_spelling", "members": ["Session.quotas", "WebServer.quotas"], "classes": ["QuotaManagerClass"],
         "disposition": "Compiler requires 4D.QuotaManagerClass; documented/hover 4D.QuotaManager is unknown. Correct semantic type and recipe, preserve raw syntax.",
         "evidence": "out/oop_type_name_crosscheck.json"},
        {"issue": "webserver_quota_object_assignability", "members": ["WebServer.quotas"],
         "disposition": "Quota object is not directly assignable according to class documentation; modify existing quota properties. Mark accessor read-only.",
         "evidence": "pipeline/oop/semantic_overlays/WebServer.quotas.json"},
        {"issue": "vector_immutable_properties", "members": ["Vector.length", "Vector.precision"],
         "disposition": "Apply documented immutable class contract to both property accessors; static compile success does not establish runtime writability.",
         "evidence": ["pipeline/oop/semantic_overlays/Vector.length.json", "pipeline/oop/semantic_overlays/Vector.precision.json"]},
    ]
    return {
        "mechanicalFlagCount": current["conflicts"],
        "mechanicalAffectedMembers": len({i["id"] for i in current["items"]}),
        "byKind": current["byKind"],
        "items": items,
        "r4Comparison": {
            "baselineVersion": "21-R4", "r4MembersChecked": previous["membersChecked"],
            "r5MembersChecked": current["membersChecked"],
            "r4FlagCount": previous["conflicts"], "r5FlagCount": current["conflicts"],
            "r4ByKind": previous["byKind"],
            "addedFlags": [after[k] for k in sorted(set(after) - set(before))],
            "removedFlags": [before[k] for k in sorted(set(before) - set(after))],
            "changedFlags": [{"before": before[k], "after": after[k]} for k in sorted(set(before) & set(after)) if before[k] != after[k]],
            "note": "Fresh R4 OOP-only extraction/signature cross-check; no classic artifacts read and no R4 compiler verification claimed.",
        },
        "manualCompilerAndDocumentationIssues": manual,
        "manualIssueCount": len(manual),
        "overlapWithMechanicalFlags": 1,
        "distinctReviewedIssueCount": current["conflicts"] + len(manual) - 1,
        "reviewStatus": "All flags and manual issues have explicit dispositions; no synthetic diagnostic suppressed. Static TCP argument acceptance is an evidenced compiler limitation, not proof of valid port inputs.",
        "excludedFromConflictCount": "Ten multivariant hover index gaps, seven dynamic stand-ins and 230 unverified documentation snippets are limitations/examples, not additional mechanical IR conflicts.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="extraction/oop-baseline")
    parser.add_argument("--out", default="out/oop_refresh_review.json")
    args = parser.parse_args()
    baseline = Path(args.baseline)
    old_manifest = read(baseline / "oop_manifest.json")
    manifest = read(Path("out/oop_manifest.json"))
    old_ir = read(baseline / "4d-oop-ir.json")
    ir = read(Path("out/4d-oop-ir.json"))
    old_members = {e["id"]: e for e in old_ir["commands"]}
    members = {e["id"]: e for e in ir["commands"]}
    r4_signature_path = Path("extraction/oop-r4-conflict-comparison/signatures.json")
    r4_members = set(read(r4_signature_path))
    added_members = set(members) - set(old_members)
    introduced_in_stable_r4 = sorted(added_members & r4_members)
    new_in_r5 = sorted(added_members - r4_members)
    old_sections = sections(read(baseline / "oop_stage1_raw.json"))
    new_sections = sections(read(Path("out/oop_stage1_raw.json")))
    fields = (
        "summary", "descriptionBlocks", "syntaxLines", "paramTable",
        "history", "returnsShapeTables", "examples", "subsections",
    )
    changed_sections = [
        {"class": key[0], "memberHeading": key[1], "changedFields": changed}
        for key in sorted(old_sections.keys() & new_sections.keys())
        if (changed := [f for f in fields if old_sections[key].get(f) != new_sections[key].get(f)])
    ]
    def source(entry):
        if entry["kind"] == "oop_property":
            return entry["accessor"].get("rawSyntax")
        return "<br/>".join(o.get("rawSyntax") or "" for o in entry.get("overloads", []))

    changed_signatures = [
        {"id": member_id, "before": source(old_members[member_id]),
         "after": source(members[member_id])}
        for member_id in sorted(old_members.keys() & members.keys())
        if source(old_members[member_id]) != source(members[member_id])
    ]
    capture_path = Path("references/syntaxEN-21-R5.provenance.json")
    capture = read(capture_path)
    if capture["sha256"] != manifest["syntaxSource"]["sha256"]:
        raise SystemExit("Capture provenance and OOP manifest hashes disagree.")
    registry_path = Path("references/4d-constants-registry.json")
    registry = read(registry_path)
    roundtrip = read(Path("out/oop_roundtrip_report.json"))
    coverage = read(Path("out/oop_coverage_report.json"))
    synth_manifest = read(Path("out/oop_synth_manifest.json"))
    compiler = read(Path("out/oop_lsp_crosscheck_report.json"))
    hover = read(Path("out/oop_hover_crosscheck.json"))
    controls = read(Path("out/oop_type_name_crosscheck.json"))
    examples = read(Path("out/oop_doc_examples.json"))
    stats = read(Path("out/oop_corpus_stats.json"))
    assembly_delta = read(Path("out/oop_diff_report.json"))
    conflicts = conflict_inventory(
        read(Path("out/oop_param_conflicts.json")),
        read(Path("extraction/oop-r4-conflict-comparison/conflicts.json")),
    )
    conflicts["r4Comparison"]["docsRoot"] = "mirror/docs/21-R4"
    conflicts["r4Comparison"]["syntaxSource"] = {
        "path": "references/syntaxEN-21-R4.json",
        "sha256": hashlib.sha256(Path("references/syntaxEN-21-R4.json").read_bytes()).hexdigest(),
    }
    schema_validation = {"documents": {}, "engines": ["jsonschema"]}
    import jsonschema

    schema_path = Path("references/4d-command-ir-schema.json")
    validator = jsonschema.Draft202012Validator(read(schema_path))
    boon = Path("tools/4dform/boon")
    if boon.is_file():
        schema_validation["engines"].append(str(boon))
    for path in ("out/4d-oop-ir.json", "references/4d-oop-ir-examples.json"):
        validator.validate(read(Path(path)))
        if boon.is_file():
            proc = subprocess.run([str(boon), "-q", str(schema_path), path],
                                  capture_output=True, text=True)
            if proc.returncode:
                raise SystemExit(f"boon validation failed for {path}: {proc.stdout} {proc.stderr}")
        schema_validation["documents"][path] = "valid"
    from check_schema_gate import syntax_sources, verbatim_syntax_violations

    source_violations = verbatim_syntax_violations(
        ir, syntax_sources(Path.cwd(), Path.cwd() / manifest["syntaxSource"]["path"])
    )
    if source_violations:
        raise SystemExit(f"Current OOP source invariant failed: {source_violations}")
    current_ir_hash = hashlib.sha256(Path("out/4d-oop-ir.json").read_bytes()).hexdigest()
    current_manifest_hash = hashlib.sha256(Path("out/oop_manifest.json").read_bytes()).hexdigest()
    provenance_records = [
        synth_manifest["compilerVerification"],
        hover["compilerProvenance"],
        examples["compilerVerification"]["compilerProvenance"],
        controls["compilerProvenance"],
    ]
    for provenance in provenance_records:
        if (provenance["assembledIRSha256"] != current_ir_hash
                or provenance["sourceManifestSha256"] != current_manifest_hash):
            raise SystemExit("A compiler verdict was produced against different OOP IR/manifest inputs.")
    for rel, info in synth_manifest["files"].items():
        if info["sourceSha256"] != hashlib.sha256((Path("oopcheck/Project") / rel).read_bytes()).hexdigest():
            raise SystemExit(f"A final method differs from its compiled manifest: {rel}")
    artifact_paths = (
        [Path("out/4d-oop-ir.json")]
        + sorted(p for p in Path("out").glob("oop*.json") if p.resolve() != Path(args.out).resolve())
        + sorted(Path("out/oop_stage3_ir_full").glob("*.json"))
    )
    crosslink_path = Path("out/4d-ir-crosslinks.json")
    crosslink_validation = None
    if crosslink_path.is_file():
        artifact_paths.append(crosslink_path)
        crosslinks = read(crosslink_path)
        crosslink_validation = {
            "path": str(crosslink_path),
            "relationships": len(crosslinks["relationships"]),
            "unresolved": len(crosslinks["unresolved"]),
        }
    source_paths = (
        [Path(manifest["syntaxSource"]["path"]), capture_path, registry_path]
        + [Path(record["path"]) for record in capture["constants"]]
        + sorted((Path(manifest["docsRoot"]) / "API").glob("*.html"))
        + [schema_path]
        + sorted(p for p in Path("pipeline/oop").rglob("*") if p.is_file() and p.suffix in (".py", ".json"))
    )
    validation = {
        "schemaValidation": schema_validation,
        "verbatimSourceInvariant": {"passed": True, "members": sum(not m.get("dynamicMember") for m in members.values())},
        "G1": {"passed": roundtrip["passed"], "members": roundtrip["members"],
               "lines": roundtrip["overloadLines"], "roundTripped": roundtrip["roundTripped"]},
        "G3": {"passed": coverage["passed"], "inScope": coverage["inScope"],
               "present": coverage["present"], "scopeExclusions": len(coverage["skippedWithReason"])},
        "G4": {"passed": all(r["status"] == "clean" for r in compiler)
                      and {r["id"] for r in compiler} == set(members),
               "members": len({r["id"] for r in compiler}), "blocks": len(compiler),
               "allTargetFilesPresent": synth_manifest["compilerVerification"]["allTargetFilesPresent"],
               "compilerProvenance": synth_manifest["compilerVerification"]},
        "G5": {**hover["summary"], "compilerProvenance": hover["compilerProvenance"]},
        "classAndSemanticControls": {"passed": controls["passed"], "cases": len(controls["cases"]),
                                    "evidence": "out/oop_type_name_crosscheck.json"},
        "docExamples": examples["compilerVerification"],
        "exampleCoverage": stats["exampleCoverage"],
        "classicDependentGates": "G2 previously passed; final combined schema/collision/parity gates belong to the parent. Crosslinks are recorded when present; this review does not read the classic IR.",
    }
    if crosslink_validation is not None:
        validation["crosslinks"] = crosslink_validation
    report = {
        "verificationScope": {
            "G4AndDocCompilerVerified": "Actual tool4d LSP experimental/checkSyntax diagnostics for the generated methods or literal snippets checked; not runtime semantics, a full-application compile, or an exhaustive arity guarantee.",
            "G5": "Fresh tool4d LSP hover-index responses; documentation strings can disagree with static diagnostics, and absence from the index is recorded explicitly.",
        },
        "finalArtifactSha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact_paths
        },
        "sourceFileSha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths
        },
        "finalMethodBinding": {
            "manifest": "out/oop_synth_manifest.json",
            "manifestSha256": hashlib.sha256(Path("out/oop_synth_manifest.json").read_bytes()).hexdigest(),
            "methods": len(synth_manifest["files"]),
            "everyMethodMatchesCompiledSourceHash": True,
            "note": "Individual method SHA256s live in the bound manifest. This review excludes its own hash to avoid circular hashing; the parent snapshot records it externally.",
        },
        "baselineDocsRoot": old_manifest["docsRoot"],
        "docsRoot": manifest["docsRoot"],
        "docsVersionBadge": manifest["docsVersionBadge"],
        "syntaxSource": manifest["syntaxSource"],
        "captureProvenance": {"path": str(capture_path), "record": capture},
        "constantsRegistry": {
            "path": str(registry_path),
            "sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "themes": len(registry["themes"]),
            "entries": sum(len(entries) for entries in registry["byName"].values()),
            "uniqueNames": len(registry["byName"]),
            "sourceResources": capture["constants"],
            "lastAssemblyDelta": {key: len(assembly_delta[key]) for key in ("added", "removed", "changed")},
            "note": "O3/O4/O5 rerun after the shared R5 registry refresh. Official selector 135 remains QUIC Connection Timeout; documentation terminology is not substituted for the source symbol.",
        },
        "compilerProvenance": controls["compilerProvenance"],
        "assembledIRSha256": hashlib.sha256(Path("out/4d-oop-ir.json").read_bytes()).hexdigest(),
        "validation": validation,
        "conflictInventory": conflicts,
        "counts": {"before": len(old_members), "after": len(members),
                   "builtInClasses": manifest["counts"]["classes"],
                   "classRecords": len(ir["classes"]),
                   "introducedInStableR4": len(introduced_in_stable_r4),
                   "newInR5": len(new_in_r5)},
        "added": sorted(members.keys() - old_members.keys()),
        "introducedInStableR4": introduced_in_stable_r4,
        "newInR5": new_in_r5,
        "additionVersionEvidence": {
            "r4DocsRoot": "mirror/docs/21-R4",
            "r4SyntaxSource": conflicts["r4Comparison"]["syntaxSource"],
            "r4SignaturesSha256": hashlib.sha256(r4_signature_path.read_bytes()).hexdigest(),
            "r4FixedMembers": len(r4_members),
            "r5FixedMembers": roundtrip["members"],
            "method": "Partition the 26 additions versus R3 by presence in the freshly extracted R4 typed signatures. QuotaManager class History and Session.quotas record R4 introduction; Web server quota support and the other new APIs are R5. Individual quota-property sinceVersion fields are not inferred or altered.",
        },
        "removed": sorted(old_members.keys() - members.keys()),
        "addedClassRecords": sorted(ir["classes"].keys() - old_ir["classes"].keys()),
        "changedSignatures": changed_signatures,
        "changedExtractedSections": changed_sections,
        "review": {
            "signatureChanges": {
                "4D.Vector.new": "R5 adds optional precision: 32/64 (mk single/double precision); enum sweep covers both.",
                "Session.setPrivileges": "Collection overload now explicitly returns Boolean; documentation correction, not a new API.",
            },
            "substantiveExistingMembers": {
                "Session.info": "R4 adds unreachableSince to the returned shape and explicitly marks info read-only.",
                "WebServer.start": "R5 accepts quotas in settings; refreshed example and history retained.",
            },
            "examples": ["Collection.filter", "Collection.reduce", "Collection.reduceRight", "4D.Vector.new", "WebServer.start"],
            "cosmeticChanges": ["4D.classStoreName: exposed vs published", "CryptoKey.pem: leading article",
                                "DataClass.query: punctuation", "IMAPTransporter.addFlags: duplicate See also heading"],
            "quotaClass": "QuotaManagerClass is genuinely added versus R3 (class introduced R4, Web server support R5); all 19 properties included. Do not infer individual property introduction dates from class history.",
            "overlays": "All eight reviewed against R5 sources. Four prior overlays retained; Folder star, multiSort type, IMAPNotifier recipe and ZipFile recipe re-probed with positive/negative controls. Two quota overlays correct compiler type spelling; WebServer.quotas is not assignable as an object. Two Vector overlays apply the documented immutable class contract to length and precision.",
            "sharedConstantsRefresh": "Parent reports seven additions and no removals/value changes: Border Custom/System Rounded, three Vector index constants, MCP server enabled/MCP 2 server enabled. Updated shared registry has 92 themes and 2499 entries; OOP assembly remains byte-equivalent.",
            "limitations": "Compiler checks are static, not network/REST/runtime tests. No diagnostic suppressed. Doc snippets depending on unspecified models/classes remain verbatim and unverified. Hover lacks ten multivariant-property entries and repeats three evidenced documentation errors.",
        },
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(f"+{len(report['added'])} -{len(report['removed'])}; "
          f"{len(changed_signatures)} signatures, {len(changed_sections)} extracted sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Record a beta snapshot only after its source-bound verification gates pass."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from common.docsroot import docs_version_info

ROOT = Path(__file__).resolve().parents[1]
BUILD = "21 R5 build 21R5.100156"
DOCS_COMMIT = "78952faa7ceba81909b6b757a76108afa76f8993"


def read(path):
    return json.loads((ROOT / path).read_text())


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regression_evidence():
    checks = []
    for directory in ("pipeline/tests", "pipeline/oop/tests", "scripts/static_docs/tests"):
        command = [sys.executable, "-m", "unittest", "discover", "-s", directory]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        require(result.returncode == 0, f"Regression failure: {command}\n{result.stdout}\n{result.stderr}")
        match = re.search(r"Ran (\d+) tests?", result.stderr)
        require(match is not None, f"Missing unittest result: {result.stderr}")
        checks.append({"command": command, "tests": int(match.group(1)), "passed": True})
    command = [str(ROOT / "tools/4dform/boon"), "references/4d-command-ir-schema.json",
               "out/4d-command-ir.json", "out/4d-oop-ir.json",
               "references/4d-command-ir-examples.json", "references/4d-oop-ir-examples.json"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    require(result.returncode == 0, f"Schema failure:\n{result.stdout}\n{result.stderr}")
    return {"tests": checks, "schema": {"command": command, "passed": True,
                                     "validatorSha256": digest("tools/4dform/boon")},
            "python": sys.version,
            "dependencies": {name: importlib.metadata.version(name)
                             for name in ("beautifulsoup4", "lxml", "jsonschema")}}


def classic_evidence():
    provenance = read("out/classic_compiler_provenance.json")
    require(provenance["compilerVersion"] == BUILD and provenance["fullRun"],
            "Classic evidence is not a full run of the pinned R5 compiler")
    require(provenance["compilerSha256"] == digest(provenance["compilerPath"]),
            "Classic compiler binary changed")
    require(provenance["bridgeSha256"] == digest("tools/4dlsp/tool4d-lsp-stdio"),
            "Compiler bridge binary changed")
    for key, path in (("irSha256", "out/4d-command-ir.json"),
                      ("manifestSha256", "out/synth_manifest.json"),
                      ("reportSha256", "out/lsp_crosscheck_report.json")):
        require(provenance[key] == digest(path), f"Stale classic {path}")
    for path, expected in provenance["sourceSha256"].items():
        require(digest("Project/" + path) == expected, f"Stale classic method {path}")
    manifest = read("out/synth_manifest.json")
    files = set(manifest["files"])
    ids = {entry["command_id"] for entry in manifest["files"].values()}
    ir = read("out/4d-command-ir.json")
    require(ids == {entry["id"] for entry in ir["commands"] if entry["theme"] != "4D-View-Pro"},
            "Classic synthesis omitted non-View-Pro commands")
    require(files == set(provenance["sourceSha256"]), "Classic compiler source coverage differs")
    require(provenance["targetedFiles"] == provenance["returnedFiles"] == len(files),
            "Classic compiler omitted files or checked extra temporary methods")
    verdicts = read("out/lsp_crosscheck_report.json")
    expected = Counter((entry["command_id"], block["overload_index"], block.get("variant", "default"))
                       for entry in manifest["files"].values() for block in entry["overloads"])
    actual = Counter((entry["id"], entry["overload_index"], entry.get("variant", "default")) for entry in verdicts)
    require(actual == expected, "Classic verdict block coverage differs")
    require(all(entry["status"] == "clean" and not entry["diagnostics"] for entry in verdicts),
            "Classic compiler has diagnostics")
    hover = read("out/classic_hover_crosscheck.json")
    require(hover["counts"]["unrecognized"] == 0, "Classic has unexpected hover gaps")
    require({entry["id"] for entry in hover["commands"]} ==
            {entry["command_id"] for entry in manifest["files"].values()}, "Classic hover coverage differs")
    for entry in hover["commands"]:
        require(entry["sourceSha256"] == digest(entry["file"]), f"Stale classic hover {entry['id']}")
    controls = read("out/classic_r5_controls.json")
    require(controls["compilerVersion"] == BUILD, "Controls used a different compiler")
    require(controls["compilerSha256"] == provenance["compilerSha256"], "Controls compiler hash differs")
    required = [entry for entry in controls["controls"] if "expectsError" in entry]
    require({entry["method"] for entry in required} == {"R5VectorIndexProbe", "R5UnknownNegative"},
            "Classic required controls are missing")
    require(all(entry["passed"] for entry in required),
            "Classic required controls failed")
    return {"commands": len(ir["commands"]), "methods": len(files), "blocks": len(verdicts), "hover": hover["counts"],
            "compiler": provenance, "controls": controls}


def oop_evidence():
    review = read("out/oop_refresh_review.json")
    stable, beta = set(review["introducedInStableR4"]), set(review["newInR5"])
    require(not stable & beta and stable | beta == set(review["added"]),
            "OOP release-history partition differs from reviewed additions")
    for key in ("finalArtifactSha256", "sourceFileSha256"):
        for path, expected in review[key].items():
            require(digest(path) == expected, f"Stale OOP evidence: {path}")
    ir = read("out/4d-oop-ir.json")
    ids = {entry["id"] for entry in ir["commands"]}
    manifest = read("out/oop_synth_manifest.json")
    require(ids == {entry["member_id"] for entry in manifest["files"].values()},
            "OOP synthesis coverage differs from IR")
    provenance = manifest["compilerVerification"]
    require(provenance["tool4dBuild"] == BUILD and provenance["allTargetFilesPresent"],
            "OOP compiler is unpinned or omitted targets")
    require(provenance["assembledIRSha256"] == digest("out/4d-oop-ir.json") and
            provenance["sourceManifestSha256"] == digest("out/oop_manifest.json"),
            "OOP compiler inputs are stale")
    require(provenance["compilerSyntaxSha256"] == digest("references/syntaxEN-21-R5.json"),
            "OOP compiler syntax differs from official capture")
    require(provenance["reportSha256"] == digest("out/oop_lsp_crosscheck_report.json"),
            "OOP compiler report changed")
    for path, entry in manifest["files"].items():
        require(entry["sourceSha256"] == digest("oopcheck/Project/" + path),
                f"OOP compiled method changed: {path}")
    verdicts = read("out/oop_lsp_crosscheck_report.json")
    expected = Counter((entry["member_id"], block["overload_index"], block["variant"])
                       for entry in manifest["files"].values() for block in entry["blocks"])
    actual = Counter((entry["id"], entry["overload_index"], entry["variant"]) for entry in verdicts)
    require(expected == actual and all(entry["status"] == "clean" and not entry["diagnostics"]
                                      for entry in verdicts), "OOP compiler blocks differ or have diagnostics")
    hover = read("out/oop_hover_crosscheck.json")
    require(ids == {entry["id"] for entry in hover["results"]} and len(hover["results"]) == len(ids),
            "OOP hover member coverage differs")
    require(all(hover["summary"][key] == 0 for key in
                ("disagreements", "unknownToCompiler", "noCallSite")), "OOP has unexplained hover failures")
    require(hover["compilerProvenance"]["tool4dBuild"] == BUILD and
            hover["compilerProvenance"]["assembledIRSha256"] == digest("out/4d-oop-ir.json"),
            "OOP hover used stale inputs")
    docs = read("out/oop_doc_examples.json")
    require(docs["compilerVerification"]["compilerProvenance"]["tool4dBuild"] == BUILD and
            docs["compilerVerification"]["compilerProvenance"]["assembledIRSha256"] ==
            digest("out/4d-oop-ir.json"), "Documentation verdicts are not fresh R5 evidence")
    checked = [entry for entry in docs["examples"] + docs["unattributed"] if "compilerVerification" in entry]
    buckets = docs["compilerVerification"]["buckets"]
    require(len(checked) == docs["compilerVerification"]["blocksVerified"] == sum(buckets.values()),
            "OOP documentation check counts differ")
    controls = read("out/oop_type_name_crosscheck.json")
    require(controls["passed"] and controls["compilerProvenance"]["tool4dBuild"] == BUILD,
            "OOP semantic controls failed or used another compiler")
    project = read("out/oop_project_compiler_provenance.json")
    require(project["compilerVersion"] == BUILD and project["diagnosticCount"] == 0,
            "Full OOP project compiler gate failed or is unpinned")
    for key, path in (("irSha256", "out/4d-oop-ir.json"),
                      ("manifestSha256", "out/oop_synth_manifest.json"),
                      ("reportSha256", "out/oop_project_compiler_report.json")):
        require(project[key] == digest(path), f"Stale full OOP project {path}")
    for path, expected_hash in project["sourceSha256"].items():
        require(digest(path) == expected_hash, f"Stale full OOP project method {path}")
    require(project["returnedFiles"] == len(project["sourceSha256"]) ==
            len(manifest["files"]) + len(project["helpers"]), "Full OOP project coverage differs")
    require(all(not entry["diagnostics"] for entry in read("out/oop_project_compiler_report.json")),
            "OOP helper/project diagnostics must not be suppressed")
    for gate in ("G1", "G3", "G4", "classAndSemanticControls", "verbatimSourceInvariant"):
        require(review["validation"][gate]["passed"], f"OOP gate {gate} failed")
    stats = read("out/oop_corpus_stats.json")
    require(stats["corpus"]["members"] == len(ids) and
            stats["exampleCoverage"]["neither"] == 0, "OOP statistics or example coverage differ")
    require(stats["corpus"]["classes"] == len(ir["classes"]) and
            stats["corpus"]["enums"] == len(ir["enums"]), "OOP registry statistics differ")
    return {"members": len(ids), "methods": len(manifest["files"]), "blocks": len(verdicts),
            "classes": stats["corpus"]["classes"], "enums": stats["corpus"]["enums"],
            "hover": hover["summary"], "documentationExamples": docs["compilerVerification"],
            "hoverDiscrepancies": [entry for entry in hover["results"]
                                  if entry["status"] == "explained-disagreement"],
            "semanticControlsSha256": digest("out/oop_type_name_crosscheck.json"),
            "compilerBinarySha256": digest(provenance["tool4dPath"]),
            "bridgeSha256": digest("tools/4dlsp/tool4d-lsp-stdio"),
            "fullProjectCompiler": project,
            "introducedInStableR4": review["introducedInStableR4"],
            "newInR5": review["newInR5"],
            "compiler": provenance, "reviewArtifact": "out/oop_refresh_review.json"}


def main():
    version = docs_version_info(ROOT / "mirror/docs")
    require(version["version"] == "21-R5" and version["status"] == "BETA", "Docs are not R5 BETA")
    require(read("mirror/snapshot.json")["sourceCommit"] == DOCS_COMMIT, "Docs snapshot commit changed")
    resources = read("references/syntaxEN-21-R5.provenance.json")
    require(resources["bundleVersion"] == BUILD and resources["status"] == "BETA",
            "Official capture is not the pinned R5 BETA build")
    for entry in [resources, *resources["constants"]]:
        require(digest(entry["path"]) == entry["sha256"], f"Official resource changed: {entry['path']}")
        require(entry["transformation"] == "none", "Official resource was transformed")
    require(digest("references/syntaxEN-21-R4.json") ==
            "be7f09b297e82d810e12e4e83bdf41c775b6a20e4b8a5a71b6ba9202b5d718c6",
            "Stable R4 capture changed")
    classic = classic_evidence()
    oop = oop_evidence()
    classic_ids = {entry["id"] for entry in read("out/4d-command-ir.json")["commands"]}
    oop_ids = {entry["id"] for entry in read("out/4d-oop-ir.json")["commands"]}
    require(not classic_ids & oop_ids, "Classic/OOP member identifiers collide")
    classic_ir, oop_ir = read("out/4d-command-ir.json"), read("out/4d-oop-ir.json")
    for key in ("enums", "classes"):
        shared = classic_ir.get(key, {}).keys() & oop_ir.get(key, {}).keys()
        require(all(classic_ir[key][name] == oop_ir[key][name] for name in shared),
                f"Classic/OOP {key} definitions collide")
    for ir in (classic_ir, oop_ir):
        for entry in ir["commands"]:
            require((ROOT / entry["docPageLocal"].split("#", 1)[0]).is_file(),
                    f"Missing local documentation source: {entry['id']}")
    crosslinks = read("out/4d-ir-crosslinks.json")
    require(not crosslinks["unresolved"], "Crosslinks have unresolved endpoints")
    for edge in crosslinks["relationships"]:
        for endpoint in (edge["from"], edge["to"]):
            if "command" in endpoint:
                domain = {"classic": classic_ids, "oop": oop_ids}[endpoint["corpus"]]
                identifier = endpoint["command"]
            else:
                domain = {"classic": classic_ir.get("classes", {}), "oop": oop_ir["classes"]}[endpoint["corpus"]]
                identifier = endpoint["classId"]
            require(identifier in domain, f"Crosslink endpoint missing: {endpoint}")
    artifacts = [
        "mirror/snapshot.json", "references/syntaxEN-21-R5.provenance.json",
        "references/syntaxEN-21-R5.json", "references/21-R5/4D_ConstantsEN.xlf",
        "references/21-R5/4D_ConstantsThemesEN.xlf", "references/4d-constants-registry.json",
        "references/4d-command-ir-schema.json", "references/4d-command-ir-examples.json",
        "references/4d-oop-ir-examples.json",
        "out/4d-command-ir.json", "out/synth_manifest.json", "out/lsp_crosscheck_report.json",
        "out/classic_compiler_provenance.json", "out/classic_hover_crosscheck.json",
        "out/classic_r5_controls.json", "out/classic_r5_review.json",
        "out/manifest.json", "out/stage1_raw.json",
        "out/4d-oop-ir.json", "out/oop_doc_examples.json", "out/oop_synth_manifest.json",
        "out/oop_corpus_stats.json", "out/oop_refresh_review.json", "out/oop_lsp_crosscheck_report.json",
        "out/oop_hover_crosscheck.json", "out/oop_type_name_crosscheck.json", "out/4d-ir-crosslinks.json",
        "out/oop_project_compiler_report.json", "out/oop_project_compiler_provenance.json",
        "out/oop_manifest.json", "out/oop_stage1_raw.json", "out/oop_param_conflicts.json",
        "out/r5_conflict_inventory.json",
    ]
    methods = sorted([*ROOT.glob("Project/Sources/Methods/Synth_*.4dm"),
                      *ROOT.glob("oopcheck/Project/Sources/Methods/SynthOOP_*.4dm")])
    report = {
        "version": version["version"], "status": version["status"], "compilerBuild": BUILD,
        "docsCommit": DOCS_COMMIT, "docsRoot": "mirror/docs",
        "resources": resources, "classic": classic, "oop": oop,
        "crosslinks": {"edges": len(crosslinks["relationships"]), "unresolved": 0},
        "regressionChecks": regression_evidence(),
        "artifactsSha256": {path: digest(path) for path in artifacts},
        "methodsSha256": {str(path.relative_to(ROOT)): digest(path.relative_to(ROOT)) for path in methods},
        "pipelineSha256": {str(path.relative_to(ROOT)): digest(path.relative_to(ROOT))
                           for path in sorted((ROOT / "pipeline").rglob("*.py"))},
        "inputSha256": {
            str(path.relative_to(ROOT)): digest(path.relative_to(ROOT))
            for path in sorted({path for directory in ("pipeline", "references")
                                for path in (ROOT / directory).rglob("*")
                                if path.is_file() and path.suffix in {".json", ".xlf", ".4dm"}})
        },
        "documentationSha256": {
            str(path.relative_to(ROOT)): digest(path.relative_to(ROOT))
            for path in sorted({ROOT / "README.md",
                                *(ROOT / "pipeline").rglob("*.md"),
                                *(ROOT / "references").rglob("*.md")})
        },
        "configurationSha256": {
            path: digest(path) for path in
            (".gitignore", "pipeline/requirements.txt", ".github/workflows/extract-docs.yml")
        },
        "verificationScope": "Source-bound tool4d experimental/checkSyntax static compile checks and separate hover checks; not runtime execution or proof of every full-application arity rule.",
        "limitations": read("out/r5_conflict_inventory.json")["compilerGateLimitations"],
        "oopGateLimitations": read("out/r5_conflict_inventory.json")["oopGateLimitations"],
    }
    (ROOT / "out/r5_snapshot.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Recorded R5 BETA snapshot: {len(methods)} vendoring methods, {len(artifacts)} bound artifacts")


if __name__ == "__main__":
    main()

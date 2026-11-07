#!/usr/bin/env python3
"""Retain every project diagnostic, including synthetic callback helpers."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "oopcheck/Project"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    compiler = Path(os.environ["TOOL4D_PATH"])
    version = subprocess.check_output([str(compiler), "--version"], text=True).strip()
    if version != "21 R5 build 21R5.100156":
        raise ValueError(f"Expected pinned R5 compiler, got {version}")
    bridge = ROOT / "tools/4dlsp/tool4d-lsp-stdio"
    command = [str(bridge), "check-syntax", "--workspace", str(PROJECT), "--json",
               "Sources/Methods/SynthOOP_4D_Blob_new.4dm"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Project compiler failed:\n{result.stdout}\n{result.stderr}")
    entries = json.loads(result.stdout)
    sources = {}
    for entry in entries:
        path = Path(unquote(urlparse(entry["uri"]).path))
        relative = str(path.relative_to(ROOT))
        if relative in sources:
            raise ValueError(f"Duplicate compiler response for {relative}")
        sources[relative] = digest(path)
    manifest = json.loads((ROOT / "out/oop_synth_manifest.json").read_text())
    expected = {"oopcheck/Project/" + path for path in manifest["files"]}
    helpers = {
        "oopcheck/Project/Sources/Classes/SynthOOPHandler.4dm",
        "oopcheck/Project/Sources/Methods/SynthOOPCallback.4dm",
    }
    if set(sources) != expected | helpers:
        raise ValueError(f"Project compiler coverage differs: missing={(expected | helpers) - sources.keys()}, "
                         f"extra={sources.keys() - (expected | helpers)}")
    report_path = ROOT / "out/oop_project_compiler_report.json"
    report_path.write_text(json.dumps(entries, indent=2) + "\n")
    provenance = {
        "compilerVersion": version, "compilerPath": str(compiler),
        "compilerSha256": digest(compiler), "bridgeSha256": digest(bridge),
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "command": command, "returnedFiles": len(entries), "targetedFiles": len(expected),
        "helpers": sorted(helpers), "sourceSha256": sources,
        "irSha256": digest(ROOT / "out/4d-oop-ir.json"),
        "manifestSha256": digest(ROOT / "out/oop_synth_manifest.json"),
        "reportSha256": digest(report_path),
        "diagnosticCount": sum(len(entry["diagnostics"]) for entry in entries),
    }
    (ROOT / "out/oop_project_compiler_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    if provenance["diagnosticCount"]:
        raise ValueError(f"Project has {provenance['diagnosticCount']} diagnostics; see {report_path}")
    if result.returncode:
        raise ValueError(f"Compiler returned {result.returncode} despite no retained diagnostics")
    print(f"{len(entries)} project files clean, including both callback helpers; full diagnostics retained.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compile positive constants and deliberately invalid calls; never run them."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    compiler = Path(os.environ["TOOL4D_PATH"])
    version = subprocess.check_output([str(compiler), "--version"], text=True).strip()
    if version != "21 R5 build 21R5.100156":
        raise ValueError(f"Controls require the pinned R5 compiler, got {version}")
    probes = {
        "R5VectorIndexProbe": ((ROOT / "pipeline/tests/fixtures/R5VectorIndexProbe.4dm").read_text(), False),
        "R5QRHistorical": ("QR REPORT\n", None),
        "R5RegisterHistorical": ("REGISTER CLIENT\n", None),
        "R5UnknownNegative": ("R5FabricatedCommandXyz()\n", True),
    }
    created = []
    rows = []
    try:
        for name, (text, _) in probes.items():
            path = ROOT / "Project/Sources/Methods" / f"{name}.4dm"
            with path.open("x") as stream:
                stream.write(text)
            created.append(path)
        command = [str(ROOT / "tools/4dlsp/tool4d-lsp-stdio"), "check-syntax",
                   "--workspace", str(ROOT / "Project"), "--json",
                   "Sources/Methods/R5VectorIndexProbe.4dm"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if result.returncode not in (0, 1):
            raise RuntimeError(f"Control compiler failed: {result.stderr}")
        response = json.loads(result.stdout)
        for name, (text, expected_error) in probes.items():
            matches = [entry for entry in response if entry["uri"].endswith(f"/{name}.4dm")]
            if len(matches) != 1:
                raise ValueError(f"Compiler omitted or duplicated control {name}")
            diagnostics = matches[0]["diagnostics"]
            has_error = any(d["severity"] == 1 for d in diagnostics)
            if expected_error is None:
                rows.append({"method": name, "source": text, "diagnostics": diagnostics,
                             "status": "historical_rejection_reproduced" if has_error
                             else "historical_rejection_not_reproduced"})
                continue
            passed = has_error == expected_error and (expected_error or not diagnostics)
            rows.append({"method": name, "source": text, "expectsError": expected_error,
                         "diagnostics": diagnostics, "passed": passed})
        report = {
            "compilerVersion": version,
            "compilerSha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
            "controls": rows,
            "limitation": "Compile-time checks only; vector field/index applicability and runtime units are not tested. "
                          "QR REPORT/REGISTER CLIENT are observations of historical full-compiler constraints, "
                          "not required negative controls: checkSyntax does not establish their empty-call validity.",
        }
        (ROOT / "out/classic_r5_controls.json").write_text(json.dumps(report, indent=2) + "\n")
        required = [row for row in rows if "expectsError" in row]
        if not all(row["passed"] for row in required):
            raise ValueError(f"Unexpected controls: {[row for row in required if not row['passed']]}")
        print("Two required controls passed: vector constants accepted; fabricated command rejected.")
        for row in rows:
            if "status" in row:
                print(f"{row['method']}: {row['status']}")
    finally:
        for path in created:
            path.unlink()


if __name__ == "__main__":
    main()

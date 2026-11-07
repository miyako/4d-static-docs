#!/usr/bin/env python3
"""Check classic synthetic call tokens against a running project-scoped LSP."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "tools/4dlsp/tool4d-lsp-stdio"
NO_HOVER_DELIMITERS = {"Begin-SQL", "End-SQL"}
DELIMITER_EVIDENCE = (
    "SQL block delimiters have no tool4d hover entry. Both generated methods "
    "contain a real Begin SQL / End SQL block and must have clean current "
    "compiler verdicts; this is a hover-index limitation, not signature agreement."
)


def classify(cid: str, name: str, value, compiler_rows: list[dict]) -> str:
    if isinstance(value, str) and name.lower() in value.replace("*", "").lower():
        return "recognized"
    if cid in NO_HOVER_DELIMITERS and value == "No hover information available at this position.":
        checks = [row for row in compiler_rows if row["id"] == cid]
        if checks and all(row["status"] == "clean" and not row["diagnostics"] for row in checks):
            return "explained_no_hover"
    return "unrecognized"


def hover(path: Path, line: int, character: int):
    result = subprocess.run(
        [str(BRIDGE), "hover", str(path), "--line", str(line),
         "--character", str(character), "--json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"Hover failed for {path}:{line}:{character}: {result.stderr}")
    return json.loads(result.stdout)["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", help="Comma-separated command ids; default is every synthetic file")
    parser.add_argument("--out", type=Path, default=ROOT / "out/classic_hover_crosscheck.json")
    args = parser.parse_args()
    ir = json.loads((ROOT / "out/4d-command-ir.json").read_text())
    commands = {c["id"]: c for c in ir["commands"]}
    manifest = json.loads((ROOT / "out/synth_manifest.json").read_text())
    compiler_rows = json.loads((ROOT / "out/lsp_crosscheck_report.json").read_text())
    selected = set(args.ids.split(",")) if args.ids else {
        entry["command_id"] for entry in manifest["files"].values()
    }
    missing = selected - {entry["command_id"] for entry in manifest["files"].values()}
    if missing:
        raise ValueError(f"No synthetic method for requested ids: {sorted(missing)}")
    rows = []
    for relative, entry in manifest["files"].items():
        cid = entry["command_id"]
        if cid not in selected:
            continue
        path = ROOT / "Project" / relative
        name = commands[cid]["displayName"]
        calls = [(line, text.index(name)) for line, text in enumerate(path.read_text().splitlines())
                 if not text.lstrip().startswith("//") and name in text]
        if not calls:
            raise ValueError(f"No {name} call token found in {path}")
        line, start = calls[0]
        value = hover(path, line, start + len(name) // 2)
        status = classify(cid, name, value, compiler_rows)
        row = {
            "id": cid, "file": str(path.relative_to(ROOT)),
            "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "line": line, "character": start + len(name) // 2,
            "status": status,
            "hover": value,
        }
        if status == "explained_no_hover":
            row["explanation"] = DELIMITER_EVIDENCE
        rows.append(row)
    counts = {status: sum(r["status"] == status for r in rows)
              for status in ("recognized", "explained_no_hover", "unrecognized")}
    args.out.write_text(json.dumps({"counts": counts, "commands": rows}, indent=2) + "\n")
    print(counts)
    return int(bool(counts["unrecognized"]))


if __name__ == "__main__":
    raise SystemExit(main())

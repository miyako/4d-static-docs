#!/usr/bin/env python3
"""Stage 6 (pilot) -- synthesize .4dm call sites from the assembled IR and
cross-check them against the real 4D compiler via tool4d-lsp-stdio.

This is the Phase 1 *pilot* of the synthetic-example / LSP cross-check
loop: a small, hand-picked subset of commands (the 13 regression fixtures
plus a handful chosen to exercise every Layer-2 construct -- enums,
subGrammars, foreignGrammars, pointer_unresolved targets, literal_symbols,
and the queryThemeChain multiCallChain protocol) is used to prove the
mechanics end to end before scaling to all 1456 commands.

For each pilot command, for each overload, this script:
  - synthesizes one call-site expression per overload, deriving each
    argument from the overload's modeled parameter `type.kind` (see
    `build_arg_for_type` below for the kind -> 4D-syntax mapping), and
  - writes a `.4dm` method file to `Project/Sources/Methods/Synth_<id>.4dm`
    (sanitized/truncated to 31 chars for 4D's identifier rules), and
  - records the (file, line range) -> (command id, overload index) mapping
    in `out/synth_manifest.json` so tool4d diagnostics can be attributed
    back to the specific overload that produced them.

Usage:
    python3 pipeline/stage6_synth_examples.py generate   # write .4dm files + manifest
    python3 pipeline/stage6_synth_examples.py validate   # run tool4d-lsp-stdio, write report
    python3 pipeline/stage6_synth_examples.py report     # print report summary
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IR_PATH = ROOT / "out" / "4d-command-ir.json"
EXAMPLES_PATH = ROOT / "references" / "4d-command-ir-examples.json"
METHODS_DIR = ROOT / "Project" / "Sources" / "Methods"
MANIFEST_PATH = ROOT / "out" / "synth_manifest.json"
REPORT_PATH = ROOT / "out" / "lsp_crosscheck_report.json"
TOOL4D_LSP = ROOT / "tools" / "tool4d-lsp-stdio"

# Extra pilot picks beyond the 13 regression fixtures, chosen to exercise
# every Layer-2 construct at least once (see pipeline/README.md / plan.md
# for the rationale behind each pick):
EXTRA_PILOT_IDS = [
    "WEB-SET-OPTION",              # enum_ref (WebServerOptionSelector)
    "Get-database-parameter",      # enum_ref (DatabaseParameterSelector), out param
    "SET-DATABASE-PARAMETER",      # enum_ref (DatabaseParameterSelector)
    "SQL-EXECUTE",                 # foreign_grammar_ref (SQL)
    "QUERY-BY-SQL",                # foreign_grammar_ref (SQLWhereClauseWithExpressionSubstitution)
    "IMAP-New-transporter",        # callbackContracts (IMAPListenerOn*)
    "SAX-OPEN-XML-ELEMENT",        # handleTypes (SAXContext) + stateMachine (saxParsing) entry
    "SAX-CLOSE-XML-ELEMENT",       # stateMachine (saxParsing) exit
]
# QUERY-BY-ATTRIBUTE and ORDER-BY already appear in the 13 regression
# fixtures and cover subgrammar_ref (attributePath), literal_symbols, and
# the queryThemeChain multiCallChain protocol.


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def sanitize_method_name(command_id: str) -> str:
    """Derive a valid, unique-enough 4D method name from a command id.

    4D identifiers: max 31 chars, must start with a letter/underscore/$,
    letters/digits/underscores/spaces only. Command ids may contain
    hyphens (e.g. "ORDER-BY-FORMULA") or mixed case with different
    hyphenation (e.g. "SAX-Get-XML-node") -- neither is a legal 4D
    identifier fragment, so hyphens become underscores and the whole name
    is prefixed and length-capped.
    """
    base = re.sub(r"[^A-Za-z0-9_]", "_", command_id)
    name = f"Synth_{base}"
    if len(name) > 31:
        # Deterministic truncation + short disambiguating suffix derived
        # from the full id, so two ids that collide after truncation
        # don't silently overwrite each other.
        import hashlib

        digest = hashlib.sha1(command_id.encode()).hexdigest()[:4]
        name = f"{name[:31 - 5]}_{digest}"
    return name


def enum_literal(ir, enum_name: str) -> str:
    values = ir["enums"][enum_name]["values"]
    return values[0]["name"]


def build_arg_for_type(ir, type_obj, ctx: str):
    """Return a 4D expression string for one parameter, given its TypeRef.

    `ctx` is a short human label (e.g. "aTable") used only for comments /
    fallback var names -- it does not affect compiled semantics.
    """
    if isinstance(type_obj, list):
        # Union type: the schema documents this as "value may be any of
        # these shapes"; the first alternative is picked deterministically.
        return build_arg_for_type(ir, type_obj[0], ctx)

    kind = type_obj.get("kind")

    if kind == "concrete":
        name = type_obj["name"]
        if name == "Table":
            return "[SynthTable]"
        if name == "Field":
            return "[SynthTable]label"
        return CONCRETE_LITERALS.get(name, CONCRETE_LITERALS["Text"])

    if kind == "pseudo":
        # "any"/"expression"/etc: a plain Text literal is a valid value for
        # almost every pseudo type in a compile-time-only check.
        return '"synthAny"'

    if kind == "pointer_unresolved":
        targets = type_obj.get("possibleTargets", [])
        if "Table" in targets:
            return "->[SynthTable]"
        if "Field" in targets:
            return "->[SynthTable]label"
        return "Nil"

    if kind == "literal_symbols":
        symbols = type_obj["symbols"]
        # Bare 4D special-symbol tokens (e.g. *, >, <, &, |, #) are written
        # unquoted at the call site -- confirmed against real doc syntax
        # examples (e.g. "ORDER BY([Products];[Products]Name;>)",
        # "QUERY BY ATTRIBUTE(...;*)").
        return symbols[0]

    if kind == "enum_ref":
        return enum_literal(ir, type_obj["enum"])

    if kind == "subgrammar_ref":
        grammar = ir["subGrammars"][type_obj["grammar"]]
        example = grammar.get("syntaxExample", '"x"')
        # syntaxExample is a human-readable "a / b / c" list of alternatives;
        # take the first alternative and make sure it's a quoted Text literal.
        first = example.split("/")[0].strip()
        if not first.startswith('"'):
            first = f'"{first}"'
        return first

    if kind == "foreign_grammar_ref":
        # Foreign-grammar text (SQL, Regex, ...) is opaque to the 4D
        # compiler -- it only needs to type-check as Text. Per the IR's own
        # "validatableByThisCorpus": false marker, tool4d cannot and does
        # not validate the embedded grammar itself.
        return '"1=1"'

    # Unknown/unmodeled kind: emit an explicit marker so it shows up as a
    # visible compile error rather than silently guessing.
    return f"UNKNOWN_TYPE_KIND_{kind}"


CONCRETE_LITERALS = {
    "Text": '"synthText"',
    "String": '"synthText"',
    "Longint": "1",
    "Integer": "1",
    "Real": "1",
    "Number": "1",
    "Boolean": "True",
    "Date": "!2024-01-01!",
    "Time": "?00:00:00?",
    "Pointer": "Nil",
    "Object": "New object",
    "Collection": "New collection",
    "Variant": "1",
    "Picture": "New picture(\"\";\"\")",
    "4D.IMAPTransporter": "Null",
}


def build_call_args(ir, params):
    """Flatten an overload's `params` (Parameter | VariadicGroup elements)
    into a list of argument expressions, honoring each VariadicGroup's
    minimum cardinality."""
    args = []
    for p in params:
        if "members" in p:
            # VariadicGroup: repeat its members `cardinality.min` times
            # (at least once, so the group is actually exercised).
            reps = max(1, p.get("cardinality", {}).get("min", 1) or 1)
            for _ in range(reps):
                for m in p["members"]:
                    args.append(build_arg_for_type(ir, m["type"], m.get("name", "arg")))
        else:
            args.append(build_arg_for_type(ir, p["type"], p.get("name", "arg")))
    return args


def synthesize_command(ir, command) -> list[str]:
    """Return the list of source lines for one command's synthetic method,
    one call-site line per overload, each preceded by a comment recording
    the overload index (for human debugging; the manifest is authoritative
    for line->overload attribution)."""
    lines = []
    for oi, overload in enumerate(command.get("overloads", [])):
        params = overload.get("params", [])
        args = build_call_args(ir, params)
        call_name = command["displayName"]
        arg_str = ";".join(args)
        lines.append(f"// overload {oi}")
        if overload.get("returns"):
            lines.append(f"var $synthResult_{oi} : Variant")
            lines.append(f"$synthResult_{oi}:={call_name}({arg_str})")
        else:
            lines.append(f"{call_name}({arg_str})")
    return lines


def cmd_generate(args):
    ir = load_json(IR_PATH)
    examples = load_json(EXAMPLES_PATH)
    fixture_ids = [c["id"] for c in examples.get("commands", [])]
    pilot_ids = fixture_ids + EXTRA_PILOT_IDS

    commands_by_id = {c["id"]: c for c in ir["commands"]}
    missing = [cid for cid in pilot_ids if cid not in commands_by_id]
    if missing:
        print(f"WARNING: pilot ids not found in assembled IR: {missing}", file=sys.stderr)
        pilot_ids = [cid for cid in pilot_ids if cid in commands_by_id]

    METHODS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"pilot_ids": pilot_ids, "files": {}}

    for cid in pilot_ids:
        command = commands_by_id[cid]
        method_name = sanitize_method_name(cid)
        file_path = METHODS_DIR / f"{method_name}.4dm"
        overload_lines = synthesize_command(ir, command)
        source_lines = list(overload_lines)
        file_path.write_text("\n".join(source_lines) + "\n")

        # Record which source line each overload's call site starts at
        # (1-based, matching tool4d-lsp-stdio diagnostic line numbers).
        overload_line_starts = []
        cursor = 1
        for oi, overload in enumerate(command.get("overloads", [])):
            overload_line_starts.append({"overload_index": oi, "comment_line": cursor})
            cursor += 3 if overload.get("returns") else 2
        manifest["files"][f"Sources/Methods/{method_name}.4dm"] = {
            "command_id": cid,
            "overloads": overload_line_starts,
        }
        print(f"wrote {file_path.relative_to(ROOT)} ({len(command.get('overloads', []))} overload(s))")

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\n{len(pilot_ids)} pilot commands -> {MANIFEST_PATH.relative_to(ROOT)}")


# LSP DiagnosticSeverity codes (see the Language Server Protocol spec).
LSP_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def cmd_validate(args):
    if not MANIFEST_PATH.exists():
        raise SystemExit("out/synth_manifest.json not found -- run 'generate' first")
    if not TOOL4D_LSP.exists():
        raise SystemExit("tools/tool4d-lsp-stdio not found -- provision it per skills/4dtools/SKILL.md")

    manifest = load_json(MANIFEST_PATH)
    rel_paths = sorted(manifest["files"].keys())

    proc = subprocess.run(
        [str(TOOL4D_LSP), "validate", "--json", "--workspace", "Project/"] + rel_paths,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode not in (0, 1):
        print(proc.stdout, file=sys.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"tool4d-lsp-stdio exited with unexpected code {proc.returncode}")

    try:
        # Actual shape: a list of {"uri": "file://...", "diagnostics": [...]},
        # one entry per file that had ANY diagnostics (clean files are
        # omitted entirely). Each diagnostic has 0-based
        # range.start.line/range.end.line, a numeric LSP `severity`, and a
        # `message` -- there is no per-file "path" key, only the full uri.
        per_file = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("Could not parse --json output, raw stdout follows:", file=sys.stderr)
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise

    diagnostics_by_relpath = {}
    for entry in per_file:
        uri = entry["uri"]
        # uri is file:///abs/path/Project/Sources/Methods/Foo.4dm -- recover
        # the "Sources/Methods/Foo.4dm" key used as a manifest/CLI-arg key.
        rel = uri.split("/Project/", 1)[-1]
        diagnostics_by_relpath[rel] = entry["diagnostics"]

    report = []
    for rel_path, file_info in manifest["files"].items():
        cid = file_info["command_id"]
        diags = diagnostics_by_relpath.get(rel_path, [])
        # Attribute each diagnostic to the overload whose comment_line is
        # the closest preceding line (convert 0-based LSP lines to the
        # manifest's 1-based comment_line convention).
        starts = file_info["overloads"]
        for oi_info in starts:
            oi = oi_info["overload_index"]
            start = oi_info["comment_line"]
            end = starts[oi + 1]["comment_line"] if oi + 1 < len(starts) else float("inf")
            matched = []
            for d in diags:
                line = d["range"]["start"]["line"] + 1
                if start <= line < end:
                    matched.append(
                        {
                            "message": d["message"],
                            "severity": LSP_SEVERITY.get(d.get("severity"), d.get("severity")),
                            "line": line,
                        }
                    )
            status = "clean"
            if any(d["severity"] == "error" for d in matched):
                status = "error"
            elif matched:
                status = "warning"
            report.append(
                {
                    "id": cid,
                    "overload_index": oi,
                    "file": rel_path,
                    "diagnostics": matched,
                    "status": status,
                }
            )

    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    n_error = sum(1 for r in report if r["status"] == "error")
    n_warning = sum(1 for r in report if r["status"] == "warning")
    n_clean = sum(1 for r in report if r["status"] == "clean")
    print(f"{len(report)} overload(s) checked: {n_clean} clean, {n_warning} warning-only, {n_error} error")
    print(f"-> {REPORT_PATH.relative_to(ROOT)}")


def cmd_report(args):
    if not REPORT_PATH.exists():
        raise SystemExit("out/lsp_crosscheck_report.json not found -- run 'validate' first")
    report = load_json(REPORT_PATH)
    for r in report:
        if r["status"] != "clean":
            print(f"{r['id']} overload {r['overload_index']}: {r['status']}")
            for d in r["diagnostics"]:
                print(f"    {d}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="write synthetic .4dm files + manifest")
    sub.add_parser("validate", help="run tool4d-lsp-stdio and write the cross-check report")
    sub.add_parser("report", help="print a summary of non-clean overloads")
    args = parser.parse_args()

    {"generate": cmd_generate, "validate": cmd_validate, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()

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


# 4D `var $x : <Type>` declaration keywords for concrete IR type names that
# need an addressable variable rather than a bare literal (see `direction`
# handling in build_arg_for_param below). "Array" is deliberately absent --
# arrays are declared with the ARRAY <ELEMENT-TYPE> command, not `var`, so
# it is special-cased separately.
DECLARABLE_VAR_TYPES = {
    "Text": "Text",
    "String": "Text",
    "Longint": "Longint",
    "Integer": "Integer",
    "Real": "Real",
    "Number": "Real",
    "Boolean": "Boolean",
    "Date": "Date",
    "Time": "Time",
    "Object": "Object",
    "Collection": "Collection",
    "Variant": "Variant",
    "Picture": "Picture",
}


class SynthContext:
    """Per-overload mutable state threaded through argument synthesis:
    `prelude` accumulates variable-declaration statements that must be
    emitted before the call line, `counter` gives each declared variable a
    unique name, and `star_active` implements the "star_operator_dual_signature"
    heuristic (category C, ~167 commands per out/4d-command-ir.json's
    relationships[]): once a bare `*` literal_symbols argument is emitted,
    a later sibling parameter whose union type offers both Integer and
    Text alternatives switches from the default (first-listed, usually
    "reference number") alternative to Text ("name string"), matching the
    documented "asObjectName" toggle convention.
    """

    def __init__(self):
        self.prelude: list[str] = []
        self.counter = 0
        self.star_active = False

    def fresh_name(self, prefix: str) -> str:
        self.counter += 1
        return f"${prefix}{self.counter}"


def enum_literal(ir, enum_name: str) -> str:
    values = ir["enums"][enum_name]["values"]
    return values[0]["name"]


def build_arg_for_type(ir, type_obj, ctx: str, ctx_state: SynthContext, direction: str = "in"):
    """Return a 4D expression string for one parameter, given its TypeRef.

    `ctx` is a short human label (e.g. "aTable") used only for fallback var
    names -- it does not affect compiled semantics. `direction` ("in" |
    "out" | "inout") controls whether an addressable variable must be
    declared (out/inout params cannot be passed an expression/literal in
    4D) rather than a bare literal.
    """
    if isinstance(type_obj, list):
        # Union type: the schema documents this as "value may be any of
        # these shapes". Default: first alternative, EXCEPT the
        # star_operator_dual_signature toggle (see SynthContext docstring):
        # once `*` has been passed, prefer a Text alternative if present.
        if ctx_state.star_active:
            names = [t.get("name") for t in type_obj if t.get("kind") == "concrete"]
            if "Text" in names:
                return build_arg_for_type(
                    ir, type_obj[names.index("Text")], ctx, ctx_state, direction
                )
        return build_arg_for_type(ir, type_obj[0], ctx, ctx_state, direction)

    kind = type_obj.get("kind")

    if kind == "concrete":
        name = type_obj["name"]
        if name == "Table":
            return "[SynthTable]"
        if name == "Field":
            return "[SynthTable]label"
        if name == "Array":
            # Arrays are by-reference by construction -- always declare a
            # real typed array and pass its name, never a literal.
            arr = ctx_state.fresh_name("arr")
            ctx_state.prelude.append(f"ARRAY LONGINT({arr};0)")
            return arr
        if direction in ("out", "inout") or name not in CONCRETE_LITERALS:
            # By-reference params (and any concrete type this pilot has no
            # literal for) need an actual variable -- 4D rejects an
            # expression/literal in an out/inout argument slot.
            var_type = DECLARABLE_VAR_TYPES.get(name, "Variant")
            v = ctx_state.fresh_name("v")
            ctx_state.prelude.append(f"var {v} : {var_type}")
            return v
        return CONCRETE_LITERALS[name]

    if kind == "pseudo":
        # "any"/"expression"/etc: default to a plain Text literal, which
        # type-checks for almost every pseudo type in a compile-time-only
        # check -- EXCEPT known by-reference pseudo params (see below).
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
        if symbols == ["*"]:
            ctx_state.star_active = True
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
    "4D.IMAPTransporter": "Null",
    # NOTE: "Picture" is deliberately absent -- GRAPH/GRAPH SETTINGS model
    # their Picture parameter as inout, and 4D rejects an expression
    # (New picture(...)) in a by-reference slot, so Picture always goes
    # through the var-declaration path above regardless of direction.
}

# Known SQL/pseudo params that must be an addressable Field/Variant
# reference rather than any literal, even though the IR models them as
# pseudo:"any" (e.g. SQL EXECUTE's placeholder-substitution `parameter`
# arg). tool4d confirmed this ("Impossible to cast Text to Field<Variant>")
# during the Phase 1 pilot; flagged here as a known synthesizer special
# case pending a possible schema addition (see plan.md open questions).
PSEUDO_REQUIRES_REFERENCE = {
    ("SQL-EXECUTE", "parameter"),
}


def build_call_args(ir, params, ctx_state: SynthContext, command_id: str):
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
                    args.append(
                        build_arg_for_type(
                            ir, m["type"], m.get("name", "arg"), ctx_state, m.get("direction", "in")
                        )
                    )
        else:
            pname = p.get("name", "arg")
            if (command_id, pname) in PSEUDO_REQUIRES_REFERENCE:
                v = ctx_state.fresh_name("v")
                ctx_state.prelude.append(f"var {v} : Variant")
                args.append(v)
                continue
            args.append(build_arg_for_type(ir, p["type"], pname, ctx_state, p.get("direction", "in")))
    return args


def synthesize_command(ir, command) -> list[list[str]]:
    """Return one list of source lines per overload (any variable-
    declaration prelude lines its by-reference/Array parameters need,
    followed by the call-site line), each block starting with a comment
    recording the overload index (for human debugging; the manifest is
    authoritative for line->overload attribution). Returning per-overload
    blocks (rather than one flat list) lets the caller compute exact
    1-based line ranges even though prelude length now varies per overload."""
    blocks = []
    # One SynthContext shared across all overloads of this command so that
    # `fresh_name()` never reuses a variable name between overloads -- all
    # overloads land in the same .4dm file/method scope, so per-overload
    # counters previously collided (e.g. GRAPH's two overloads each
    # declaring "$v1", which 4D flags as a variable-redefinition warning).
    # `prelude`/`star_active` are still reset per overload since each
    # overload's declarations and star-toggle state are independent.
    ctx_state = SynthContext()
    for oi, overload in enumerate(command.get("overloads", [])):
        params = overload.get("params", [])
        ctx_state.prelude = []
        ctx_state.star_active = False
        args = build_call_args(ir, params, ctx_state, command["id"])
        call_name = command["displayName"]
        arg_str = ";".join(args)
        block = [f"// overload {oi}"]
        block.extend(ctx_state.prelude)
        if overload.get("returns"):
            block.append(f"var $synthResult_{oi} : Variant")
            block.append(f"$synthResult_{oi}:={call_name}({arg_str})")
        else:
            block.append(f"{call_name}({arg_str})")
        blocks.append(block)
    return blocks


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
        overload_blocks = synthesize_command(ir, command)
        source_lines = [line for block in overload_blocks for line in block]
        file_path.write_text("\n".join(source_lines) + "\n")

        # Record which source line each overload's call site starts at
        # (1-based, matching tool4d-lsp-stdio diagnostic line numbers),
        # using each block's actual length (prelude length varies).
        overload_line_starts = []
        cursor = 1
        for oi, block in enumerate(overload_blocks):
            overload_line_starts.append({"overload_index": oi, "comment_line": cursor})
            cursor += len(block)
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

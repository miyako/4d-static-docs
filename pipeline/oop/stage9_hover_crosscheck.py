#!/usr/bin/env python3
"""GATE G5 -- diff the 4D compiler's own view of every OOP member against the IR.

`check-syntax` proves the synthesized corpus COMPILES; it does not prove the
IR describes the members correctly. A member that was renamed or made
obsolete, or whose parameter list the docs got wrong, can still compile if the
call happens to be well-formed -- `skills/4dlsp/SKILL.md` calls this out
explicitly as the blind spot of syntax checking.

`textDocument/hover` closes it. tool4d answers with the signature set the
compiler itself holds for a member, e.g.

    .copy() : Collection
    .copy( option : Integer ) : Collection
    .copy( option : Integer ; groupWithCol : Collection ) : Collection
    .copy( option : Integer ; groupWithObj : Object ) : Collection

That is a THIRD independent source, derived from neither the HTML docs
(stage O1) nor syntaxEN.json (stage O2). This stage hovers one call site per
member -- reusing the already-verified call sites in oopcheck/Project that
stage O6 generated -- and reports every disagreement to
out/oop_hover_crosscheck.json.

Disagreements are recorded, not auto-applied: hover's rendering differs from
the docs in ways that are cosmetic (it drops `{}` optional markers, spells
Integer for enum params, elides variadics), so each finding is triaged by
hand and, if it is a real IR bug, fixed through a semantic overlay.

Prerequisite: a running server, so ~500 hovers cost ~0.2s each instead of a
full tool4d startup each:

    tools/tool4d-lsp-stdio mcp --workspace "$PWD/oopcheck/Project"
    python3 pipeline/oop/stage9_hover_crosscheck.py
    tools/tool4d-lsp-stdio mcp --stop
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IR_PATH = ROOT / "out" / "4d-oop-ir.json"
PROJECT_DIR = ROOT / "oopcheck" / "Project"
MANIFEST_PATH = ROOT / "out" / "oop_synth_manifest.json"
OUT_PATH = ROOT / "out" / "oop_hover_crosscheck.json"
TOOL4D_LSP = ROOT / "tools" / "tool4d-lsp-stdio"

NO_HOVER = "No hover information available at this position."

# Members whose synthesized call site deliberately uses a stand-in name rather
# than the documented one, so there is nothing at that position for hover to
# resolve to the IR entry. Kept in sync with stage O6's table.
DYNAMIC_MEMBERS = {
    "4D.classClassName",
    "4D.classStoreName",
    "DataClass.attributeName",
    "DataStore.dataclassName",
    "Entity.attributeName",
    "EntitySelection.attributeName",
    "WebForm.componentName",
}

# tool4d renders an alternate overload with a trailing `*` on the member name
# (`.verify*( message : Blob ; ... )`), which is a rendering marker, not part
# of the name.
# Disagreements that are understood and deliberate. Hover renders the member's
# DOCUMENTATION string, so where the docs are wrong hover repeats the error and
# check-syntax -- which exercises the real parser -- is the stronger oracle.
EXPLAINED_DISAGREEMENTS = {
    "4D.Folder.new": (
        "Hover still shows the `{ ; * }` that FolderClass.html documents, because hover "
        "renders the doc string. The parser disagrees with the doc: tool4d accepts "
        "`Folder(\"/tmp\"; fk posix path; *)` but rejects "
        "`4D.Folder.new(\"/tmp\"; fk posix path; *)` with a bare \"Syntax error\", and the "
        "sibling 4D.File.new documents no `*` at all. The IR follows the parser via "
        "pipeline/oop/semantic_overlays/4D.Folder.new.json, so this arity difference is "
        "expected and is not an IR bug."
    ),
}

SIG_RE = re.compile(r"^\s*(?P<name>[\w.]*\.?\w+)\*?\s*\((?P<params>.*)\)\s*(?::\s*(?P<ret>.+?))?\s*$")
PROP_RE = re.compile(r"^\s*\.?(?P<name>\w+)\s*:\s*(?P<type>.+?)\s*$")


def hover(path: Path, line0: int, char: int) -> str | None:
    proc = subprocess.run(
        [
            str(TOOL4D_LSP),
            "hover",
            "--json",
            "--line",
            str(line0),
            "--character",
            str(char),
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return None
    try:
        result = json.loads(proc.stdout)["result"]
    except (json.JSONDecodeError, KeyError):
        return None
    return None if result == NO_HOVER else result


def signature_lines(markdown: str) -> list[str]:
    """The leading signature block of a hover response, before the prose."""
    lines = []
    for raw in markdown.split("\n"):
        line = raw.strip()
        if not line:
            break
        lines.append(line)
    return lines


def parse_params(text: str) -> list[str]:
    """Ordered parameter names from one rendered signature's argument list."""
    names = []
    for chunk in text.split(";"):
        # tool4d keeps the docs' `{ ... }` optional markers and `...` variadic
        # marker in the rendered signature; they are notation, not name text.
        chunk = chunk.replace("{", " ").replace("}", " ").replace("...", " ")
        chunk = chunk.strip().lstrip(".").strip()
        if not chunk:
            continue
        names.append(chunk.split(":")[0].strip())
    return names


def normalize_type(t: str) -> str:
    t = (t or "").strip().rstrip(".")
    aliases = {
        "Longint": "Integer",
        "Real": "Number",
        "String": "Text",
        "Variant": "any",
    }
    return aliases.get(t, t)


def ir_type_name(t) -> str:
    if isinstance(t, list):
        return "|".join(sorted(ir_type_name(x) for x in t))
    if not isinstance(t, dict):
        return "any"
    if t.get("kind") == "enum_ref":
        # Every enum in this corpus is Integer-valued, which is how the
        # compiler renders such a parameter.
        return "Integer"
    if t.get("kind") == "pseudo":
        return "any" if t.get("name") == "any" else t.get("name")
    return t.get("name") or "any"


def find_call_position(member, block_lines: list[str]) -> tuple[int, int] | None:
    """(line offset within the block, character) of the member name in the call."""
    short = member["memberName"].lstrip(".").split(".")[-1]
    for offset in range(len(block_lines) - 1, -1, -1):
        line = block_lines[offset]
        m = re.search(r"\.(" + re.escape(short) + r")\b", line)
        if m:
            return offset, m.start(1) + 1
    return None


def compare(member, sigs: list[str]) -> list[dict]:
    findings = []
    if member["kind"] == "oop_property":
        declared = member["accessor"]["type"]
        ir_types = {
            normalize_type(ir_type_name(t))
            for t in (declared if isinstance(declared, list) else [declared])
        }
        hover_types = set()
        for line in sigs:
            m = PROP_RE.match(line)
            if m:
                hover_types.add(normalize_type(m.group("type")))
        if hover_types and not (hover_types & ir_types):
            findings.append(
                {
                    "kind": "property_type",
                    "ir": sorted(ir_types),
                    "hover": sorted(hover_types),
                }
            )
        return findings

    parsed = [SIG_RE.match(line) for line in sigs]
    parsed = [m for m in parsed if m]
    if not parsed:
        return [{"kind": "unparsed_hover", "hover": sigs}]

    if len(parsed) != len(member["overloads"]):
        findings.append(
            {
                "kind": "overload_count",
                "ir": len(member["overloads"]),
                "hover": len(parsed),
                "hoverSignatures": sigs,
            }
        )

    ir_arities = sorted(len(o["params"]) for o in member["overloads"])
    hv_arities = sorted(len(parse_params(m.group("params"))) for m in parsed)
    if ir_arities != hv_arities:
        findings.append(
            {"kind": "arity_set", "ir": ir_arities, "hover": hv_arities, "hoverSignatures": sigs}
        )

    ir_rets = {normalize_type(ir_type_name(o.get("returns"))) for o in member["overloads"]}
    hv_rets = {normalize_type(m.group("ret") or "") for m in parsed}
    hv_rets.discard("")
    if hv_rets and not (hv_rets & ir_rets):
        findings.append(
            {"kind": "return_type", "ir": sorted(ir_rets), "hover": sorted(hv_rets)}
        )

    ir_names = {tuple(p.get("name") or "" for p in o["params"]) for o in member["overloads"]}
    hv_names = {tuple(parse_params(m.group("params"))) for m in parsed}
    only_hover = hv_names - ir_names
    if only_hover and hv_arities == ir_arities:
        findings.append(
            {
                "kind": "param_names",
                "ir": sorted("|".join(x) for x in ir_names),
                "hover": sorted("|".join(x) for x in only_hover),
            }
        )
    return findings


def main() -> int:
    ir = json.load(open(IR_PATH))
    by_id = {c["id"]: c for c in ir["commands"]}
    manifest = json.load(open(MANIFEST_PATH))

    results = []
    unknown, agree, disagree, skipped = [], 0, 0, 0
    no_hover_multivariant: list[str] = []
    explained_n = 0
    items = sorted(manifest["files"].items())
    for n, (rel, info) in enumerate(items, 1):
        member_id = info["member_id"]
        member = by_id[member_id]
        if member_id in DYNAMIC_MEMBERS:
            skipped += 1
            results.append({"id": member_id, "status": "skipped-dynamic"})
            continue
        path = PROJECT_DIR / rel
        lines = path.read_text().splitlines()
        block = info["blocks"][0]
        start = block["comment_line"] - 1
        body = lines[start : start + block["lines"]]
        pos = find_call_position(member, body)
        if pos is None:
            results.append({"id": member_id, "status": "no-call-site"})
            continue
        markdown = hover(path, start + pos[0], pos[1])
        if markdown is None:
            multi = member["kind"] == "oop_property" and isinstance(
                member["accessor"].get("type"), list
            )
            if multi:
                # Empirically, tool4d's hover index holds ONE type per property
                # and simply has no entry for a multi-typed one: every
                # single-typed sibling on the same class answers (Email.subject,
                # WebServer.debugLog), while all nine multi-typed properties in
                # the corpus answer "No hover information available at this
                # position." This is a gap in hover's index, not evidence the
                # member is unknown -- GATE G4 compiles a read AND a write for
                # every variant of all nine with 0 diagnostics.
                no_hover_multivariant.append(member_id)
                results.append(
                    {
                        "id": member_id,
                        "status": "no-hover-multivariant-property",
                        "irTypes": [ir_type_name(t) for t in member["accessor"]["type"]],
                        "note": (
                            "tool4d hover has no entry for multi-typed properties; "
                            "covered instead by G4, which compiles every variant."
                        ),
                    }
                )
                continue
            unknown.append(member_id)
            results.append(
                {
                    "id": member_id,
                    "status": "unknown-to-compiler",
                    "file": rel,
                    "line": start + pos[0] + 1,
                }
            )
            continue
        sigs = signature_lines(markdown)
        findings = compare(member, sigs)
        if findings:
            explained = EXPLAINED_DISAGREEMENTS.get(member_id)
            if explained:
                explained_n += 1
            else:
                disagree += 1
            entry = {
                "id": member_id,
                "status": "explained-disagreement" if explained else "disagreement",
                "hoverSignatures": sigs,
                "findings": findings,
            }
            if explained:
                entry["reason"] = explained
            results.append(entry)
        else:
            agree += 1
            results.append({"id": member_id, "status": "agrees", "hoverSignatures": sigs})
        if n % 100 == 0:
            print(f"  {n}/{len(items)}", file=sys.stderr)

    report = {
        "gate": "G5",
        "summary": {
            "members": len(items),
            "agrees": agree,
            "disagreements": disagree,
            "explainedDisagreements": explained_n,
            "unknownToCompiler": len(unknown),
            "skippedDynamic": skipped,
            "noHoverMultivariantProperty": len(no_hover_multivariant),
        },
        "noHoverMultivariantProperty": no_hover_multivariant,
        "unknownToCompiler": unknown,
        "results": results,
    }
    OUT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    print(f"-> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

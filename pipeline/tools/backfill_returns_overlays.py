#!/usr/bin/env python3
"""One-off migration: restore `returns` for commands whose overlay's
`overloadMerges` entry silently dropped it.

Background: `pipeline/common/autoparse.py`'s `draft_overload_params` used
to require a top-level `(...)` parameter list to even attempt parsing a
trailing `: ReturnType`, so bare zero-argument signatures like
"Monitored activity : Collection" lost their return type entirely. That
regex bug is now fixed (see autoparse.py) and self-heals every command with
no overlay, or an overlay with no `overloadMerges`, the next time Stage 3 +
Stage 5 re-run -- nothing to do there.

Separately (and independently), whenever a command's
`pipeline/semantic_overlays/<id>.json` includes an `overloadMerges` entry
(used to correct params/direction/etc for a specific overload),
`apply_overload_merges` in `common/stage3lib.py` replaces that overload's
`returns` wholesale from `{"params": merge["params"], ...only fields
explicitly present in merge...}` -- so an overlay author who fixed params
but didn't also explicitly re-list `returns` silently drops a `returns`
the mechanical draft *did* correctly compute. Both bugs surface
identically downstream: a command whose doc page has a "Function result"
row (a real return value, e.g.
https://developer.4d.com/docs/commands/monitored-activity#monitored-activity)
ends up with no `returns` on its assembled overload, so
pipeline/stage6_synth_examples.py emits a bare procedure-style call
(`Command(...)`) and the real 4D compiler rejects it: "This function has
been called as a procedure."

This script handles only the second, narrower class: commands whose
overlay actively re-specifies `params` via `overloadMerges` and needs
`returns` added back explicitly, one merge entry at a time, matching the
note convention already used by the (regex-bug-only) fixes in
Random.json / Keystroke.json / Right-click.json / Refresh-license.json /
WEB-Server-list.json / WEB-Is-server-running.json / WEB-Server.json /
WEB-Get-current-session-ID.json / WEB-Is-secured-connection.json.

For each target id: reads the Stage 1 raw record's parameterTable, takes
the (single -- this script bails with a warning if a command has more
than one, which none currently do) "Function result" row's Type column,
derives a TypeRef via `common.autoparse._type_ref` (the same mapping used
everywhere else), and adds `returns` (+ a short note, appended to any
existing note) to every `overloadMerges` entry in that command's overlay
that doesn't already have one.

Edits are applied as surgical text-level insertions (locate the merge
object's closing brace via bracket matching, splice `returns` in just
before it; locate+rewrite only the affected `"note": "..."` string) rather
than a full `json.load`/`json.dump` round-trip, so the diff for each file
is minimal and every other hand-authored formatting choice in the overlay
is left untouched, per this repo's "smallest necessary change" convention
for editing hand-authored 4D/pipeline artifacts.

Idempotent: a command already fully patched (or one whose overlay has no
`overloadMerges` at all) is skipped on re-run.

Usage:
    python3 pipeline/tools/backfill_returns_overlays.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from common.autoparse import _type_ref  # noqa: E402
from common.stage3lib import build_draft_entry, apply_overlay  # noqa: E402

RAW_PATH = ROOT / "out" / "stage1_raw.json"
OVERLAY_DIR = ROOT / "pipeline" / "semantic_overlays"

NOTE_SUFFIX_TMPL = (
    " Restored `returns` ({type}) from the parameter table's 'Function result' "
    "row -- apply_overload_merges replaces the whole overload from this merge "
    "entry's fields, so it was silently dropped even though the mechanical "
    "draft had correctly computed it."
)

_NOTE_STRING_RE = re.compile(r'"note"\s*:\s*"(?:[^"\\]|\\.)*"')


def _find_matching_brace(text: str, open_idx: int) -> int:
    """`open_idx` points at a '{'. Return the index of its matching '}'."""
    depth = 0
    in_str = False
    escape = False
    for i in range(open_idx, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
    raise ValueError("no matching brace found")


def _enclosing_object_span(text: str, inner_pos: int) -> tuple[int, int]:
    """Given a position inside some JSON object, return (open, close) indices
    of the innermost enclosing '{' ... '}' (tracked via a brace stack, string-aware).
    """
    stack: list[int] = []
    in_str = False
    escape = False
    for i, c in enumerate(text[:inner_pos]):
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                stack.append(i)
            elif c == "}":
                stack.pop()
    open_idx = stack[-1]
    return open_idx, _find_matching_brace(text, open_idx)


def patch_overlay_text(text: str, merges_to_fix: list[dict], return_type_text: str, return_type_ref) -> str:
    """Return `text` with `returns` spliced into each of `merges_to_fix`'s
    JSON object (matched by its unique `note` string) and that merge's
    note extended with an explanatory suffix. Edits are computed against
    the original text then applied back-to-front so earlier offsets stay
    valid.
    """
    edits: list[tuple[int, int, str]] = []  # (start, end, replacement)
    for merge in merges_to_fix:
        note_val = merge.get("note", "")
        candidates = [
            m for m in _NOTE_STRING_RE.finditer(text)
            if json.loads(m.group(0).split(":", 1)[1].strip()) == note_val
        ]
        if len(candidates) != 1:
            raise ValueError(f"expected exactly 1 note match for {note_val!r}, found {len(candidates)}")
        note_start, note_end = candidates[0].span()

        _, merge_close = _enclosing_object_span(text, note_start)

        new_note_val = note_val.rstrip() + NOTE_SUFFIX_TMPL.format(type=return_type_text)
        edits.append((note_start, note_end, f'"note": {json.dumps(new_note_val, ensure_ascii=False)}'))

        # Indent "returns" the same as the merge object's other keys (read
        # from the "note" key's own line), and insert it right after the
        # last non-whitespace character before the merge's closing brace --
        # not right before the brace itself -- so the brace keeps its own
        # original indentation on its own line.
        line_start = text.rfind("\n", 0, note_start) + 1
        indent = text[line_start:note_start]
        j = merge_close - 1
        while text[j] in " \t\n":
            j -= 1
        insert_pos = j + 1
        insert_text = f',\n{indent}"returns": {json.dumps(return_type_ref, ensure_ascii=False)}'
        edits.append((insert_pos, insert_pos, insert_text))

    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")
    args = ap.parse_args()

    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))

    patched = []
    for rec in raw["records"]:
        cid = rec["id"]
        pt = rec.get("parameterTable")
        if not pt:
            continue
        fr_rows = [r for r in pt.get("rows", []) if r.get("Parameter") == "Function result"]
        if not fr_rows:
            continue
        if len(fr_rows) > 1:
            print(f"WARNING: {cid} has {len(fr_rows)} 'Function result' rows -- skipping (needs manual review)")
            continue

        overlay_path = OVERLAY_DIR / f"{cid}.json"
        if not overlay_path.exists():
            continue
        text = overlay_path.read_text(encoding="utf-8")
        overlay = json.loads(text)
        merges = overlay.get("overloadMerges")
        if not merges:
            continue  # the autoparse.py regex fix alone already covers this one

        entry, _, sig_texts = build_draft_entry(rec)
        merged, _ = apply_overlay(entry, sig_texts, overlay_path)
        if all(ov.get("returns") for ov in merged["overloads"]):
            continue  # already fine

        to_fix = [m for m in merges if "returns" not in m]
        if not to_fix:
            continue

        return_type_text = fr_rows[0]["Type"]
        return_type_ref = _type_ref(return_type_text)
        new_text = patch_overlay_text(text, to_fix, return_type_text, return_type_ref)
        json.loads(new_text)  # re-validate before writing

        patched.append(cid)
        if not args.dry_run:
            overlay_path.write_text(new_text, encoding="utf-8")

    print(f"patched: {len(patched)} -> {patched}")
    if args.dry_run:
        print("(dry run -- no files written)")


if __name__ == "__main__":
    main()

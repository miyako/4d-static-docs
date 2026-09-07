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

# 4D View Pro is a licensed/installable 4D component, not part of the base
# language; Project/4DCommandIRSynthCheck.4DProject has no way to provision
# it, so every one of its 122 commands fails tool4d's check for reasons
# entirely unrelated to the IR (confirmed via check-syntax: all 122 4D-View-
# Pro-themed commands error, 0 others do). Permanently excluded from
# generation/validation so the corpus stays signal, not noise. If ViewPro is
# ever provisioned in this environment, this exclusion can be lifted.
EXCLUDED_THEMES = {"4D-View-Pro"}


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


# Matches a bare 4D identifier fragment: letters/digits/underscore, must
# start with a letter or underscore. IR param names are camelCase (e.g.
# "jsonString", "asObjectName") and match this directly when they're sane;
# this also rules out the shapes that don't -- literal_symbols flag names
# like "*"/">"", names starting with a digit (e.g. "4Duser"), and anything
# containing a space or non-ASCII character.
_PARAM_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Param names that pass `_PARAM_IDENT_RE` but are known, from empirical
# tool4d cross-check findings, to cause a real problem when used verbatim
# as a synthesized local-variable-name prefix (e.g. a name colliding with
# something tool4d specifically rejects for a local var but not a param
# name). Empty until a full-corpus re-validation surfaces a concrete case
# -- extend here (with a comment recording the empirical finding) rather
# than guessing preemptively; every local this stage declares is always
# `$`-prefixed, so collision with a bare 4D command/keyword name is not a
# concern by construction.
PARAM_NAME_DENYLIST: set[str] = set()


def sanitize_param_ident(name: str | None) -> str | None:
    """Return `name` unchanged if it's a legal/sane 4D identifier fragment
    suitable as a synthesized local-variable-name prefix (e.g.
    "jsonString"), or None if callers must fall back to the generic
    type-shape prefix (`v`, `arr`, ...) instead -- see `_PARAM_IDENT_RE`
    and `PARAM_NAME_DENYLIST` above for the rejection rules.

    No length cap is applied here: the longest param name across the
    whole IR is 25 characters, and even with the "$" sigil plus a 1-3
    digit `fresh_name` counter suffix that stays well under 4D's
    31-character identifier limit (see `sanitize_method_name` above).
    """
    if not name or not isinstance(name, str):
        return None
    if not _PARAM_IDENT_RE.match(name):
        return None
    if name in PARAM_NAME_DENYLIST:
        return None
    return name


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
    # "Pointer" is deliberately absent from CONCRETE_LITERALS -- there is
    # no such thing as a Pointer literal in 4D (unlike Nil, which is a
    # documentation term, not a keyword). A "nil pointer" is a Pointer
    # variable that has been declared but never assigned via `->`, so
    # every Pointer-typed argument always goes through the declared-var
    # path below (see CONCRETE_LITERALS' "Pointer" omission forcing that
    # branch), never a bare literal.
    "Pointer": "Pointer",
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
        # Whether the CURRENT overload has a '*' star_operator_dual_signature
        # flag param at all (set once per overload, unlike star_active
        # which toggles per render_block variant) -- see the union-type
        # preference logic in build_arg_for_type for why this is needed.
        self.star_present = False
        # Set when synthesizing a self-declaring ARRAY <TYPE> command (e.g.
        # ARRAY TEXT, ARRAY BLOB): its own generic concrete:"Array" param
        # must declare that exact element type, not the LONGINT default,
        # or 4D reports "Redefinition of variable ... from ARRAY LONGINT
        # to ARRAY <TYPE>" (the command's own body redeclares it).
        self.self_array_element: str | None = None
        # Enum-value sweep override: normally an enum_ref param resolves
        # to enum_literal()'s fixed values[0]; when a specific enum sweep
        # variant is being synthesized (see ENUM_SWEEP_MAX / synthesize_
        # command below), this maps enum name -> the value name to use
        # instead, so every constant name in a modeled enum eventually
        # gets compiled at least once, not just the first.
        self.enum_override: dict[str, str] = {}
        # Union-type discriminator sweep override: normally a union-typed
        # param resolves via the preference rules below (star toggle,
        # first-concrete fallback); when a specific union sweep variant is
        # being synthesized (see find_union_params_in_params /
        # synthesize_command below), this maps param name -> the
        # alternative index to force instead, so every alternative shape
        # in a modeled union eventually gets compiled at least once, not
        # just whichever one the default preference rules happen to pick.
        self.union_override: dict[str, int] = {}
        # Param names (within THIS command only -- ctx_state is rebuilt
        # per command) that must always resolve to a declared addressable
        # variable, never a bare literal, regardless of which pass
        # (default or union-sweep) reaches them -- see
        # CONCRETE_REQUIRES_REFERENCE below for why direction/type alone
        # can't capture this.
        self.reference_required: set[str] = set()
        # Param names (within THIS command only) belonging to a "linked
        # union group" (see LINKED_UNION_GROUPS) -- two or more params
        # whose union alternatives must move TOGETHER (e.g. METHOD-SET-
        # COMMENTS' path/comments: both scalar Text, or both Text array;
        # never one of each). Consulted by build_arg_for_type's union
        # branch so the DEFAULT pass resolves every member to the same
        # index (0, the scalar form) instead of each member
        # independently falling through to the star_present preference
        # rule below -- which, for these commands, picks a DIFFERENT
        # alternative per param name (e.g. "Text array" for path but
        # scalar "Date" for modDate), producing an invalid mixed-kind
        # call even in the "default" block. The union-sweep dispatch
        # (synthesize_command) handles the swept variants separately via
        # a whole-group union_override, so this only needs to cover the
        # un-swept default case.
        self.linked_group_members: set[str] = set()
        # (within THIS command only) param name -> forced array element
        # type, from ARRAY_ELEMENT_TYPE_OVERRIDE -- see that table's
        # docstring for why a handful of array params can't use the
        # generic LONGINT default.
        self.array_element_override: dict[str, str] = {}

    def fresh_name(self, prefix: str) -> str:
        self.counter += 1
        return f"${prefix}{self.counter}"

    def fresh_name_for(self, param_name: str | None, fallback_prefix: str) -> str:
        """Like `fresh_name()`, but prefers a sanitized form of the
        command's real, doc-derived param `name` (e.g. "$jsonString1")
        over the generic type-shape prefix (`v`, `arr`, ...), so
        INPUT-derived locals are self-documenting -- an example reading
        `$jsonString1:="synthText"; ...:=JSON Parse($jsonString1;...)` is
        far more useful to a downstream reader/agent than the equivalent
        with `$v1`. Falls back to `fresh_name(fallback_prefix)` whenever
        `param_name` isn't a legal/sane 4D identifier fragment on its own
        (see `sanitize_param_ident`) -- e.g. literal_symbols flag params
        named "*"/">"", names starting with a digit, non-ASCII names, or
        anything else `sanitize_param_ident` rejects. This is purely
        cosmetic (the variable name only) and never changes which 4D
        type gets declared or which value gets passed."""
        ident = sanitize_param_ident(param_name)
        return self.fresh_name(ident or fallback_prefix)


# Concrete IR type names of the form "<Element> array" (as opposed to the
# generic "Array") carry their element type in the name -- map each to the
# 4D ARRAY-declaration keyword for that element.
ARRAY_TYPE_ELEMENT = {
    "Boolean array": "BOOLEAN",
    "Date array": "DATE",
    "Integer array": "INTEGER",
    "Object array": "OBJECT",
    "Pointer array": "POINTER",
    "Real array": "REAL",
    "Text array": "TEXT",
}

# Valid 4D ARRAY-declaration element keywords, used to recognize a
# self-declaring "ARRAY <TYPE>" command from its displayName (see
# SynthContext.self_array_element above).
ARRAY_DECLARE_KEYWORDS = {
    "BLOB", "BOOLEAN", "DATE", "INTEGER", "LONGINT", "OBJECT",
    "PICTURE", "POINTER", "REAL", "TEXT", "TIME",
}


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
        # Union-discriminator sweep override (see find_union_params_in_
        # params / synthesize_command) takes precedence over every other
        # preference below -- if this exact param is being actively swept,
        # force the requested alternative index regardless of any other
        # rule, so every alternative shape gets exercised at least once.
        if ctx in ctx_state.union_override:
            idx = ctx_state.union_override[ctx]
            if 0 <= idx < len(type_obj):
                return build_arg_for_type(ir, type_obj[idx], ctx, ctx_state, direction)
        # Enum-value sweep override (see synthesize_command) takes
        # precedence over every other preference below -- if one of the
        # union alternatives is an enum_ref this call is actively
        # sweeping, use it (otherwise the "prefer concrete" rule just
        # below would always pick a sibling concrete:Text/Integer
        # alternative instead, e.g. GET-PRINT-OPTION's "option": [enum_ref
        # PrintOptionSelector, concrete:Text] -- silently defeating the
        # sweep, since it would never select the enum_ref alternative at
        # all, in any variant).
        for t in type_obj:
            if t.get("kind") == "enum_ref" and t["enum"] in ctx_state.enum_override:
                return build_arg_for_type(ir, t, ctx, ctx_state, direction)
        if ctx in ctx_state.linked_group_members:
            # This param is coupled to sibling param(s) that must all
            # resolve to the SAME alternative index (see
            # LINKED_UNION_GROUPS / SynthContext.linked_group_members) --
            # always the scalar (index 0) form here, since the
            # union-sweep dispatch (synthesize_command) handles every
            # swept variant of this group via its own whole-group
            # union_override, which is already caught by the check above.
            return build_arg_for_type(ir, type_obj[0], ctx, ctx_state, direction)
        if ctx_state.star_active:
            names = [t.get("name") for t in type_obj if t.get("kind") == "concrete"]
            if "Text" in names:
                return build_arg_for_type(
                    ir, type_obj[names.index("Text")], ctx, ctx_state, direction
                )
        elif ctx_state.star_present:
            # The flag-omission sweep (see find_flag_omission_variants) can
            # render a "*" omitted" variant for an overload that DOES have
            # a star_operator_dual_signature flag -- e.g. GET-LIST-ITEM's
            # "list": [Text, Integer] or LISTBOX-SET-ARRAY's "object":
            # [Text, Variable], where '*' omitted means the sibling
            # (non-Text) alternative applies. Text is listed first in the
            # IR so the generic "prefer first concrete" fallback below
            # would still pick Text even with the flag genuinely absent
            # from the call, producing a real type mismatch (a Text
            # literal in a slot that requires the other alternative's
            # type) -- tool4d caught this for both shapes. Only takes
            # effect when this overload actually has a '*' flag
            # (ctx_state.star_present); overloads with an unrelated
            # Text/other union and no '*' flag at all (54 in this corpus,
            # e.g. ARRAY-TO-LIST) keep the existing Text-first default,
            # already cross-checked clean.
            for t in type_obj:
                if t.get("kind") == "concrete" and t.get("name") != "Text":
                    return build_arg_for_type(ir, t, ctx, ctx_state, direction)
        # Otherwise prefer the first *concrete* alternative over a leading
        # pseudo one (e.g. GET LIST ITEM ICON's itemRef: ["pseudo:Operator",
        # "concrete:Integer"] -- the pseudo alternative there just documents
        # that the literal '*' sentinel is also accepted, already captured
        # by sentinelValues; synthesizing a bare pseudo "any" Text literal
        # for a param whose only non-pseudo alternative is Integer produces
        # a value tool4d rejects outright, whereas the concrete alternative
        # always type-checks).
        for t in type_obj:
            if t.get("kind") == "concrete":
                return build_arg_for_type(ir, t, ctx, ctx_state, direction)
        return build_arg_for_type(ir, type_obj[0], ctx, ctx_state, direction)

    kind = type_obj.get("kind")

    if kind == "concrete":
        name = type_obj["name"]
        if name == "Table":
            return "[SynthTable]"
        if name == "Field":
            return "[SynthTable]label"
        if name == "Array" or name in ARRAY_TYPE_ELEMENT:
            # Arrays are by-reference by construction -- always declare a
            # real typed array and pass its name, never a literal. Element
            # type: explicit "<Element> array" names carry it directly;
            # bare "Array" uses the self-declaring-command override (see
            # SynthContext.self_array_element) when set, else LONGINT.
            element = (
                ctx_state.array_element_override.get(ctx)
                or ARRAY_TYPE_ELEMENT.get(name)
                or ctx_state.self_array_element
                or "LONGINT"
            )
            arr = ctx_state.fresh_name_for(ctx, "arr")
            if name == "Array" and ctx_state.self_array_element:
                # This IS a self-declaring "ARRAY <TYPE>" command's own
                # arrayName param (e.g. ARRAY TIME's own first argument) --
                # the call under test already performs the declaration
                # (ARRAY TIME($arr;size;size2)), so emitting an extra
                # prelude "ARRAY TIME($arr;0)" line first re-declares the
                # exact same variable with the exact same command a second
                # time in the same method. tool4d rejected this ("Can't use
                # the same variable name for overloads"). Skip the prelude
                # here; the rendered call line is the only declaration.
                return arr
            ctx_state.prelude.append(f"ARRAY {element}({arr};0)")
            return arr
        if (
            direction in ("out", "inout")
            or name not in CONCRETE_LITERALS
            or ctx in ctx_state.reference_required
        ):
            # By-reference params (and any concrete type this pilot has no
            # literal for) need an actual variable -- 4D rejects an
            # expression/literal in an out/inout argument slot.
            var_type = DECLARABLE_VAR_TYPES.get(name, "Variant")
            v = ctx_state.fresh_name_for(ctx, "v")
            ctx_state.prelude.append(f"var {v} : {var_type}")
            return v
        return CONCRETE_LITERALS[name]

    if kind == "pseudo":
        # An out/inout pseudo param (e.g. GET MENU ITEM PROPERTY's "value",
        # the DOM-Get-*-XML-element family's element-handle result) is a
        # by-reference slot exactly like a concrete out/inout one -- 4D
        # rejects a literal/expression there ("... is an output parameter,
        # it can't be a constant."). Declare an addressable Variant
        # variable instead, same convention as the concrete branch above.
        if direction in ("out", "inout"):
            v = ctx_state.fresh_name_for(ctx, "v")
            ctx_state.prelude.append(f"var {v} : Variant")
            return v
        # "any"/"Expression": default to a plain Text literal, which
        # type-checks for almost every pseudo type in a compile-time-only
        # check -- EXCEPT known by-reference pseudo params (see below).
        # "Operator": this pseudo name is always used (15 occurrences,
        # all within a union alongside concrete:Integer -- see
        # find_union_params_in_params) to represent a param whose
        # sentinelValues document a bare '*' token meaning "the current/
        # selected item" (e.g. DELETE-FROM-LIST's itemRef). A quoted Text
        # literal is the wrong shape for that -- tool4d rejects it -- the
        # bare unquoted symbol is what's actually expected here, same as
        # a literal_symbols flag.
        if type_obj.get("name") == "Operator":
            return "*"
        if ctx in ctx_state.reference_required:
            # See PSEUDO_ANY_REQUIRES_REFERENCE -- this pseudo:"any" param
            # must be an addressable variable/field, not a bare literal.
            v = ctx_state.fresh_name_for(ctx, "v")
            ctx_state.prelude.append(f"var {v} : Variant")
            return v
        return '"synthAny"'

    if kind == "pointer_unresolved":
        targets = type_obj.get("possibleTargets", [])
        if "Table" in targets:
            return "->[SynthTable]"
        if "Field" in targets:
            return "->[SynthTable]label"
        # No resolvable target: same "nil pointer" convention as the
        # concrete:Pointer case above -- declare an unassigned Pointer
        # variable rather than emitting the bare (invalid) "Nil" token.
        v = ctx_state.fresh_name_for(ctx, "v")
        ctx_state.prelude.append(f"var {v} : Pointer")
        return v

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
        enum_name = type_obj["enum"]
        if enum_name in ctx_state.enum_override:
            return ctx_state.enum_override[enum_name]
        return enum_literal(ir, enum_name)

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


# Commands with 2+ params whose union type is a "scalar OR matching array"
# pair (e.g. path: [Text, Text array]) that must move TOGETHER -- 4D's own
# METHOD-{GET,SET}-{CODE,COMMENTS,ATTRIBUTES} family documents two mutually
# exclusive calling syntaxes (act on ONE method by name, or on SEVERAL
# methods via parallel arrays), never a mix of the two forms in one call.
# METHOD-SET-ATTRIBUTES/CODE/COMMENTS already carry an explicit IR
# jointConstraints entry for this ("path and X must be passed as the same
# kind... the two syntaxes cannot be mixed"); the three GET- siblings need
# the identical rule but the semantic overlay review never added it for
# them (a review gap, not a different real rule -- confirmed identical
# doc syntax pattern). Without this table, build_arg_for_type's per-param
# preference rules (particularly the star_present heuristic, keyed only
# on each param's OWN alternatives) can independently pick DIFFERENT
# alternatives for two linked params -- confirmed via tool4d/real compile
# feedback for METHOD-SET-COMMENTS' union-sweep variants (sweeping path
# to scalar Text while comments silently stayed an array): "the type of
# the 1st and 2nd args must match".
LINKED_UNION_GROUPS = {
    "METHOD-GET-ATTRIBUTES": ["path", "attributes"],
    "METHOD-GET-CODE": ["path", "code"],
    "METHOD-GET-COMMENTS": ["path", "comments"],
    "METHOD-GET-MODIFICATION-DATE": ["path", "modDate", "modTime"],
    "METHOD-SET-ATTRIBUTES": ["path", "attributes"],
    "METHOD-SET-CODE": ["path", "code"],
    "METHOD-SET-COMMENTS": ["path", "comments"],
}


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
    "Object": "New object",
    "Collection": "New collection",
    "Variant": "1",
    "4D.IMAPTransporter": "Null",
    # NOTE: "Picture" is deliberately absent -- GRAPH/GRAPH SETTINGS model
    # their Picture parameter as inout, and 4D rejects an expression
    # (New picture(...)) in a by-reference slot, so Picture always goes
    # through the var-declaration path above regardless of direction.
    # NOTE: "Pointer" is deliberately absent -- see DECLARABLE_VAR_TYPES'
    # "Pointer" entry above; "Nil" is not a valid 4D literal/keyword, so
    # every Pointer-typed argument always goes through the var-declaration
    # path (an unassigned `var $v : Pointer` is a real nil pointer).
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

# Same by-reference requirement as CONCRETE_REQUIRES_REFERENCE below, but
# for a pseudo:"any" param -- JSON-Stringify-array's own overlay already
# documents this: "If a scalar variable or field is passed instead of an
# array, the command still returns a valid JSON array string" (a scalar
# VARIABLE OR FIELD, not a bare constant). tool4d confirmed rejecting the
# generic pseudo:"any" Text literal fallback ("Invalid constant type:
# Alphanumeric"). Consulted in build_arg_for_type's pseudo branch,
# alongside CONCRETE_REQUIRES_REFERENCE's own set (reused via
# ctx_state.reference_required, same populate-once-per-command mechanism).
PSEUDO_ANY_REQUIRES_REFERENCE = {
    ("JSON-Stringify-array", "array"),
}

# (command_id, param_name) -> forced array element type, for the narrow
# set of commands whose doc explicitly requires the array's element type
# to MATCH some other argument's actual data type rather than accepting
# the generic default (LONGINT). DISTINCT-VALUES's own param description
# says "array: ... must match aField's type" -- confirmed via a corpus-
# wide description-text search for "must match"+"type" that this is the
# only such case among all bare concrete:"Array" params. The fixture
# table's only field (besides the numeric ID) is [SynthTable]label, a
# Text field (see CONCRETE_LITERALS["Field"]), so DISTINCT-VALUES's array
# must be declared ARRAY TEXT to match it -- tool4d rejected the LONGINT
# default ("array vs. field type mismatch").
ARRAY_ELEMENT_TYPE_OVERRIDE = {
    ("DISTINCT-VALUES", "array"): "TEXT",
    # Same "array element type must match an associated Text field" family
    # as DISTINCT-VALUES above, confirmed via tool4d for 5 more commands
    # that convert between an array and a Field/list whose actual content
    # is Text (this corpus's fixture table's only field, [SynthTable]
    # label, is Text -- see CONCRETE_LITERALS["Field"]): ARRAY-TO-SELECTION
    # ("Retyping... array of type Long integer to variable of type Text"),
    # LIST-TO-ARRAY (a 4D list's items are always Text regardless of
    # whether the list itself is identified by Text name or Integer ID --
    # only the "array" out-param needs this, not the sibling "itemRefs"
    # out-param, which holds numeric item-ref numbers and correctly stays
    # LONGINT), SELECTION-TO-ARRAY and SELECTION-RANGE-TO-ARRAY (their
    # embedded group's "array" member pairs with a Field/Table union
    # "selection"/"data" member that always resolves to the Text field
    # default in this synthesizer, since no union-sweep is generated for a
    # union param embedded inside a VariadicGroup -- see
    # find_union_params_in_params), and ARRAY-TO-LIST (array's elements are
    # copied into a list's Text items, regardless of the list's own Text-
    # name/Integer-ID union). Keyed by bare param name (matching
    # DISTINCT-VALUES's precedent), which applies uniformly whether the
    # param is top-level or embedded in a group -- build_arg_for_type only
    # ever sees the member's own `ctx` (its name), not its container.
    ("ARRAY-TO-SELECTION", "array"): "TEXT",
    ("LIST-TO-ARRAY", "array"): "TEXT",
    ("SELECTION-TO-ARRAY", "array"): "TEXT",
    ("ARRAY-TO-LIST", "array"): "TEXT",
    ("SELECTION-RANGE-TO-ARRAY", "array"): "TEXT",
}

# Known CONCRETE-typed "in"-direction params that nonetheless must be an
# addressable field/variable, never a literal -- the IR's `direction: "in"`
# only tells the synthesizer the value flows into the command, not whether
# the command reads it by reference. 4D's own doc convention sometimes
# signals this via the parameter's description noun ("variable"/"Field",
# not "value") rather than any direction/type distinction the mechanical
# extraction can see:
#   - WEB-SET-HTTP-HEADER's single-Text "header" overload: the doc body
#     states outright "The command will not accept a literal text type
#     constant as the header parameter; it must be a 4D variable or
#     field." (confirmed on developer.4d.com). tool4d's stricter
#     compiler-level check rejects a bare Text literal there.
#   - LAUNCH-EXTERNAL-PROCESS's "inputStream" (stdin): documented type is
#     a Text/Blob union and direction "in", but the real compiler rejects
#     a literal the same way -- confirmed by the user's real-4D-app
#     compile ("... is output which must be field or variable that is of
#     type text"), the same requires-a-real-storage-location family as
#     the aField-as-Field fix (see Get-external-data-path et al.).
#   - LISTBOX-INSERT-COLUMN's "headerVar": documented as "Column header
#     variable" (type Integer, Pointer) -- the Pointer alternative already
#     forces a declared var (Pointer has no literal), but the union's
#     first/default alternative is Integer, which DOES have a literal
#     (build_arg_for_type's default preference happily emits a bare "1"),
#     and the real compiler rejects that ("headerVar can't be a
#     constant."). footerVar (Variable, Pointer) needs no entry here: its
#     first alternative is concrete:Variable, which already has no
#     CONCRETE_LITERALS entry and so already forces a declared var.
# Consulted inside build_arg_for_type's concrete branch by param NAME
# (via ctx_state.reference_required, populated per-command below) so it
# applies uniformly whether a param's value is reached through the
# default pass OR an active union-sweep variant (e.g. headerVar's own
# "union-sweep headerVar=Integer" case) -- unlike a build_call_args-level
# override, this can't be silently bypassed by the union-sweep dispatch,
# since build_arg_for_type recurses into the swept alternative with the
# same `ctx` (param name) either way.
CONCRETE_REQUIRES_REFERENCE = {
    ("WEB-SET-HTTP-HEADER", "header"),
    ("LAUNCH-EXTERNAL-PROCESS", "inputStream"),
    ("LISTBOX-INSERT-COLUMN", "headerVar"),
    # Same "headerVar can't be a constant" shape as LISTBOX-INSERT-COLUMN
    # above (identical Integer|Pointer union, confirmed by a corpus-wide
    # sweep for this exact shape) -- LISTBOX-DUPLICATE-COLUMN wasn't in the
    # user's reported error batch but shares the bug (not yet exercised by
    # any prior cross-check run); LISTBOX-INSERT-COLUMN-FORMULA WAS
    # reported ("Invalid constant type: Real").
    ("LISTBOX-DUPLICATE-COLUMN", "headerVar"),
    ("LISTBOX-INSERT-COLUMN-FORMULA", "headerVar"),
    # LISTBOX-GET-CELL-POSITION's X/Y are documented plain concrete:Real
    # out-parameters (row/column pixel position), yet tool4d still
    # rejected the bare Real literal fallback ("Invalid constant type:
    # Real") -- same "needs a real variable here, not any literal
    # constant" rule as headerVar above, just phrased differently by a
    # newer compiler version, and (unlike headerVar) with no union
    # alternative to pick a declared-var-forcing sibling from.
    ("LISTBOX-GET-CELL-POSITION", "X"),
    ("LISTBOX-GET-CELL-POSITION", "Y"),
    # Set-user-properties's nbLogin/groupOwner ("Binary databases only;
    # ignored in project databases") are documented plain concrete:Integer
    # params but hit the identical "Invalid constant type: Real" rejection
    # (see LISTBOX-GET-CELL-POSITION above -- 4D's bare numeric literals
    # are always internally typed Real regardless of the target param's
    # own declared type).
    ("Set-user-properties", "nbLogin"),
    ("Set-user-properties", "groupOwner"),
    # DOM-Parse-XML-variable's "variable" (Blob|Text union, both
    # overloads) rejects the union's Text alternative as a bare literal
    # ("Incompatible type") -- the command requires an addressable
    # variable holding the XML content, not a Text constant, even though
    # Text is a documented valid alternative type.
    ("DOM-Parse-XML-variable", "variable"),
    # WP-EXPORT-VARIABLE's "destination" (Text|Blob union) rejects the
    # union's Text alternative as a bare literal ("Invalid constant type:
    # Alphanumeric") -- same "must be an addressable variable/field, not a
    # literal" family as WEB-SET-HTTP-HEADER's header above (its own doc
    # calls this param "the 4D destination variable").
    ("WP-EXPORT-VARIABLE", "destination"),
}

# Curated (command_id, param_name) -> literal overrides for params whose
# generic kind-based literal (see build_arg_for_type) type-checks as an
# expression but isn't the *shape* of expression the command actually
# requires:
#   - QUERY/QUERY-SELECTION's "comparator" is documented as one of the
#     symbols = # < > <= >= % (see the command's own param description);
#     the generic concrete:Text literal ("synthText") is a well-typed
#     Text expression but not one of those symbols, so tool4d's stricter
#     compiler-level check rejects it at runtime semantics (confirmed by
#     a real 4D compile) even though it's syntactically a valid Text.
#   - QUERY/QUERY-SELECTION's "queryArgument" (the single-string calling
#     form, overloads 0-1) must evaluate to a Boolean predicate over a
#     field of aTable -- a bare Text/pseudo literal is not a comparison at
#     all ("... is an expression that evaluates as true or false. It
#     can't be a constant."), so this emits an actual field comparison
#     instead of the generic pseudo:Expression fallback.
SPECIAL_ARG_LITERALS = {
    ("QUERY", "comparator"): '"="',
    ("QUERY-SELECTION", "comparator"): '"="',
    ("QUERY", "queryArgument"): '[SynthTable]label="synthAny"',
    ("QUERY-SELECTION", "queryArgument"): '[SynthTable]label="synthAny"',
}

# Commands using the queryThemeChain protocol's single-expression
# "queryArgument" calling form (out/4d-command-ir.json's protocols.
# multiCallChains.queryThemeChain lists QUERY/QUERY-SELECTION alongside
# QUERY-BY-ATTRIBUTE/ORDER-BY/etc, but only these two share this exact
# param shape -- see render_query_chain). Confirmed against developer.4d.
# com's QUERY page (Examples 4, 6-8, 10, 12, 15-17): a real multi-criteria
# query means calling the command repeatedly, re-passing aTable (if the
# overload takes one) every time, with the trailing '*' flag on every call
# except the last, and a leading conjunction ('&'/'|'/'#') on every call
# after the first. A single one-shot call (what render_block's "default"
# variant emits) can only ever prove the FIRST call's own shape type-
# checks -- it never exercises the continuation shape at all, which has
# an entire extra positional argument (the conjunction) that doesn't
# appear anywhere in the IR's own params list for this overload, since
# the conjunction is documented as embedded in queryArgument's own
# micro-grammar rather than modeled as a distinct param (unlike QUERY-BY-
# ATTRIBUTE, which already has an explicit conjOp param of its own).
QUERY_ARG_CHAIN_COMMANDS = {"QUERY", "QUERY-SELECTION"}
# AND/OR/AND-EXCEPT -- swept across the continuation calls below so every
# conjunction symbol gets compiled at least once, not just one.
QUERY_CHAIN_CONJUNCTIONS = ["|", "&", "#"]
QUERY_CHAIN_PREDICATES = [
    '[SynthTable]label="synthAny"',
    '[SynthTable]label="synthOther"',
    '[SynthTable]label="synthYetAnother"',
    '[SynthTable]label="synthFourth"',
]


def render_query_chain(call_name: str, oi: int, has_a_table: bool) -> dict:
    """Build a real multi-criteria call chain for a queryThemeChain
    command's single-expression overload: an opening call (no
    conjunction, trailing '*'), one continuation call per
    QUERY_CHAIN_CONJUNCTIONS symbol (leading conjunction, trailing '*'
    except on the last), and no separate closing call -- the last
    continuation simply omits '*' to execute the accumulated query, per
    the documented "call repeatedly; only the very last call omits '*'"
    rule. Every call re-passes aTable when the overload has one (see
    Example 4/6-8 etc: aTable is NOT omitted on continuation calls, only
    the leading-conjunction rule differs from the first call)."""
    lines = [f"// overload {oi} multi-query chain"]
    n = len(QUERY_CHAIN_CONJUNCTIONS) + 1
    for i in range(n):
        args = []
        if has_a_table:
            args.append("[SynthTable]")
        if i > 0:
            args.append(QUERY_CHAIN_CONJUNCTIONS[i - 1])
        args.append(QUERY_CHAIN_PREDICATES[i])
        if i < n - 1:
            args.append("*")
        lines.append(f"{call_name}({';'.join(args)})")
    return {"overload_index": oi, "variant": "chain", "lines": lines}


# QUERY BY ATTRIBUTE / QUERY SELECTION BY ATTRIBUTE already model their
# conjunction as an explicit "conjOp" param (unlike QUERY/QUERY-SELECTION
# above), but the default single-call rendering always includes it, which
# contradicts developer.4d.com's own rule ("The conjOp parameter is not
# used for the first QUERY BY ATTRIBUTE call of a multiple query, or if
# the query is a simple query."). Build a real chain instead: an opening
# call with conjOp omitted entirely, then one continuation call per
# QUERY_CHAIN_CONJUNCTIONS symbol (conjOp included, trailing '*' except
# on the last).
QUERY_ATTR_CHAIN_COMMANDS = {"QUERY-BY-ATTRIBUTE", "QUERY-SELECTION-BY-ATTRIBUTE"}


def render_query_attr_chain(ir, ctx_state: "SynthContext", call_name: str, oi: int, params: list, command_id: str) -> dict:
    has_a_table = bool(params) and params[0].get("name") == "aTable"
    rest = [p for p in params if p.get("name") not in ("aTable", "conjOp", "*")]
    ctx_state.prelude = []
    lines = [f"// overload {oi} multi-query chain"]
    n = len(QUERY_CHAIN_CONJUNCTIONS) + 1
    for i in range(n):
        args = []
        if has_a_table:
            args.append("[SynthTable]")
        if i > 0:
            args.append(QUERY_CHAIN_CONJUNCTIONS[i - 1])
        for p in rest:
            args.append(build_arg_for_type(ir, p["type"], p.get("name", "arg"), ctx_state, p.get("direction", "in")))
        if i < n - 1:
            args.append("*")
        lines.append(f"{call_name}({';'.join(args)})")
    lines[1:1] = ctx_state.prelude
    return {"overload_index": oi, "variant": "chain", "lines": lines}


# ORDER BY / ORDER BY ATTRIBUTE have no conjunction at all -- multiple
# sort levels are built by calling the command repeatedly, ONE sort level
# (one repetition of the VariadicGroup "sortLevel"/"group") per call,
# re-passing aTable every time, trailing '*' on every call except the
# last (confirmed against developer.4d.com's ORDER BY / ORDER BY
# ATTRIBUTE pages: "you can pass only one sort level (field) per...
# call"). The default single-call rendering (render_block above, which
# expands the VariadicGroup to cardinality.min=1 rep and always includes
# the trailing '*') leaves a dangling, never-closed chain -- syntactically
# fine but never actually demonstrates or closes a real multi-level sort.
ORDER_CHAIN_COMMANDS = {"ORDER-BY", "ORDER-BY-ATTRIBUTE"}
ORDER_CHAIN_ORDERS = [">", "<"]


def render_order_chain(ir, ctx_state: "SynthContext", call_name: str, oi: int, params: list, command_id: str) -> dict:
    has_a_table = bool(params) and params[0].get("name") == "aTable"
    group_param = next(p for p in params if "members" in p)
    ctx_state.prelude = []
    lines = [f"// overload {oi} multi-sort chain"]
    n = len(ORDER_CHAIN_ORDERS)
    for i in range(n):
        args = []
        if has_a_table:
            args.append("[SynthTable]")
        for m in group_param["members"]:
            if m.get("name") == "order":
                args.append(ORDER_CHAIN_ORDERS[i])
            else:
                args.append(build_arg_for_type(ir, m["type"], m.get("name", "arg"), ctx_state, m.get("direction", "in")))
        if i < n - 1:
            args.append("*")
        lines.append(f"{call_name}({';'.join(args)})")
    lines[1:1] = ctx_state.prelude
    return {"overload_index": oi, "variant": "chain", "lines": lines}

# Curated (command_id -> {frozenset({paramA, paramB}), ...}) trailing
# optional-param pairs confirmed (via a live tool4d cross-check) to be
# mutually exclusive alternates of the same call, not independently
# combinable -- e.g. INTEGER TO BLOB/REAL TO BLOB's own jointConstraints
# rule: "offset and * are mutually exclusive: pass at most one of them."
# The synthesizer's default policy (include every optional param) produces
# an invalid call for these, so once the first member of a pair has been
# emitted, later members are skipped outright. Safe only because in every
# entry here the skipped member is the last param in the overload (so
# omitting it just ends the call one argument early, rather than leaving a
# hole in the middle of the positional list).
MUTUALLY_EXCLUSIVE_TRAILING_PARAMS = {
    "INTEGER-TO-BLOB": {frozenset({"offset", "*"})},
    "REAL-TO-BLOB": {frozenset({"offset", "*"})},
    # FORM-SET-SIZE's own jointConstraints rule: "object and * are
    # mutually exclusive (cannot both be passed)." tool4d confirmed the
    # default block's "object" + "*" combination ("Incompatible type").
    "FORM-SET-SIZE": {frozenset({"object", "*"})},
    # WP-SELECT's own jointConstraints rule: "targetObj and the
    # startRange/endRange pair are alternative ways to specify the
    # selection; pass one or the other, not both." A 3-member set works
    # the same way the 2-member sets above do: once "targetObj" (first in
    # the set to appear positionally) is included, both trailing
    # startRange/endRange are skipped. tool4d confirmed the default (and
    # flag-omission) blocks' "targetObj" + "startRange" + "endRange"
    # combination ("Incompatible type").
    "WP-SELECT": {frozenset({"targetObj", "startRange", "endRange"})},
}

# Commands whose embedded VariadicGroup and a later trailing optional
# param are documented alternates -- pass at most one. Selection-to-
# JSON's own overlay: "aField and template are alternative ways to
# restrict which fields are serialized; pass at most one of them." The
# generic MUTUALLY_EXCLUSIVE_TRAILING_PARAMS mechanism above only applies
# to plain top-level params (its exclusion check lives in the `else`
# branch of build_call_args's per-param loop); here one side of the pair
# is an embedded VariadicGroup member (aField), always rendered
# unconditionally by the "members" branch above that loop, so skip the
# group outright for these commands instead -- template is kept since
# it's the more general/customizable of the two documented alternatives.
# tool4d confirmed the default block's "aField" + "template" combination
# ("This value cannot be passed as a parameter to this method or
# command.").
SKIP_GROUP_FOR_TRAILING_PARAM = {"Selection-to-JSON"}

# Commands whose union-typed param can only combine with a following
# optional/required trailing param when it resolves to a specific
# alternative (usually Text) -- per the command's own doc text. Num's
# own description: "When expression is of the string type, you can use a
# separator parameter or a base parameter" (implying: when expression is
# Boolean or Integer instead, separator/base cannot be passed at all --
# the real call is Num(expression) alone, a single argument). tool4d
# confirmed Num(True;"x")/Num(1;"x")/Num(True;1)/Num(1;1) all real-
# compiler-reject ("Incompatible type"), while Num(True)/Num(1) alone are
# legal. Since this corpus's union-sweep always keeps every OTHER param
# at its own default (see the loop below) rather than omitting it, and
# overload 1's "base" is a required (non-optional) param with no legal
# omission at all, there's no single swept call shape that both moves
# expression off Text AND keeps the call legal here -- so the affected
# non-Text alternatives are simply excluded from the sweep for these
# entries (the default block already exercises the Text alternative,
# which is the only one that combines legally with a trailing param).
UNION_SWEEP_TEXT_ONLY_WITH_TRAILING = {("Num", "expression")}


def build_call_args(ir, params, ctx_state: SynthContext, command_id: str):
    """Flatten an overload's `params` (Parameter | VariadicGroup |
    ContentBindingPair elements) into a list of argument expressions,
    honoring each VariadicGroup's minimum cardinality."""
    args = []
    included_names: set[str] = set()
    exclusive_pairs = MUTUALLY_EXCLUSIVE_TRAILING_PARAMS.get(command_id, set())
    for p in params:
        if "members" in p:
            if command_id in SKIP_GROUP_FOR_TRAILING_PARAM:
                # See SKIP_GROUP_FOR_TRAILING_PARAM -- this group is a
                # documented mutually-exclusive alternate of a later
                # trailing param that's always included; drop the group
                # entirely rather than emit both.
                continue
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
        elif "contentParam" in p:
            # ContentBindingPair: ONE argument slot with two documented
            # alternatives (e.g. LISTBOX INSERT COLUMN's headerName: pass
            # either a literal "content" value or a live variable/pointer
            # "binding" to it -- confirmed against real doc syntax
            # "headerName Integer, Pointer", a plain union, not two
            # separate slots). The contentParam alternative is used since
            # it is always literal-friendly (Integer/Text), unlike
            # bindingParam which is typically Pointer/Variable-only.
            content = p["contentParam"]
            args.append(
                build_arg_for_type(
                    ir, content["type"], content.get("name", "arg"), ctx_state, content.get("direction", "in")
                )
            )
        else:
            pname = p.get("name", "arg")
            if any(pname in pair and included_names & pair for pair in exclusive_pairs):
                # Some other member of this param's exclusivity pair was
                # already emitted -- skip this one (see
                # MUTUALLY_EXCLUSIVE_TRAILING_PARAMS docstring above).
                continue
            included_names.add(pname)
            if (command_id, pname) in PSEUDO_REQUIRES_REFERENCE:
                v = ctx_state.fresh_name_for(pname, "v")
                ctx_state.prelude.append(f"var {v} : Variant")
                args.append(v)
                continue
            if (command_id, pname) in SPECIAL_ARG_LITERALS:
                args.append(SPECIAL_ARG_LITERALS[(command_id, pname)])
                continue
            args.append(build_arg_for_type(ir, p["type"], pname, ctx_state, p.get("direction", "in")))
    return args



def find_enum_refs_in_params(params) -> list[str]:
    """Return the distinct enum names referenced (directly, or as one
    alternative of a union type) by an overload's top-level params --
    used to drive the enum-value sweep below. Only plain Parameter
    entries are inspected (none of the enum_ref-bearing commands in this
    corpus use VariadicGroup/ContentBindingPair params)."""
    names = []
    for p in params:
        if "members" in p or "contentParam" in p:
            continue
        t = p.get("type")
        candidates = t if isinstance(t, list) else [t]
        for c in candidates:
            if isinstance(c, dict) and c.get("kind") == "enum_ref" and c["enum"] not in names:
                names.append(c["enum"])
    return names


def _is_plain_optional(p) -> bool:
    return "members" not in p and "contentParam" not in p and bool(p.get("optional"))


# Interactive form commands where BOTH the docs and tool4d agree the
# fully bare zero-argument call is a documented, valid overload (e.g.
# "ADD RECORD" with no parens, confirmed via doc.4d.com) -- yet tool4d's
# static analyzer specifically rejects it with a prototype-mismatch
# error, yet accepts every *other* arity of the same overload
# (ADD RECORD(*), ADD RECORD([Table]), ADD RECORD([Table];*) all
# validate clean). This 3-command family is the only place in the whole
# corpus this happens -- other same-shape "every param optional, flag
# last" commands (e.g. HIGHLIGHT-RECORDS, QUERY-BY-EXAMPLE,
# PRINT-SELECTION) validate their zero-arg variant clean. Root cause
# looks like tool4d's offline/dataless static analyzer being unable to
# resolve "current default table" for these 3 specific interactive
# add/modify/print-record commands without a live form/runtime context
# -- a tooling limitation, not an IR error (the IR's independent
# optionality modeling matches the documented syntax). Excluded here so
# the flag sweep doesn't manufacture a false-positive "IR bug" for a
# call shape real 4D code is documented to support.
FLAG_SWEEP_SKIP_EMPTY_CALL = {"ADD-RECORD", "MODIFY-RECORD", "PRINT-RECORD"}

# Commands whose doc signature wraps every param in its own optionality
# braces (implying, per the auto-parser's independent-per-token reading,
# that a fully bare `Cmd()` call is legal) but where the real 4D compiler
# actually requires at least one argument to be present -- confirmed via
# real-compiler feedback (unlike FLAG_SWEEP_SKIP_EMPTY_CALL above, this
# is NOT a tool4d static-analyzer quirk; QR REPORT() genuinely fails to
# compile: "the command requires at least 1 parameter"). QR-REPORT's own
# doc text even hints at this asymmetry: aTable defaults to the current
# table when omitted, but there's no equivalent "acts on nothing" fallback
# for omitting every parameter simultaneously -- passing document as
# Char(1) (a sentinel documented elsewhere in the same page to mean "no
# such document exists") is the minimal legal call. Treated identically
# to FLAG_SWEEP_SKIP_EMPTY_CALL for sweep-generation purposes (skip
# manufacturing the zero-arg variant), but tracked separately since the
# underlying reason -- a genuine compiler requirement, not a tooling gap
# in the checker -- is different and shouldn't be conflated with it.
COMPILER_REQUIRES_NONEMPTY_CALL = {"QR-REPORT", "REGISTER-CLIENT"}


def find_flag_omission_variants(params, command_id: str) -> list[tuple[str, list]]:
    """Return (label, truncated_params) pairs, one per optional
    literal_symbols "flag" param (e.g. '*', '>') that can be legally
    omitted per 4D's positional-argument calling convention: an optional
    param can only be dropped as part of a contiguous all-optional run at
    the very front or the very back of the argument list -- 4D has no
    named-argument or skip-a-middle-slot mechanism.

    Two thirds of this corpus's optional flags turn out to be LEADING
    (e.g. GET-LIST-ITEM's leading '*' toggles asObjectName addressing for
    every following param -- confirmed against real doc syntax
    "GET LIST ITEM ({*;}list;...)"), not trailing -- the synthesizer
    previously only ever exercised the "flag present" branch, never the
    "flag(s) omitted" branch for either position, which this sweep now
    covers for both.

    `truncated_params` is the params list to actually build the omitted
    call from: dropping a LEADING flag at index i means using
    params[i+1:] (whatever legally-optional params preceded the flag in
    the same leading run, e.g. QUERY-BY-ATTRIBUTE's aTable before conjOp,
    are dropped along with it -- still a legal call, just testing a
    stronger omission than the single flag alone); dropping a TRAILING
    flag at index i means using params[:i]."""
    variants = []
    n = len(params)
    leading_len = 0
    for q in params:
        if _is_plain_optional(q):
            leading_len += 1
        else:
            break
    trailing_start = n
    for q in reversed(params):
        if _is_plain_optional(q):
            trailing_start -= 1
        else:
            break
    for i, p in enumerate(params):
        if "members" in p or "contentParam" in p:
            continue
        t = p.get("type")
        if not (isinstance(t, dict) and t.get("kind") == "literal_symbols" and p.get("optional")):
            continue
        flag_name = p.get("name") or "".join(t.get("symbols", ["flag"]))
        if i < leading_len:
            truncated = params[i + 1 :]
            if truncated or command_id not in FLAG_SWEEP_SKIP_EMPTY_CALL | COMPILER_REQUIRES_NONEMPTY_CALL:
                variants.append((f"omit-leading-thru:{flag_name}", truncated))
        if i >= trailing_start:
            truncated = params[:i]
            if truncated or command_id not in FLAG_SWEEP_SKIP_EMPTY_CALL | COMPILER_REQUIRES_NONEMPTY_CALL:
                variants.append((f"omit-trailing-from:{flag_name}", truncated))
    return variants


def _alt_label(t: dict) -> str:
    kind = t.get("kind")
    if kind == "concrete":
        return t.get("name", "concrete")
    if kind == "pseudo":
        return f"pseudo:{t.get('name', 'any')}"
    if kind == "literal_symbols":
        return "|".join(t.get("symbols", []))
    if kind == "enum_ref":
        return f"enum_ref:{t.get('enum')}"
    return kind or "?"


def find_union_params_in_params(params) -> list[tuple[str, list]]:
    """Return (param_name, alternatives) pairs, one per plain Parameter
    whose type is a union (list) of 2+ alternatives -- used to drive the
    union-discriminator sweep below. Only plain Parameter entries are
    inspected, matching find_enum_refs_in_params/find_flag_omission_
    variants' existing precedent (no VariadicGroup/ContentBindingPair
    param in this corpus carries a union type at the top level).

    Excludes the one param immediately following a leading '*'
    star_operator_dual_signature flag (e.g. DELETE-FROM-LIST's "list"
    right after "asObjectName") when that param's alternatives include a
    "Text" concrete alongside another concrete/pseudo alternative -- this
    is the same condition build_arg_for_type's star_active/star_present
    preference rules already key off of. That param's value isn't an
    independently choosable union member; it's strictly governed by the
    flag (per the IR's own interactionNotes on these commands), so
    forcing e.g. "list=Integer" while the flag is still present in the
    call produces an invalid combination the flag-omission sweep (see
    find_flag_omission_variants) already exercises correctly via the two
    flag on/off variants instead.

    Also excludes any union param in an overload that ALSO has a plain
    enum_ref selector param (only WEB-SET-OPTION's "value" and
    SET-DATABASE-PARAMETER's "value" in this corpus): the union's actual
    valid shape is selector-dependent (e.g. WEB-SET-OPTION's "Web port
    ID" selector requires Integer, not Boolean/Text/Collection), not a
    free choice independent of which selector value the enum-value sweep
    (see find_enum_refs_in_params) happens to be using in a given block
    -- confirmed via tool4d: forcing value=Boolean against the sweep's
    default selector={values[0]} ("Web port ID") produced a real type
    error, not an IR bug."""
    has_enum_selector = any(
        "members" not in q
        and "contentParam" not in q
        and isinstance(q.get("type"), dict)
        and q["type"].get("kind") == "enum_ref"
        for q in params
    )
    out = []
    for i, p in enumerate(params):
        if "members" in p or "contentParam" in p:
            continue
        t = p.get("type")
        if isinstance(t, list) and len(t) > 1:
            if has_enum_selector:
                continue
            if i > 0:
                prev = params[i - 1]
                prev_t = prev.get("type")
                if (
                    "members" not in prev
                    and "contentParam" not in prev
                    and isinstance(prev_t, dict)
                    and prev_t.get("kind") == "literal_symbols"
                    and prev_t.get("symbols") == ["*"]
                ):
                    names = [x.get("name") for x in t if x.get("kind") == "concrete"]
                    if "Text" in names and len(t) > 1:
                        continue
            out.append((p.get("name", "?"), t))
    return out


def synthesize_command(ir, command) -> list[dict]:
    """Return one dict per synthesized block: {"overload_index", "variant",
    "lines"} (any variable-declaration prelude lines its by-reference/
    Array parameters need, followed by the call-site line). Each block's
    first line is a comment recording the overload index and variant (for
    human debugging; the manifest is authoritative for line->block
    attribution).

    Normally there is exactly one block per overload (variant "default").
    For overloads with an enum_ref param, ADDITIONAL blocks (variant
    "enum:<enum_name>=<value_name>") are emitted, one per remaining enum
    value, so every constant name in a modeled enum -- not just
    values[0] -- eventually gets compiled and cross-checked against
    tool4d, not only the first. For overloads with an omittable optional
    literal_symbols flag, ADDITIONAL blocks (variant "flag:omit-...")
    are emitted with that flag (and, if applicable, the rest of its
    leading/trailing optional run) left out of the call entirely, so the
    "flag omitted" branch -- never previously exercised, since the
    synthesizer's default always includes every optional param -- is
    also compiled and cross-checked."""
    blocks = []
    # One SynthContext shared across all overloads of this command so that
    # `fresh_name()` never reuses a variable name between overloads -- all
    # overloads land in the same .4dm file/method scope, so per-overload
    # counters previously collided (e.g. GRAPH's two overloads each
    # declaring "$v1", which 4D flags as a variable-redefinition warning).
    # `prelude`/`star_active` are still reset per overload since each
    # overload's declarations and star-toggle state are independent.
    ctx_state = SynthContext()
    ctx_state.reference_required = {
        pname for (cid, pname) in CONCRETE_REQUIRES_REFERENCE if cid == command["id"]
    } | {
        pname for (cid, pname) in PSEUDO_ANY_REQUIRES_REFERENCE if cid == command["id"]
    }
    ctx_state.linked_group_members = set(LINKED_UNION_GROUPS.get(command["id"], []))
    ctx_state.array_element_override = {
        pname: elem for (cid, pname), elem in ARRAY_ELEMENT_TYPE_OVERRIDE.items() if cid == command["id"]
    }
    # Self-declaring "ARRAY <TYPE>" commands (ARRAY TEXT, ARRAY BLOB, ...)
    # redeclare their own generic concrete:"Array" param at that exact
    # element type -- detect this from the displayName so the array
    # element type below matches, instead of always defaulting to LONGINT.
    m = re.match(r"^ARRAY (\w+)$", command["displayName"])
    if m and m.group(1) in ARRAY_DECLARE_KEYWORDS:
        ctx_state.self_array_element = m.group(1)
    for oi, overload in enumerate(command.get("overloads", [])):
        params = overload.get("params", [])
        call_name = command["displayName"]
        ctx_state.star_present = any(
            "members" not in p
            and "contentParam" not in p
            and isinstance(p.get("type"), dict)
            and p["type"].get("kind") == "literal_symbols"
            and p["type"].get("symbols") == ["*"]
            for p in params
        )

        def render_block(variant: str, comment_suffix: str, overrides: dict[str, str], call_params=None, union_overrides: dict[str, int] | None = None):
            ctx_state.prelude = []
            ctx_state.star_active = False
            ctx_state.enum_override = overrides
            ctx_state.union_override = union_overrides or {}
            block = [f"// overload {oi}{comment_suffix}"]
            if command["id"] in KEYWORD_BLOCK_COMMANDS:
                # A bare 4D keyword-pair block (e.g. Begin SQL/End SQL), not
                # a callable command: written unparenthesized with no
                # argument list, per the IR's own "Is a keyword, not a
                # callable command with parameters" constraint note. Begin
                # SQL and End SQL only type-check as a matched pair, so
                # both synthetic methods (one per command id) emit the
                # full pair -- this is still a valid cross-check that
                # tool4d recognizes each keyword, even though it can't
                # isolate "just Begin SQL" from "just End SQL".
                block.append("Begin SQL")
                block.append("End SQL")
                return {"overload_index": oi, "variant": variant, "lines": block}
            args = build_call_args(ir, call_params if call_params is not None else params, ctx_state, command["id"])
            arg_str = ";".join(args)
            block.extend(ctx_state.prelude)
            if overload.get("returns"):
                # A unique name per BLOCK (not just per overload index) --
                # multiple blocks can share the same overload_index (the
                # "default" block plus its enum-sweep variants, see
                # synthesize_command), and reusing $synthResult_{oi} across
                # them redeclares the same variable in the same method
                # scope, which tool4d flags as "Redefinition of variable".
                result_var = ctx_state.fresh_name("synthResult")
                block.append(f"var {result_var} : Variant")
                block.append(f"{result_var}:={call_name}({arg_str})")
            else:
                block.append(f"{call_name}({arg_str})")
            return {"overload_index": oi, "variant": variant, "lines": block}

        param_names = [p.get("name") for p in params if "members" not in p and "contentParam" not in p]
        if (
            command["id"] in QUERY_ARG_CHAIN_COMMANDS
            and "queryArgument" in param_names
            and "*" in param_names
        ):
            blocks.append(render_query_chain(call_name, oi, param_names[0] == "aTable"))
        elif (
            command["id"] in QUERY_ATTR_CHAIN_COMMANDS
            and "conjOp" in param_names
            and "*" in param_names
        ):
            blocks.append(render_query_attr_chain(ir, ctx_state, call_name, oi, params, command["id"]))
        elif (
            command["id"] in ORDER_CHAIN_COMMANDS
            and any("members" in p for p in params)
            and "*" in param_names
        ):
            blocks.append(render_order_chain(ir, ctx_state, call_name, oi, params, command["id"]))
        else:
            blocks.append(render_block("default", "", {}))

        # Enum-value sweep: for every enum_ref param this overload has,
        # emit one additional block per enum value so every constant name
        # in the referenced enum eventually gets
        # compiled, not just enum_literal()'s fixed values[0] default used
        # by the "default" block above. Skipped for KEYWORD_BLOCK_COMMANDS
        # (no params) and enums with only one value (nothing left to sweep).
        if command["id"] not in KEYWORD_BLOCK_COMMANDS:
            for enum_name in find_enum_refs_in_params(params):
                values = ir["enums"][enum_name]["values"]
                # Sweep ALL values (not values[1:]) -- for a plain
                # enum_ref param the "default" block above already covers
                # values[0], but for a union param like GET-PRINT-OPTION's
                # "option": [enum_ref, concrete:Text], the "prefer concrete"
                # rule in build_arg_for_type means the default block never
                # actually exercises the enum_ref alternative at all (it
                # picks the sibling Text alternative instead), so relying
                # on the default block to have covered values[0] would
                # silently skip it. One harmless duplicate compile of
                # values[0] for the plain (non-union) commands is a small
                # price for this guarantee holding uniformly.
                for v in values:
                    value_name = v["name"]
                    blocks.append(
                        render_block(
                            f"enum:{enum_name}={value_name}",
                            f" enum-sweep {enum_name}={value_name}",
                            {enum_name: value_name},
                        )
                    )

            # Flag on/off sweep: for every optional literal_symbols flag
            # param that sits in a leading or trailing all-optional run,
            # emit one additional block with that flag (and, for a
            # leading flag, whatever legally-optional params preceded it
            # in the same run) omitted from the call entirely -- the
            # "flag omitted" branch, never exercised by the "default"
            # block above since it always includes every optional param.
            for label, call_params in find_flag_omission_variants(params, command["id"]):
                blocks.append(
                    render_block(
                        f"flag:{label}",
                        f" flag-sweep {label}",
                        {},
                        call_params=call_params,
                    )
                )

            # Union-discriminator sweep: for every plain param whose type
            # is a union of 2+ alternatives, emit one additional block per
            # alternative (one param swept at a time, others left at
            # default) -- the "default" block above only ever exercises
            # whichever single alternative the preference rules in
            # build_arg_for_type happen to pick (first concrete, or the
            # star-toggle Text/non-Text choice), so every other shape in
            # a modeled union (e.g. SET-LIST-ITEM-PROPERTIES's "icon":
            # [concrete:Picture, concrete:Integer, concrete:Text]) was
            # never actually compiled before this sweep.
            linked_group = LINKED_UNION_GROUPS.get(command["id"], [])
            for pname, alts in find_union_params_in_params(params):
                if pname in linked_group:
                    # Handled below as a whole-group sweep instead --
                    # sweeping this param alone here would leave its
                    # linked sibling(s) at their own independent default,
                    # producing an invalid mixed-kind call (see
                    # LINKED_UNION_GROUPS).
                    continue
                if (command["id"], pname) in UNION_SWEEP_TEXT_ONLY_WITH_TRAILING:
                    # See UNION_SWEEP_TEXT_ONLY_WITH_TRAILING -- only the
                    # Text alternative combines legally with this
                    # overload's trailing param; skip the others. Keep
                    # original (idx, alt) pairs so union_overrides still
                    # indexes correctly into the full alternatives list.
                    swept = [
                        (idx, a) for idx, a in enumerate(alts)
                        if a.get("kind") == "concrete" and a.get("name") == "Text"
                    ]
                else:
                    swept = list(enumerate(alts))
                for idx, alt in swept:
                    blocks.append(
                        render_block(
                            f"union:{pname}={_alt_label(alt)}",
                            f" union-sweep {pname}={_alt_label(alt)}",
                            {},
                            union_overrides={pname: idx},
                        )
                    )

            # Linked-union-group sweep: every member of a LINKED_UNION_
            # GROUPS group must move to the SAME alternative index in the
            # same call (see the table's docstring) -- so sweep the whole
            # group together, one block per shared index, instead of the
            # generic per-param loop above (which would desync the group).
            if linked_group:
                param_types = {p["name"]: p["type"] for p in params if "name" in p}
                alt_count = min(
                    len(param_types[m]) for m in linked_group if isinstance(param_types.get(m), list)
                )
                for idx in range(alt_count):
                    label = ",".join(
                        f"{m}={_alt_label(param_types[m][idx])}" for m in linked_group
                    )
                    blocks.append(
                        render_block(
                            f"linkedgroup:{label}",
                            f" linked-union-sweep {label}",
                            {},
                            union_overrides={m: idx for m in linked_group},
                        )
                    )
    return blocks


# Commands that are 4D language keywords rather than callable commands
# (written bare, with no parentheses/argument list) -- confirmed via
# developer.4d.com ("Begin SQL is a keyword used in the Method editor...").
# Each must be paired with its closing keyword in the same synthetic
# method for the pair to be syntactically valid on its own.
KEYWORD_BLOCK_COMMANDS = {"Begin-SQL", "End-SQL"}


def resolve_target_ids(ir, commands_by_id, args, default_ids):
    """Decide which command ids a generate/validate/report invocation
    should target, from mutually exclusive --all / --ids / --theme flags,
    falling back to `default_ids` (the Phase 1 pilot set) when none are
    given -- this keeps the original pilot-only invocation
    (`generate`/`validate`/`report` with no flags) working unchanged.

    Returns (target_ids, is_batch): is_batch is True only for --ids/--theme
    (a partial slice of the corpus, used for the Phase 2 merge-not-replace
    manifest/report semantics below) and False for --all or the default
    pilot set (both of which replace their manifest/report wholesale)."""
    all_ids = getattr(args, "all", False)
    ids_arg = getattr(args, "ids", None)
    theme_arg = getattr(args, "theme", None)
    chosen = sum(bool(x) for x in (all_ids, ids_arg, theme_arg))
    if chosen > 1:
        raise SystemExit("--all, --ids, and --theme are mutually exclusive")
    if all_ids:
        return [
            cid for cid, c in commands_by_id.items() if c.get("theme") not in EXCLUDED_THEMES
        ], False
    if ids_arg:
        ids = [x.strip() for x in ids_arg.split(",") if x.strip()]
        missing = [cid for cid in ids if cid not in commands_by_id]
        if missing:
            raise SystemExit(f"--ids: not found in assembled IR: {missing}")
        excluded = [cid for cid in ids if commands_by_id[cid].get("theme") in EXCLUDED_THEMES]
        if excluded:
            raise SystemExit(
                f"--ids: {excluded} belong to a permanently excluded theme "
                f"({EXCLUDED_THEMES}) -- see EXCLUDED_THEMES for why"
            )
        return ids, True
    if theme_arg:
        if theme_arg in EXCLUDED_THEMES:
            raise SystemExit(
                f"--theme {theme_arg!r} is permanently excluded -- see EXCLUDED_THEMES for why"
            )
        ids = [cid for cid, c in commands_by_id.items() if c.get("theme") == theme_arg]
        if not ids:
            raise SystemExit(f"--theme: no commands found with theme {theme_arg!r}")
        return ids, True
    return default_ids, False


def cmd_generate(args):
    ir = load_json(IR_PATH)
    examples = load_json(EXAMPLES_PATH)
    fixture_ids = [c["id"] for c in examples.get("commands", [])]
    default_pilot_ids = fixture_ids + EXTRA_PILOT_IDS

    commands_by_id = {c["id"]: c for c in ir["commands"]}
    default_pilot_ids = [cid for cid in default_pilot_ids if cid in commands_by_id]
    target_ids, subset_mode = resolve_target_ids(ir, commands_by_id, args, default_pilot_ids)

    METHODS_DIR.mkdir(parents=True, exist_ok=True)


    # A full (--all) or default (pilot) run replaces the manifest wholesale.
    # A --ids/--theme batch run merges into whatever manifest already
    # exists on disk, so regenerating one batch doesn't discard the
    # file->overload mappings already recorded for every other command
    # (needed for the "revalidate just this batch" Phase 2 workflow).
    if subset_mode and MANIFEST_PATH.exists():
        manifest = load_json(MANIFEST_PATH)
        manifest.setdefault("files", {})
    else:
        manifest = {"files": {}}
    manifest["pilot_ids"] = sorted(set(manifest.get("pilot_ids", [])) | set(target_ids)) if subset_mode else target_ids

    for cid in target_ids:
        command = commands_by_id[cid]
        method_name = sanitize_method_name(cid)
        file_path = METHODS_DIR / f"{method_name}.4dm"
        overload_blocks = synthesize_command(ir, command)
        source_lines = [line for block in overload_blocks for line in block["lines"]]
        file_path.write_text("\n".join(source_lines) + "\n")

        # Record which source line each block's call site starts at
        # (1-based, matching tool4d-lsp-stdio diagnostic line numbers),
        # using each block's actual length (prelude length varies). A
        # given overload_index may now appear more than once (its
        # "default" block plus zero or more enum-sweep "variant" blocks,
        # see synthesize_command) -- diagnostics are attributed positionally
        # by comment_line range, not by overload_index uniqueness.
        overload_line_starts = []
        cursor = 1
        for block in overload_blocks:
            overload_line_starts.append(
                {
                    "overload_index": block["overload_index"],
                    "variant": block["variant"],
                    "comment_line": cursor,
                }
            )
            cursor += len(block["lines"])
        manifest["files"][f"Sources/Methods/{method_name}.4dm"] = {
            "command_id": cid,
            "overloads": overload_line_starts,
        }
        print(f"wrote {file_path.relative_to(ROOT)} ({len(command.get('overloads', []))} overload(s))")

    # A wholesale run (--all or the default pilot set) knows the complete
    # desired file set -- delete any stray Synth_*.4dm left over from a
    # prior run whose command is no longer targeted (e.g. a newly excluded
    # theme, or a command removed from the IR), so the corpus doesn't
    # silently accumulate stale generated files a --ids/--theme batch run
    # would never touch or know to clean up.
    if not subset_mode:
        wanted = set(manifest["files"].keys())
        for stale in sorted(METHODS_DIR.glob("Synth_*.4dm")):
            rel = f"Sources/Methods/{stale.name}"
            if rel not in wanted:
                stale.unlink()
                print(f"removed stale {stale.relative_to(ROOT)}")

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\n{len(target_ids)} command(s) -> {MANIFEST_PATH.relative_to(ROOT)}")


# LSP DiagnosticSeverity codes (see the Language Server Protocol spec).
LSP_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def cmd_validate(args):
    if not MANIFEST_PATH.exists():
        raise SystemExit("out/synth_manifest.json not found -- run 'generate' first")
    if not TOOL4D_LSP.exists():
        raise SystemExit("tools/tool4d-lsp-stdio not found -- provision it per skills/4dtools/SKILL.md")

    ir = load_json(IR_PATH)
    commands_by_id = {c["id"]: c for c in ir["commands"]}
    manifest = load_json(MANIFEST_PATH)

    all_ids = list(manifest.get("pilot_ids", []))
    target_ids, _ = resolve_target_ids(ir, commands_by_id, args, all_ids)
    target_id_set = set(target_ids)
    subset_mode = target_id_set != set(all_ids)

    rel_paths = sorted(
        rel for rel, info in manifest["files"].items() if info["command_id"] in target_id_set
    )
    if not rel_paths:
        raise SystemExit("no generated files match the requested ids/theme -- run 'generate' for them first")

    # `check-syntax` wraps the same `experimental/checkSyntax` request the
    # 4D Analyzer VS Code extension's "Check workspace syntax" command uses
    # (a real project-wide compile-check pass), and unlike `validate`'s
    # per-file pull diagnostics, it returns diagnostics for the WHOLE
    # project in a single response regardless of which files (if any) are
    # passed as its didOpen/anchor argument -- so this is one subprocess
    # call, not a chunked loop. Passing just one anchor file (rather than
    # every rel_path) avoids any argv-length concern on large batches.
    proc = subprocess.run(
        [str(TOOL4D_LSP), "check-syntax", "--json", "--workspace", "Project/", rel_paths[0]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode not in (0, 1):
        print(proc.stdout, file=sys.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"tool4d-lsp-stdio exited with unexpected code {proc.returncode}")

    try:
        # Same shape as `validate --json`: a list of {"uri": "file://...",
        # "diagnostics": [...]}, one entry per file in the WHOLE project
        # (not just rel_paths) -- clean files are included with an empty
        # "diagnostics" array here (unlike `validate`, which omits them).
        # Each diagnostic has 0-based range.start.line/range.end.line, a
        # numeric LSP `severity`, and a `message`.
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
    print(f"check-syntax: {len(per_file)} file(s) in project, {len(rel_paths)} targeted this run", file=sys.stderr)

    report_this_run = []
    for rel_path in rel_paths:
        file_info = manifest["files"][rel_path]
        cid = file_info["command_id"]
        diags = diagnostics_by_relpath.get(rel_path, [])
        # Attribute each diagnostic to the overload whose comment_line is
        # the closest preceding line (convert 0-based LSP lines to the
        # manifest's 1-based comment_line convention).
        starts = file_info["overloads"]
        for pos, oi_info in enumerate(starts):
            oi = oi_info["overload_index"]
            variant = oi_info.get("variant", "default")
            start = oi_info["comment_line"]
            # Positional (not overload_index-based) lookahead: a given
            # overload_index may now appear more than once in `starts`
            # (its "default" block plus enum-sweep variant blocks, see
            # synthesize_command), so the next block's start is always
            # starts[pos + 1], never starts[oi + 1].
            end = starts[pos + 1]["comment_line"] if pos + 1 < len(starts) else float("inf")
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
            report_this_run.append(
                {
                    "id": cid,
                    "overload_index": oi,
                    "variant": variant,
                    "file": rel_path,
                    "diagnostics": matched,
                    "status": status,
                }
            )

    # Merge semantics: a subset run (--ids/--theme) only touches the
    # entries for the ids it revalidated, leaving every other command's
    # last-known result in place from a prior full/other-batch run; a full
    # run (no flags, or --all) replaces the report wholesale.
    if subset_mode and REPORT_PATH.exists():
        prior_report = load_json(REPORT_PATH)
        report = [r for r in prior_report if r["id"] not in target_id_set] + report_this_run
    else:
        report = report_this_run

    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    n_error = sum(1 for r in report_this_run if r["status"] == "error")
    n_warning = sum(1 for r in report_this_run if r["status"] == "warning")
    n_clean = sum(1 for r in report_this_run if r["status"] == "clean")
    print(f"{len(report_this_run)} overload(s) checked this run: {n_clean} clean, {n_warning} warning-only, {n_error} error")
    if subset_mode:
        t_error = sum(1 for r in report if r["status"] == "error")
        t_warning = sum(1 for r in report if r["status"] == "warning")
        t_clean = sum(1 for r in report if r["status"] == "clean")
        print(f"report totals (all commands): {len(report)} overload(s), {t_clean} clean, {t_warning} warning-only, {t_error} error")
    print(f"-> {REPORT_PATH.relative_to(ROOT)}")


def cmd_report(args):
    if not REPORT_PATH.exists():
        raise SystemExit("out/lsp_crosscheck_report.json not found -- run 'validate' first")
    report = load_json(REPORT_PATH)

    ids_arg = getattr(args, "ids", None)
    theme_arg = getattr(args, "theme", None)
    if ids_arg or theme_arg:
        ir = load_json(IR_PATH)
        commands_by_id = {c["id"]: c for c in ir["commands"]}
        if ids_arg:
            wanted = {x.strip() for x in ids_arg.split(",") if x.strip()}
        else:
            wanted = {cid for cid, c in commands_by_id.items() if c.get("theme") == theme_arg}
        report = [r for r in report if r["id"] in wanted]

    for r in report:
        if r["status"] != "clean":
            variant = r.get("variant", "default")
            suffix = f" [{variant}]" if variant != "default" else ""
            print(f"{r['id']} overload {r['overload_index']}{suffix}: {r['status']}")
            for d in r["diagnostics"]:
                print(f"    {d}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    gen_p = sub.add_parser("generate", help="write synthetic .4dm files + manifest")
    val_p = sub.add_parser("validate", help="run tool4d-lsp-stdio and write the cross-check report")
    rep_p = sub.add_parser("report", help="print a summary of non-clean overloads")

    for p in (gen_p, val_p):
        p.add_argument("--all", action="store_true", help="target every command in the assembled IR (Phase 2 full corpus)")
        p.add_argument("--ids", help="comma-separated command ids to target (batch mode)")
        p.add_argument("--theme", help="target every command with this IR 'theme' (batch mode)")
    rep_p.add_argument("--ids", help="comma-separated command ids to filter the printed summary to")
    rep_p.add_argument("--theme", help="filter the printed summary to commands with this IR 'theme'")

    args = parser.parse_args()

    {"generate": cmd_generate, "validate": cmd_validate, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Stage O6 (Phase 5) -- synthesize compilable 4D call sites for every OOP IR
member and cross-check them against the real 4D compiler via tool4d.

This is the OOP sibling of `pipeline/stage6_synth_examples.py`; read
`pipeline/stage6_README.md` first -- the sweep architecture, the overlay
feedback loop, the "never silence a diagnostic without a written reason"
rule, and the shape of the manifest/report artifacts are all ported from it
unchanged. Only the *emission* layer is new, because an OOP call is not
self-contained: every instance member needs a live, correctly-typed receiver
before it can be called at all.

## What is different from the classic synthesizer

1. **Receivers.** `RECEIVER_RECIPES` below gives one compiling expression per
   class, derived from the IR's own `classes{}.instantiation` recipes and then
   verified against tool4d (see the table's docstring). This has no classic
   analogue -- `ALERT("x")` needs no prior state.
2. **Typed declarations.** Every synthesized local and every captured return
   value is declared at its real IR type (`var $e : cs.SynthTableEntity`,
   `var $r : 4D.Blob`), not classic's `Variant`. That makes `check-syntax`
   dramatically stricter: a wrong declared return type in the IR becomes a
   hard "Impossible to cast X to Y" error instead of silently passing.
3. **Sweeps.** The classic flag-on/off sweep has no OOP analogue (there are no
   `literal_symbols` flag params to omit); its replacement is the
   optional-param present/omitted sweep. The classic union-discriminator
   sweep also has no OOP analogue as a *param* sweep -- the OOP IR expresses
   alternatives as separate overloads, not union-typed params (empirically: 0
   of 446 params carry a list-valued `type`), so enumerating overloads, which
   the default block already does, IS the union sweep. Two genuinely new
   sweeps take their place: property read-vs-write and multi-variant property
   type.

## Sweeps emitted

| Sweep | What it varies | Driven by |
|---|---|---|
| default | one block per overload, all params present | `overloads[]` |
| enum-value | every value of an `enum_ref` param | `find_enum_refs` |
| optional-param | each optional param present vs. the call truncated before it | `find_optional_variants` |
| property read/write | reading, and (if `accessor.writable`) writing | `accessor` |
| property multi-variant | one read/write pair per alternative in a list-valued `accessor.type` | `accessor.type` |

Usage:
    python3 pipeline/oop/stage6_synth_examples.py generate [--all|--ids|--class]
    python3 pipeline/oop/stage6_synth_examples.py validate [--all|--ids|--class]
    python3 pipeline/oop/stage6_synth_examples.py report [--ids|--class]

`generate` is pure Python. Only `validate` needs tool4d, so stages O0-O5 stay
reproducible on a clean clone without a licensed 4D install.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IR_PATH = ROOT / "out" / "4d-oop-ir.json"
PROJECT_DIR = ROOT / "oopcheck" / "Project"
METHODS_DIR = PROJECT_DIR / "Sources" / "Methods"
MANIFEST_PATH = ROOT / "out" / "oop_synth_manifest.json"
REPORT_PATH = ROOT / "out" / "oop_lsp_crosscheck_report.json"
TOOL4D_LSP = ROOT / "tools" / "tool4d-lsp-stdio"

FILE_PREFIX = "SynthOOP_"

# ---------------------------------------------------------------------------
# Documented exclusions. Read pipeline/stage6_README.md's "Deliberate,
# documented sweep exclusions" section before adding to any of these: an
# exclusion is only ever justified by empirical evidence that the IR is
# already right and the generic mechanism is producing an artificial invalid
# construct. Fix the IR (via an overlay) or the emitter first.
# ---------------------------------------------------------------------------

# Members whose receiver class is a *dynamic* namespace/attribute placeholder
# rather than a fixed name (`4D.<classClassName>`, `ds.<dataclassName>`,
# `$entity.<attributeName>`, ...). The IR models these with `dynamicMember`
# and an explicit `namePattern`, precisely because there is no fixed member to
# compile. A concrete stand-in IS synthesized for each (see DYNAMIC_MEMBER_
# STANDIN) rather than skipping them, so the *mechanism* is still compiler-
# verified; only the doc's literal placeholder name is not.
DYNAMIC_MEMBER_STANDIN = {
    # 4D class store: any exposed class is a property of `4D`/`cs`. The check
    # project ships `Sources/Classes/SynthOOPHandler.4dm` for exactly this.
    "4D.classClassName": ("cs.SynthOOPHandler", "4D.Class"),
    "4D.classStoreName": ("cs", None),
    # ORDA: the dataclass/attribute names come from the catalog, so the check
    # project's own SynthTable/textValue are the concrete stand-ins.
    "DataStore.dataclassName": ("ds.SynthTable", "4D.DataClass"),
    "DataClass.attributeName": ("ds.SynthTable.textValue", None),
    "Entity.attributeName": ("$receiver.textValue", "Text"),
    "EntitySelection.attributeName": ("$receiver.textValue", "Collection"),
    # A web form item is addressed by the item's own name in the form; the
    # doc's own example is `Web Form.myButton`.
    "WebForm.componentName": ("Web Form.myButton", "4D.WebFormItem"),
}

# (member id, param name) pairs whose IR type is correct but for which a bare
# literal is rejected by the real compiler, so a declared local must be passed
# instead. Grow this only from an actual tool4d diagnostic, with the message
# quoted in a comment -- the classic corpus's CONCRETE_REQUIRES_REFERENCE
# table is the model.
REQUIRES_REFERENCE: set[tuple[str, str]] = set()

# Member ids excluded from generation entirely, each with the empirical
# evidence that the exclusion is an environment limitation and not an IR bug.
# Empty by design: prefer fixing the IR or the emitter.
EXCLUDED_MEMBERS: dict[str, str] = {}

# Property ids whose `accessor.writable` is true in the IR but whose write
# the compiler rejects. Populated only from a real diagnostic, and mirrored
# into the member's own semantic overlay so IR consumers see the correction
# too (not just this synthesizer).
PROPERTY_WRITE_SKIP: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Receiver recipes
# ---------------------------------------------------------------------------

# One compiling receiver per class id in `out/4d-oop-ir.json`'s `classes{}`.
#
# `lines` are prepended to a block verbatim (declarations + assignment) and
# `expr` is the expression the member is called on. Each entry mirrors the
# class's OWN `instantiation.recipes[0]` from the IR, with the doc's illustrative
# names rewritten to things that exist in the check project (`Employee` ->
# `SynthTable`, `cs.MyClass` -> `cs.SynthOOPHandler`, `Formula(OnData)` ->
# `Formula(SynthOOPCallback)`); a gate in `build_receiver_table` asserts every
# IR class is covered and that none of these reference an unknown class.
#
# Every entry in this table was verified to compile clean by running one
# probe method per class through `tool4d-lsp-stdio check-syntax` against
# `oopcheck/Project/` before this synthesizer was written: 43 of 45 passed
# first time; the two that did not are annotated below.
#
# `kind: "typed_declaration_only"` marks the four event-callback classes.
# Instances of these NEVER exist in user-constructible form -- 4D passes them
# into a callback -- so there is no expression that produces one. They are not
# excluded: a bare typed declaration (`var $event : 4D.TCPEvent`) resolves the
# type for the compiler exactly as a callback parameter does, which was
# verified empirically by compiling the same member access both ways (as a
# local, and as a `Function onTCPData($event : 4D.TCPEvent)` parameter in
# `Sources/Classes/SynthOOPEventHost.4dm`): identical diagnostics from both.
# The generated block carries a comment naming the real callback signature so
# a reader is never misled into thinking the type can be instantiated.
RECEIVER_RECIPES: dict[str, dict] = {
    "4D": {"expr": "4D", "lines": [], "kind": "namespace"},
    "cs": {"expr": "cs", "lines": [], "kind": "namespace"},
    "Blob": {"type": "4D.Blob", "expr": "4D.Blob.new()", "kind": "constructor"},
    "Class": {"type": "4D.Class", "expr": "4D.File", "kind": "property_of"},
    "Collection": {
        "type": "Collection",
        "expr": "New collection(1; 2; 3)",
        "kind": "classic_command",
    },
    "CryptoKey": {
        "type": "4D.CryptoKey",
        "expr": '4D.CryptoKey.new(New object("type"; "RSA"; "size"; 2048))',
        "kind": "constructor",
    },
    "DataClass": {"type": "4D.DataClass", "expr": "ds.SynthTable", "kind": "property_of"},
    "DataStore": {"type": "4D.DataStore", "expr": "ds", "kind": "system_object"},
    # Abstract: synthesized against its only concrete subclass, per the IR's
    # own "Obtain one of those instead" note.
    "Directory": {
        "type": "4D.Folder",
        "expr": "Folder(fk database folder)",
        "kind": "abstract_via_subclass",
        "concreteClass": "Folder",
    },
    "Document": {
        "type": "4D.File",
        "expr": 'File("/PACKAGE/README.md")',
        "kind": "abstract_via_subclass",
        "concreteClass": "File",
    },
    "Email": {"type": "4D.Email", "expr": "4D.Email.new()", "kind": "constructor"},
    "Entity": {
        "type": "cs.SynthTableEntity",
        "expr": "ds.SynthTable.new()",
        "kind": "class_function",
    },
    "EntitySelection": {
        "type": "cs.SynthTableSelection",
        "expr": "ds.SynthTable.all()",
        "kind": "class_function",
    },
    "File": {"type": "4D.File", "expr": 'File("/PACKAGE/README.md")', "kind": "classic_command"},
    "FileHandle": {
        "type": "4D.FileHandle",
        "expr": 'File("/PACKAGE/data.txt").open("write")',
        "kind": "instance_function",
    },
    "Folder": {
        "type": "4D.Folder",
        "expr": "Folder(fk database folder)",
        "kind": "classic_command",
    },
    "Formula": {"type": "4D.Formula", "expr": "Formula(1+2)", "kind": "classic_command"},
    "Function": {
        "type": "4D.Function",
        "expr": "Formula(1+2)",
        "kind": "abstract_via_subclass",
        "concreteClass": "Formula",
    },
    "HTTPAgent": {
        "type": "4D.HTTPAgent",
        "expr": '4D.HTTPAgent.new(New object("keepAlive"; True))',
        "kind": "constructor",
    },
    "HTTPRequest": {
        "type": "4D.HTTPRequest",
        "expr": '4D.HTTPRequest.new("https://example.com")',
        "kind": "constructor",
    },
    # The IR's recipe reads `4D.IMAPNotifier.new($imap; Formula(OnNotification))`,
    # but both syntaxEN and IMAPNotifierClass.html document
    # `4D.IMAPNotifier.new() : 4D.IMAPNotifier` with no parameters, and tool4d
    # rejects the two-argument form ("The function new received too many
    # parameters."). The IR recipe is wrong; see the fix in
    # pipeline/oop/class_instantiation.json.
    "IMAPNotifier": {
        "type": "4D.IMAPNotifier",
        "expr": "4D.IMAPNotifier.new()",
        "kind": "constructor",
    },
    "IMAPTransporter": {
        "type": "4D.IMAPTransporter",
        "expr": '4D.IMAPTransporter.new(New object("host"; "imap.example.com"))',
        "kind": "constructor",
    },
    "IncomingMessage": {
        "type": "4D.IncomingMessage",
        "kind": "typed_declaration_only",
        "callback": "Function handle($request : 4D.IncomingMessage) : 4D.OutgoingMessage",
    },
    "MailAttachment": {
        "type": "4D.MailAttachment",
        "expr": '4D.MailAttachment.new(File("/PACKAGE/report.pdf"))',
        "kind": "constructor",
    },
    "Method": {
        "type": "4D.Method",
        "expr": '4D.Method.new("SynthOOPCallback")',
        "kind": "constructor",
    },
    "OutgoingMessage": {
        "type": "4D.OutgoingMessage",
        "expr": "4D.OutgoingMessage.new()",
        "kind": "constructor",
    },
    "POP3Transporter": {
        "type": "4D.POP3Transporter",
        "expr": '4D.POP3Transporter.new(New object("host"; "pop.example.com"))',
        "kind": "constructor",
    },
    "SMTPTransporter": {
        "type": "4D.SMTPTransporter",
        "expr": '4D.SMTPTransporter.new(New object("host"; "smtp.example.com"))',
        "kind": "constructor",
    },
    "Session": {"type": "4D.Session", "expr": "Session", "kind": "classic_command"},
    "Signal": {"type": "4D.Signal", "expr": 'New signal("synthSignal")', "kind": "classic_command"},
    "SystemWorker": {
        "type": "4D.SystemWorker",
        "expr": '4D.SystemWorker.new("ls -l")',
        "kind": "constructor",
    },
    "TCPConnection": {
        "type": "4D.TCPConnection",
        "expr": '4D.TCPConnection.new("127.0.0.1"; 10000; New object("onData"; Formula(SynthOOPCallback)))',
        "kind": "constructor",
    },
    "TCPEvent": {
        "type": "4D.TCPEvent",
        "kind": "typed_declaration_only",
        "callback": "Function onData($event : 4D.TCPEvent)",
    },
    "TCPListener": {
        "type": "4D.TCPListener",
        "expr": '4D.TCPListener.new(10000; New object("onConnection"; Formula(SynthOOPCallback)))',
        "kind": "constructor",
    },
    "Transporter": {
        "type": "4D.SMTPTransporter",
        "expr": '4D.SMTPTransporter.new(New object("host"; "smtp.example.com"))',
        "kind": "abstract_via_subclass",
        "concreteClass": "SMTPTransporter",
    },
    "UDPEvent": {
        "type": "4D.UDPEvent",
        "kind": "typed_declaration_only",
        "callback": "Function onData($event : 4D.UDPEvent)",
    },
    "UDPSocket": {
        "type": "4D.UDPSocket",
        "expr": '4D.UDPSocket.new(New object("port"; 10000; "onData"; Formula(SynthOOPCallback)))',
        "kind": "constructor",
    },
    "Vector": {
        "type": "4D.Vector",
        "expr": "4D.Vector.new([0.1; 0.2; 0.3])",
        "kind": "constructor",
    },
    "WebForm": {"type": "4D.WebForm", "expr": "Web Form", "kind": "classic_command"},
    "WebFormItem": {
        "type": "4D.WebFormItem",
        "expr": "Web Form.myButton",
        "kind": "property_of",
    },
    "WebServer": {"type": "4D.WebServer", "expr": "WEB Server", "kind": "classic_command"},
    "WebSocket": {
        "type": "4D.WebSocket",
        "expr": '4D.WebSocket.new("wss://example.com/socket"; cs.SynthOOPHandler.new())',
        "kind": "constructor",
    },
    "WebSocketConnection": {
        "type": "4D.WebSocketConnection",
        "kind": "typed_declaration_only",
        "callback": "Function onConnection($connection : 4D.WebSocketConnection)",
    },
    "WebSocketServer": {
        "type": "4D.WebSocketServer",
        "expr": "4D.WebSocketServer.new(cs.SynthOOPHandler.new())",
        "kind": "constructor",
    },
    "ZipArchive": {
        "type": "4D.ZipArchive",
        "expr": 'ZIP Read archive(File("/PACKAGE/data.zip"))',
        "kind": "classic_command",
    },
    # The IR's recipe reads `$archive.root.file("README.md")`, but `.file()` is
    # inherited from Directory and its documented return type is 4D.File, so
    # tool4d rejects the assignment ("Impossible to cast 4D.File to
    # 4D.ZipFile."). `.files()` returns a collection of the archive's ZipFile
    # entries, which is the shape that actually type-checks.
    "ZipFile": {
        "type": "4D.ZipFile",
        "lines": [
            "var $zipArchive : 4D.ZipArchive",
            '$zipArchive:=ZIP Read archive(File("/PACKAGE/data.zip"))',
        ],
        "expr": "$zipArchive.root.files()[0]",
        "kind": "property_of",
    },
    "ZipFolder": {
        "type": "4D.ZipFolder",
        "lines": [
            "var $zipArchive : 4D.ZipArchive",
            '$zipArchive:=ZIP Read archive(File("/PACKAGE/data.zip"))',
        ],
        "expr": "$zipArchive.root",
        "kind": "property_of",
    },
    # ORDA templates: the IR models them as templates over the project's own
    # data model, so the check project's catalog supplies the concrete names.
    "cs.<DataClass>": {
        "type": "4D.DataClass",
        "expr": "ds.SynthTable",
        "kind": "property_of",
    },
    "cs.<DataClass>Entity": {
        "type": "cs.SynthTableEntity",
        "expr": "ds.SynthTable.new()",
        "kind": "class_function",
    },
    "cs.<DataClass>Selection": {
        "type": "cs.SynthTableSelection",
        "expr": "ds.SynthTable.all()",
        "kind": "class_function",
    },
}


# ---------------------------------------------------------------------------
# Value synthesis
# ---------------------------------------------------------------------------

# 4D literals for the IR's scalar concrete type names. A type absent here has
# no literal form and goes through the declared-variable path instead.
CONCRETE_LITERALS = {
    "Text": '"synthText"',
    "String": '"synthText"',
    "Integer": "1",
    "Longint": "1",
    "Real": "1",
    "Number": "1",
    "Boolean": "True",
    "Date": "!2024-01-15!",
    "Time": "?12:00:00?",
    "Object": "New object",
    "Collection": "New collection",
}

# `var $x : <keyword>` declaration types for IR concrete type names that have
# no literal (or that a param needs as an addressable variable).
DECLARABLE_TYPES = {
    "Blob": "Blob",
    "Picture": "Picture",
    "Variant": "Variant",
}

# IR type name -> the 4D type keyword used to DECLARE a variable of it. Class
# types declare as themselves (`var $f : 4D.File`); the ORDA generated classes
# declare against the check project's own catalog.
DECLARE_TYPE_OVERRIDES = {
    "Number": "Real",
    "String": "Text",
    "Longint": "Integer",
    "cs.DataStore": "4D.DataStore",
    "4D.Object": "Object",
    "4D.Entity": "cs.SynthTableEntity",
    "4D.EntitySelection": "cs.SynthTableSelection",
    "4D.DataStore": "4D.DataStore",
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Param names that are legal 4D identifier fragments but are known, from an
# actual tool4d diagnostic, to misbehave as a synthesized local's name prefix.
# Empty until a full-corpus run surfaces one -- do not guess entries in.
PARAM_NAME_DENYLIST: set[str] = set()


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def sanitize_param_ident(name: str | None) -> str | None:
    if not name or not isinstance(name, str):
        return None
    if not _IDENT_RE.match(name):
        return None
    if name in PARAM_NAME_DENYLIST:
        return None
    return name


def sanitize_method_name(member_id: str) -> str:
    """Derive a legal, collision-free 4D method name from an IR member id.

    4D identifiers cap at 31 characters and OOP ids are long
    (`EntitySelection.orderByFormula` is 30 on its own), so the name is
    truncated and disambiguated with a hash of the FULL id -- two ids that
    collide after truncation therefore still get distinct files.
    """
    base = re.sub(r"[^A-Za-z0-9_]", "_", member_id)
    name = f"{FILE_PREFIX}{base}"
    if len(name) > 31:
        digest = hashlib.sha1(member_id.encode()).hexdigest()[:4]
        name = f"{name[:31 - 5]}_{digest}"
    return name


class SynthContext:
    """Per-member mutable state threaded through value synthesis.

    One context is shared by every block in a member's file (they all land in
    the same 4D method scope), so `fresh_name` never reuses an identifier
    across blocks -- 4D reports "Redefinition of variable" otherwise.
    `prelude` is reset per block.
    """

    def __init__(self, member_id: str):
        self.member_id = member_id
        self.prelude: list[str] = []
        self.counter = 0
        self.declared: set[str] = set()
        # enum name -> value name, set for one enum-sweep variant at a time.
        self.enum_override: dict[str, str] = {}

    def fresh_name(self, prefix: str) -> str:
        self.counter += 1
        return f"${prefix}{self.counter}"

    def fresh_name_for(self, param_name: str | None, fallback: str) -> str:
        return self.fresh_name(sanitize_param_ident(param_name) or fallback)

    def declare(self, name: str, type_keyword: str) -> None:
        if name not in self.declared:
            self.declared.add(name)
            self.prelude.append(f"var {name} : {type_keyword}")


# Declaration keyword for the IR's `pseudo` types. `any` is the doc's "value of
# any type", which 4D declares as `Variant`; `Expression` is a first-class
# formula, whose declared type is 4D.Function. `var $x : any` is not valid 4D
# and the compiler rejects it with a bare "Syntax error".
PSEUDO_DECLARE_TYPES = {
    "any": "Variant",
    "Variant": "Variant",
    "Expression": "4D.Function",
}


def declare_keyword(type_name: str) -> str:
    """4D declaration keyword for an IR concrete type name."""
    if type_name in DECLARE_TYPE_OVERRIDES:
        return DECLARE_TYPE_OVERRIDES[type_name]
    if type_name in PSEUDO_DECLARE_TYPES:
        return PSEUDO_DECLARE_TYPES[type_name]
    return type_name


def declare_keyword_for(type_obj) -> str:
    """Declaration keyword for a whole TypeRef (the shape used to capture a
    return value or a property read)."""
    if isinstance(type_obj, list):
        return declare_keyword_for(type_obj[0])
    if not isinstance(type_obj, dict):
        return "Variant"
    kind = type_obj.get("kind")
    if kind == "pseudo":
        return PSEUDO_DECLARE_TYPES.get(type_obj.get("name"), "Variant")
    if kind == "enum_ref":
        # Enum members are always Integer-valued in the OOP corpus.
        return "Integer"
    if kind == "literal_symbols":
        return "Variant"
    return declare_keyword(type_obj.get("name") or "Variant")


def enum_literal(ir, enum_name: str, ctx: SynthContext) -> str:
    values = ir["enums"][enum_name]["values"]
    forced = ctx.enum_override.get(enum_name)
    if forced:
        return forced
    return values[0]["name"]


def build_arg(ir, type_obj, ctx: SynthContext, param_name: str | None = None) -> str:
    """Return a 4D expression for one parameter, given its TypeRef.

    A `list` type_obj (a union) resolves to its first alternative; the OOP IR
    has none today (see the module docstring), but the branch is kept so a
    future IR that grows one degrades to a valid call rather than crashing.
    """
    if isinstance(type_obj, list):
        return build_arg(ir, type_obj[0], ctx, param_name)
    if not isinstance(type_obj, dict):
        return '"synthText"'

    kind = type_obj.get("kind")
    if kind == "enum_ref":
        return enum_literal(ir, type_obj["enum"], ctx)
    if kind == "literal_symbols":
        return (type_obj.get("symbols") or ["*"])[0]
    if kind == "pseudo":
        name = type_obj.get("name")
        if name == "Expression":
            # A 4D.Function/Formula value: the documented way to pass an
            # expression as a first-class value.
            return "Formula(1+2)"
        if name == "Variant":
            var = ctx.fresh_name_for(param_name, "variant")
            ctx.declare(var, "Variant")
            return var
        # pseudo:"any" -- a Text literal is the least constrained thing that
        # satisfies every documented "any" param.
        return '"synthText"'

    name = type_obj.get("name") or ""
    if (ctx.member_id, param_name) in REQUIRES_REFERENCE:
        var = ctx.fresh_name_for(param_name, "ref")
        ctx.declare(var, declare_keyword(name))
        return var
    if name in CONCRETE_LITERALS:
        return CONCRETE_LITERALS[name]
    if name in DECLARABLE_TYPES:
        var = ctx.fresh_name_for(param_name, "v")
        ctx.declare(var, DECLARABLE_TYPES[name])
        return var
    if name.startswith("4D.") or name.startswith("cs."):
        class_id = name[3:] if name.startswith("4D.") else name
        recipe = RECEIVER_RECIPES.get(class_id)
        if recipe is not None:
            var = ctx.fresh_name_for(param_name, "arg")
            ctx.declare(var, recipe.get("type", declare_keyword(name)))
            for line in recipe.get("lines", []):
                if line.startswith("var "):
                    # Declarations are file-scoped in 4D, so a helper local a
                    # recipe needs must be declared once across ALL blocks --
                    # re-emitting it is a "Redefinition of variable" warning.
                    declared_name = line.split()[1]
                    if declared_name in ctx.declared:
                        continue
                    ctx.declared.add(declared_name)
                ctx.prelude.append(line)
            if recipe.get("expr"):
                ctx.prelude.append(f"{var}:={recipe['expr']}")
            return var
    # Unknown/unmodelled: declare it at its own name and pass the variable.
    var = ctx.fresh_name_for(param_name, "v")
    ctx.declare(var, declare_keyword(name) or "Variant")
    return var


def build_receiver(ctx: SynthContext, class_id: str) -> tuple[str, list[str]]:
    """Return (receiver expression, comment lines) and push declarations."""
    recipe = RECEIVER_RECIPES[class_id]
    notes: list[str] = []
    if recipe["kind"] == "namespace":
        return recipe["expr"], notes
    var = "$receiver"
    ctx.declare(var, recipe["type"])
    for line in recipe.get("lines", []):
        if line.startswith("var "):
            declared_name = line.split()[1]
            if declared_name in ctx.declared:
                continue
            ctx.declared.add(declared_name)
        ctx.prelude.append(line)
    if recipe["kind"] == "typed_declaration_only":
        notes.append(
            f"// {class_id} instances are only ever supplied by 4D to a callback: "
            f"{recipe['callback']}"
        )
        notes.append(
            "// There is no expression that constructs one, so the receiver is a bare "
            "typed declaration."
        )
    else:
        if recipe["kind"] == "abstract_via_subclass":
            notes.append(
                f"// {class_id} is abstract; synthesized against its concrete subclass "
                f"{recipe['concreteClass']}."
            )
        ctx.prelude.append(f"{var}:={recipe['expr']}")
    return var, notes


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------


def find_enum_refs(params) -> list[str]:
    """Enum names referenced by this overload's params, in order, deduplicated."""
    names: list[str] = []
    for p in params:
        t = p.get("type")
        if isinstance(t, dict) and t.get("kind") == "enum_ref":
            if t["enum"] not in names:
                names.append(t["enum"])
    return names


def brace_group_openers(raw_syntax: str, n_params: int) -> list[bool] | None:
    """Which param slots begin a new `{ ... }` optional group in the raw syntax.

    4D syntax lines encode optionality *positionally and by nesting*:

        .terminate( { code : Integer ; message : Text } )
        4D.MailAttachment.new( file : 4D.File { ; name : Text {; cid : Text { ... } } } )

    In the first, `code` and `message` share ONE group -- they are all-or-
    nothing, and `terminate(1)` is invalid even though the IR (correctly)
    marks both params optional. In the second, each optional param opens its
    own nested group, so every trailing truncation is legal. Distinguishing
    the two is what classic's hand-maintained MUTUALLY_EXCLUSIVE_TRAILING_
    PARAMS denylist encodes; here it is derived from the syntax line instead,
    so it stays correct as the corpus grows.

    Returns one bool per param, or None if the slot count cannot be matched
    (in which case the caller falls back to the conservative rule).
    """
    start = raw_syntax.find("(")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(raw_syntax)):
        ch = raw_syntax[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    region = raw_syntax[start + 1 : end]

    # A `{` binds to the param slot the group actually starts with. When it
    # appears before the current slot has any content (`( { code ; message } )`)
    # the group starts at THIS slot; when it appears after
    # (`( path : Text { ; pathType : Integer } )`) the `{` sits on the
    # separator, so the group starts at the NEXT slot.
    opened: list[bool] = []
    cur_opens = False
    carry = False
    cur_has_content = False
    saw_any = False
    for ch in region:
        if ch == "{":
            if cur_has_content:
                carry = True
            else:
                cur_opens = True
        elif ch == "}":
            continue
        elif ch == ";":
            opened.append(cur_opens)
            cur_opens = carry
            carry = False
            cur_has_content = False
        elif not ch.isspace():
            cur_has_content = True
            saw_any = True
    if saw_any:
        opened.append(cur_opens)
    if len(opened) != n_params:
        return None
    return opened


def find_optional_variants(params, raw_syntax: str = "") -> list[tuple[str, list]]:
    """Optional-param present/omitted sweep candidates.

    The default block passes every param. This yields one truncated param list
    per *legal* omission point, dropping that param and everything after it --
    4D has no named or skipped arguments, so an optional param can only be
    omitted together with every param that follows it.

    Two conditions must both hold for index `i` to be an omission point:

    1. Every param from `i` onward is optional. Without this, omitting a
       LEADING optional param silently drops a required trailing one:
       `.every( { startFrom : Integer ; } formula : 4D.Function )` would be
       truncated to `.every()`, which the compiler rejects -- and would be
       reported as an IR bug when it is really a synthesizer bug.
    2. `i` opens a new brace group (see brace_group_openers), so it is not
       the interior of an all-or-nothing group like `.terminate( { code ;
       message } )`.
    """
    openers = brace_group_openers(raw_syntax, len(params)) if raw_syntax else None
    variants = []
    for i, p in enumerate(params):
        if not p.get("optional"):
            continue
        if not all(q.get("optional") for q in params[i:]):
            continue
        if openers is not None and not openers[i]:
            continue
        name = p.get("name") or f"arg{i}"
        variants.append((f"optional:omit-{name}", params[:i]))
    return variants


def accessor_variants(accessor) -> list[dict]:
    """One entry per alternative in a property's `accessor.type`.

    Nine properties are multi-variant (`Email.to` is `Text|Object|Collection`,
    `Document.original` is `4D.File|4D.Folder`, ...). Sweeping only the first
    alternative would leave the others entirely unexercised -- an assignment of
    the Text variant compiles fine while a wrong Object/Collection variant goes
    undetected -- so every alternative gets its own read and write block.
    """
    t = accessor.get("type")
    return list(t) if isinstance(t, list) else [t]


def type_label(t) -> str:
    if not isinstance(t, dict):
        return "any"
    return t.get("name") or t.get("enum") or t.get("kind") or "any"


# ---------------------------------------------------------------------------
# Block emission
# ---------------------------------------------------------------------------


def synthesize_member(ir, member) -> list[dict]:
    """Return one dict per synthesized block: {variant, overload_index, lines}.

    Every block is self-contained: its own declarations, its own receiver, its
    own call. Blocks share one method scope, so `SynthContext` guarantees
    unique identifiers across the whole file.
    """
    member_id = member["id"]
    class_id = member["receiver"]["classId"]
    ctx = SynthContext(member_id)
    blocks: list[dict] = []

    standin = DYNAMIC_MEMBER_STANDIN.get(member_id)

    def start_block(comment: str) -> list[str]:
        ctx.prelude = []
        return [comment]

    def finish(header: list[str], call_lines: list[str], variant: str, oi: int) -> dict:
        return {
            "overload_index": oi,
            "variant": variant,
            "lines": header + ctx.prelude + call_lines,
        }

    if member["kind"] == "oop_property":
        accessor = member["accessor"]
        variants = accessor_variants(accessor)
        multi = len(variants) > 1
        for vi, vtype in enumerate(variants):
            label = type_label(vtype)
            suffix = f" [{label}]" if multi else ""
            # --- read
            header = start_block(f"// property read{suffix}")
            notes: list[str] = []
            if standin is not None:
                access, forced_type = standin
                if access.startswith("$receiver"):
                    recv, notes = build_receiver(ctx, class_id)
                    access = access.replace("$receiver", recv)
                notes.append(
                    f"// dynamic member: the doc's `{member['memberName']}` is a name "
                    f"pattern, so a concrete member of the check project's own model "
                    f"stands in for it."
                )
                read_type = forced_type or type_label(vtype)
                target = ctx.fresh_name("read")
                ctx.declare(target, declare_keyword(read_type))
                call = [f"{target}:={access}"]
            else:
                recv, notes = build_receiver(ctx, class_id)
                target = ctx.fresh_name("read")
                ctx.declare(target, declare_keyword_for(vtype))
                call = [f"{target}:={recv}{member['memberName']}"]
            blocks.append(
                finish(header + notes, call, f"read{'' if not multi else f':{label}'}", vi)
            )
            # --- write
            if not accessor.get("writable"):
                continue
            if member_id in PROPERTY_WRITE_SKIP or standin is not None:
                continue
            header = start_block(f"// property write{suffix}")
            recv, notes = build_receiver(ctx, class_id)
            value = build_arg(ir, vtype, ctx, member["memberName"].lstrip("."))
            call = [f"{recv}{member['memberName']}:={value}"]
            blocks.append(
                finish(header + notes, call, f"write{'' if not multi else f':{label}'}", vi)
            )
        return blocks

    # --- callables (functions and constructors)
    for oi, overload in enumerate(member.get("overloads", [])):
        params = overload.get("params", [])

        def render(variant: str, comment: str, call_params) -> dict:
            header = start_block(comment)
            notes: list[str] = []
            if member["receiver"]["kind"] == "class":
                call_target = f"{member['displayName']}"
            else:
                recv, notes = build_receiver(ctx, class_id)
                call_target = f"{recv}{member['memberName']}"
            args = [
                build_arg(ir, p.get("type"), ctx, p.get("name")) for p in call_params
            ]
            call_expr = f"{call_target}({'; '.join(args)})"
            returns = overload.get("returns")
            if returns:
                result = ctx.fresh_name("result")
                ctx.declare(result, declare_keyword_for(returns))
                call = [f"{result}:={call_expr}"]
            else:
                call = [call_expr]
            return finish(header + notes, call, variant, oi)

        blocks.append(render("default", f"// overload {oi}", params))

        for enum_name in find_enum_refs(params):
            values = ir["enums"][enum_name]["values"]
            for value in values[1:]:
                ctx.enum_override = {enum_name: value["name"]}
                blocks.append(
                    render(
                        f"enum:{enum_name}={value['name']}",
                        f"// overload {oi} [enum {enum_name} = {value['name']}]",
                        params,
                    )
                )
            ctx.enum_override = {}

        for variant, call_params in find_optional_variants(params, overload.get("rawSyntax", "")):
            blocks.append(render(variant, f"// overload {oi} [{variant}]", call_params))

    return blocks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_target_ids(ir, by_id, args) -> tuple[list[str], bool]:
    if getattr(args, "ids", None):
        wanted = [x.strip() for x in args.ids.split(",") if x.strip()]
        unknown = [x for x in wanted if x not in by_id]
        if unknown:
            raise SystemExit(f"unknown member id(s): {', '.join(unknown)}")
        excluded = [x for x in wanted if x in EXCLUDED_MEMBERS]
        if excluded:
            raise SystemExit(
                f"member(s) permanently excluded from this stage: {', '.join(excluded)} "
                "-- see EXCLUDED_MEMBERS in this file for the evidence"
            )
        return wanted, True
    if getattr(args, "cls", None):
        wanted = [
            c["id"]
            for c in ir["commands"]
            if c["receiver"]["classId"] == args.cls and c["id"] not in EXCLUDED_MEMBERS
        ]
        if not wanted:
            raise SystemExit(f"no members for class {args.cls!r}")
        return wanted, True
    return [c["id"] for c in ir["commands"] if c["id"] not in EXCLUDED_MEMBERS], False


def check_receiver_table(ir) -> None:
    """Gate: the recipe table and the IR's `classes{}` must agree on the class
    set, so a class added upstream can never silently go unsynthesized."""
    ir_classes = set(ir["classes"])
    table = set(RECEIVER_RECIPES)
    missing = sorted(ir_classes - table)
    extra = sorted(table - ir_classes)
    if missing:
        raise SystemExit(
            "RECEIVER_RECIPES is missing a recipe for: " + ", ".join(missing)
        )
    if extra:
        raise SystemExit("RECEIVER_RECIPES has recipes for unknown classes: " + ", ".join(extra))
    used = {c["receiver"]["classId"] for c in ir["commands"]}
    unknown = sorted(used - table)
    if unknown:
        raise SystemExit("members reference classes with no recipe: " + ", ".join(unknown))


def _split_args(arg_text: str) -> int:
    """Count top-level `;`-separated arguments in a rendered call."""
    if not arg_text.strip():
        return 0
    depth = 0
    n = 1
    in_str = False
    for ch in arg_text:
        if ch == '"':
            in_str = not in_str
        elif in_str:
            continue
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == ";" and depth == 0:
            n += 1
    return n


def verify_emission(ir, by_id, manifest, target_ids) -> None:
    """GATE: re-read what was written to disk and prove it matches the IR.

    This exists because of a review finding on the previous stage: a check
    that only asks "did the emitter produce a file, and did the compiler run
    over it?" is satisfied by output that has silently lost or mangled data.
    So the file is parsed back and each block's CALL LINE is compared against
    the IR entry it claims to exercise:

      * the member's own name appears in the call;
      * the number of arguments equals the number of params the block's
        variant intended to pass.

    A synthesizer that drops a param, calls the wrong member, or writes a
    block whose manifest line range has drifted fails here rather than
    sailing through a green check-syntax run.
    """
    problems: list[str] = []
    for rel, info in manifest["files"].items():
        if info["member_id"] not in set(target_ids):
            continue
        member = by_id[info["member_id"]]
        path = PROJECT_DIR / rel
        if not path.exists():
            problems.append(f"{rel}: manifest lists a file that is not on disk")
            continue
        lines = path.read_text().splitlines()
        blocks = info["blocks"]
        for pos, block in enumerate(blocks):
            start = block["comment_line"] - 1
            body = lines[start : start + block["lines"]]
            if len(body) != block["lines"]:
                problems.append(f"{rel}: block {pos} line range runs past end of file")
                continue
            call = body[-1]
            standin = DYNAMIC_MEMBER_STANDIN.get(member["id"])
            if standin is not None:
                # A dynamic member has no fixed name to look for; what must be
                # true is that the block uses the registered stand-in, and that
                # the block says so in a comment so no reader mistakes the
                # concrete name for the documented one.
                access = standin[0].replace("$receiver", "$receiver")
                probe = access.split(".")[-1]
                if probe not in call:
                    problems.append(
                        f"{rel}: block {pos} does not use the registered stand-in "
                        f"{standin[0]!r}"
                    )
                elif not any("dynamic member:" in line for line in body):
                    problems.append(
                        f"{rel}: block {pos} uses a dynamic-member stand-in without "
                        "the explanatory comment"
                    )
                continue
            name = member["memberName"].lstrip(".")
            if name not in call and member["displayName"] not in call:
                problems.append(
                    f"{rel}: block {pos} ({block['variant']}) call {call!r} does not "
                    f"mention {name!r}"
                )
                continue
            if member["kind"] == "oop_property":
                continue
            expected = expected_arity(member, block)
            open_paren = call.find("(", call.find(name))
            if open_paren < 0:
                problems.append(f"{rel}: block {pos} call {call!r} has no argument list")
                continue
            got = _split_args(call[open_paren + 1 : call.rfind(")")])
            if got != expected:
                problems.append(
                    f"{rel}: block {pos} ({block['variant']}) passes {got} argument(s) "
                    f"but the IR overload intends {expected}"
                )
    if problems:
        for line in problems[:40]:
            print("  " + line, file=sys.stderr)
        raise SystemExit(
            f"emission-equality gate FAILED: {len(problems)} block(s) on disk disagree "
            "with the IR they claim to exercise"
        )
    print(f"emission-equality gate: OK ({len(target_ids)} member(s) re-read from disk)")


def expected_arity(member, block) -> int:
    """How many arguments the block's variant intends to pass."""
    params = member["overloads"][block["overload_index"]]["params"]
    variant = block["variant"]
    if variant.startswith("optional:omit-"):
        name = variant[len("optional:omit-") :]
        for i, p in enumerate(params):
            if (p.get("name") or "") == name:
                return i
    return len(params)


def cmd_generate(args) -> int:
    ir = load_json(IR_PATH)
    check_receiver_table(ir)
    by_id = {c["id"]: c for c in ir["commands"]}
    target_ids, subset = resolve_target_ids(ir, by_id, args)

    METHODS_DIR.mkdir(parents=True, exist_ok=True)
    if subset and MANIFEST_PATH.exists():
        manifest = load_json(MANIFEST_PATH)
        manifest.setdefault("files", {})
    else:
        manifest = {"files": {}}

    names_seen: dict[str, str] = {}
    for member_id in target_ids:
        member = by_id[member_id]
        method = sanitize_method_name(member_id)
        if method in names_seen and names_seen[method] != member_id:
            raise SystemExit(
                f"method-name collision: {member_id} and {names_seen[method]} "
                f"both map to {method}"
            )
        names_seen[method] = member_id
        blocks = synthesize_member(ir, member)
        lines = [line for b in blocks for line in b["lines"]]
        (METHODS_DIR / f"{method}.4dm").write_text("\n".join(lines) + "\n")

        starts = []
        cursor = 1
        for b in blocks:
            starts.append(
                {
                    "overload_index": b["overload_index"],
                    "variant": b["variant"],
                    "comment_line": cursor,
                    "lines": len(b["lines"]),
                }
            )
            cursor += len(b["lines"])
        manifest["files"][f"Sources/Methods/{method}.4dm"] = {
            "member_id": member_id,
            "kind": member["kind"],
            "class_id": member["receiver"]["classId"],
            "blocks": starts,
        }

    manifest["target_ids"] = (
        sorted(set(manifest.get("target_ids", [])) | set(target_ids)) if subset else target_ids
    )
    manifest["excluded"] = EXCLUDED_MEMBERS

    if not subset:
        wanted = set(manifest["files"])
        for stale in sorted(METHODS_DIR.glob(f"{FILE_PREFIX}*.4dm")):
            rel = f"Sources/Methods/{stale.name}"
            if rel not in wanted:
                stale.unlink()
                print(f"removed stale {stale.relative_to(ROOT)}")

    verify_emission(ir, by_id, manifest, target_ids)

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    total_blocks = sum(len(v["blocks"]) for v in manifest["files"].values())
    print(f"{len(target_ids)} member(s), {total_blocks} block(s) -> {MANIFEST_PATH.relative_to(ROOT)}")
    return 0


LSP_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def run_check_syntax(anchor: str | None = None) -> list[dict]:
    """One project-wide `experimental/checkSyntax` pass over the check project."""
    if not TOOL4D_LSP.exists():
        raise SystemExit(
            "tools/tool4d-lsp-stdio not found -- provision it per skills/4dtools/SKILL.md"
        )
    cmd = [
        str(TOOL4D_LSP),
        "check-syntax",
        "--json",
        "--workspace",
        str(PROJECT_DIR.relative_to(ROOT)) + "/",
    ]
    if anchor:
        cmd.append(anchor)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    if proc.returncode not in (0, 1):
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"tool4d-lsp-stdio exited with code {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stdout[:4000], file=sys.stderr)
        print(proc.stderr[-4000:], file=sys.stderr)
        raise


def diagnostics_by_relpath(per_file: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for entry in per_file:
        rel = entry["uri"].split("/Project/", 1)[-1]
        out[rel] = entry["diagnostics"]
    return out


def cmd_validate(args) -> int:
    if not MANIFEST_PATH.exists():
        raise SystemExit("out/oop_synth_manifest.json not found -- run 'generate' first")
    ir = load_json(IR_PATH)
    by_id = {c["id"]: c for c in ir["commands"]}
    manifest = load_json(MANIFEST_PATH)
    target_ids, _ = resolve_target_ids(ir, by_id, args)
    target_set = set(target_ids)
    subset = target_set != set(manifest.get("target_ids", []))

    rel_paths = sorted(
        rel for rel, info in manifest["files"].items() if info["member_id"] in target_set
    )
    if not rel_paths:
        raise SystemExit("no generated files match the request -- run 'generate' first")

    per_file = run_check_syntax(rel_paths[0])
    diags = diagnostics_by_relpath(per_file)
    print(f"check-syntax: {len(per_file)} file(s) in project, {len(rel_paths)} targeted", file=sys.stderr)

    # Hand-off equality check (see pipeline/stage6_README.md and the review
    # lesson about lossy hand-offs): the compiler must have SEEN every file
    # this run claims to have validated. A file missing from the response is
    # not "clean", it is unverified, and silently counting it as clean is
    # exactly the class of gap this pipeline is built to avoid.
    unseen = [rel for rel in rel_paths if rel not in diags]
    if unseen:
        raise SystemExit(
            f"{len(unseen)} generated file(s) were not covered by the check-syntax "
            f"response and cannot be reported as clean, e.g. {unseen[:3]}"
        )

    run_report = []
    for rel in rel_paths:
        info = manifest["files"][rel]
        file_diags = diags.get(rel, [])
        starts = info["blocks"]
        for pos, block in enumerate(starts):
            start = block["comment_line"]
            end = (
                starts[pos + 1]["comment_line"] if pos + 1 < len(starts) else float("inf")
            )
            matched = [
                {
                    "message": d["message"],
                    "severity": LSP_SEVERITY.get(d.get("severity"), d.get("severity")),
                    "line": d["range"]["start"]["line"] + 1,
                }
                for d in file_diags
                if start <= d["range"]["start"]["line"] + 1 < end
            ]
            status = "clean"
            if any(d["severity"] == "error" for d in matched):
                status = "error"
            elif matched:
                status = "warning"
            run_report.append(
                {
                    "id": info["member_id"],
                    "kind": info["kind"],
                    "variant": block["variant"],
                    "overload_index": block["overload_index"],
                    "file": rel,
                    "diagnostics": matched,
                    "status": status,
                }
            )

    if subset and REPORT_PATH.exists():
        prior = load_json(REPORT_PATH)
        report = [r for r in prior if r["id"] not in target_set] + run_report
    else:
        report = run_report
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")

    n_err = sum(1 for r in run_report if r["status"] == "error")
    n_warn = sum(1 for r in run_report if r["status"] == "warning")
    n_clean = sum(1 for r in run_report if r["status"] == "clean")
    print(
        f"{len(run_report)} block(s) checked: {n_clean} clean, {n_warn} warning-only, "
        f"{n_err} error"
    )
    print(f"-> {REPORT_PATH.relative_to(ROOT)}")
    return 0


def cmd_report(args) -> int:
    if not REPORT_PATH.exists():
        raise SystemExit("out/oop_lsp_crosscheck_report.json not found -- run 'validate' first")
    report = load_json(REPORT_PATH)
    if getattr(args, "ids", None):
        wanted = {x.strip() for x in args.ids.split(",")}
        report = [r for r in report if r["id"] in wanted]
    if getattr(args, "cls", None):
        ir = load_json(IR_PATH)
        by_id = {c["id"]: c for c in ir["commands"]}
        report = [
            r
            for r in report
            if by_id.get(r["id"], {}).get("receiver", {}).get("classId") == args.cls
        ]
    shown = 0
    for r in report:
        if r["status"] == "clean":
            continue
        shown += 1
        print(f"{r['id']} [{r['variant']}] {r['status']}  ({r['file']})")
        for d in r["diagnostics"]:
            print(f"    {d['severity']}: {d['message']} (line {d['line']})")
    print(f"{shown} non-clean block(s) of {len(report)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="write synthetic .4dm files + manifest")
    val = sub.add_parser("validate", help="run tool4d check-syntax and write the report")
    rep = sub.add_parser("report", help="print non-clean blocks")
    for p in (gen, val):
        p.add_argument("--all", action="store_true", help="target every IR member (default)")
        p.add_argument("--ids", help="comma-separated member ids")
        p.add_argument("--class", dest="cls", help="target every member of this class id")
    rep.add_argument("--ids", help="comma-separated member ids to filter to")
    rep.add_argument("--class", dest="cls", help="filter to this class id")
    args = parser.parse_args()
    return {"generate": cmd_generate, "validate": cmd_validate, "report": cmd_report}[
        args.command
    ](args)


if __name__ == "__main__":
    raise SystemExit(main())

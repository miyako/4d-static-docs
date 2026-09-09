# `pipeline/oop/` — the 4D OOP intermediate representation

This pipeline builds `out/4d-oop-ir.json`: a machine-readable description of
the 45 built-in 4D OOP classes and their 502 in-scope members, in the same
three-layer shape as the classic-language IR (`out/4d-command-ir.json`) and
validating against the same schema (`references/4d-command-ir-schema.json`).

The two IRs are **separate documents** by design. Edges that span them live in
`out/4d-ir-crosslinks.json`. See `PLAN.md` for the full multi-session brief and
`SCOPE.md` for what is in and out of scope, with reasons.

Everything here is pure Python with no 4D dependency. From a clean clone:

```sh
pip install -r pipeline/requirements.txt
python3 pipeline/oop/stage0_reconcile.py
python3 pipeline/oop/stage0_manifest.py
python3 pipeline/oop/stage1_extract.py
python3 pipeline/oop/stage2_signatures.py     # GATE G1
python3 pipeline/oop/stage2b_crosscheck.py
python3 pipeline/oop/stage3_merge.py
python3 pipeline/oop/stage4_classes.py
python3 pipeline/oop/stage5_assemble.py       # GATE G3 + schema validation
python3 pipeline/oop/stage6_crosslinks.py
python3 pipeline/oop/check_schema_gate.py     # GATE G2
```

Every stage is idempotent: re-running with unchanged inputs rewrites identical
output and reports a zero diff.

## Sources

Two independent sources are joined, and their disagreement is the accuracy
floor for the whole corpus:

| Source | What it gives | Notes |
|---|---|---|
| `references/syntaxEN.json` | authoritative member list and `Syntax` strings | 45 class keys + `4D` (19 constructors) + `_command_` (classic, ignored) |
| `mirror/docs/21-R3/API/*.html` | prose, Parameter tables, History tables, See also, constants | 45 pages |

Both are pinned to **21-R3**. The pinning is recorded in `out/oop_manifest.json`,
and `--syntax-json` lets a future capture be swapped in.

`syntaxEN.json` member keys carry no leading dot (`at()`); API headings do
(`.at()`), and every heading carries a trailing `U+200B`. `oop.join_key()` and
`oop.strip_zws()` normalise this. Nine class maps carry a **string-valued**
`_inheritedFrom_` key that encodes the superclass and must be filtered out when
iterating members.

## Stages

### O0 — reconcile (`stage0_reconcile.py`) → `out/oop_source_diff.json`

Joins the API-page member headings against the `syntaxEN.json` keys, class by
class, and forces every mismatch into a category with evidence. Nothing is
dropped silently.

### O0b — manifest (`stage0_manifest.py`) → `out/oop_manifest.json`

The in-scope member list plus `skipped[]`, each skip carrying a reason. This is
the list GATE G3 checks the final IR against.

Flags: `--docs-root`, `--version`, `--syntax-json`.

### O1 — extract (`stage1_extract.py`) → `out/oop_stage1_raw.json`

Parses each API page into per-member sections: description prose, Parameter
table, syntax paragraphs, History table, See also, constant tables, code spans.
Cached under `cache/oop/raw/` keyed by page content hash.

`WebForm` and `WebFormItem` use `<h3>` for members; the other 43 pages use
`<h2>`. `Transporter` has no page at all — it is an abstract base whose 11
members are documented on the three concrete transporter pages.

### O2 — signatures (`stage2_signatures.py`, `syntaxparse.py`) → `out/oop_signatures.json`

A real tokenizer and recursive-descent parser for the `Syntax` grammar — not
regexes. The tokenizer is **trivia-preserving**: every token records its exact
text plus the whitespace before it, and the scanner asserts it consumed 100% of
the line. `render()` then walks the *AST*, collecting the token indices each
node claims, and asserts they equal the full token range in order — so a parser
that silently dropped a token fails loudly instead of round-tripping by
accident.

**GATE G1**: every parsed AST re-renders byte-identically to its source line.
Current result: **591/591 overload lines, 495/495 full `Syntax` fields**. Zero
normalisations were needed. Report in `out/oop_roundtrip_report.json`.

Grammar features handled: `<br/>`-separated overloads, `{}` optionality nesting
to depth 4 (including braces wrapping a leading `;`), `name : Type` pairs, a
trailing `: ReturnType`, variadic ellipsis in both positions, bare literal `*`
parameters, and three markdown-emphasis typos in the source docs.

### O2b — cross-check (`stage2b_crosscheck.py`) → `out/oop_param_conflicts.json`

Validates the O2 AST against each member's Parameter table: names, types,
direction, and the `Result` row against the parsed return type. Four
source-convention normalisations are applied and **named in the report** rather
than hidden: union types spelled `"Text, Blob"`, variadic `elementN` vs
`element`, parameter-name capitalisation drift, and `"undefined"`/`"null"` in
the Result row (consumed downstream as `Overload.returnsNullable`).

### O3 — merge (`stage3_merge.py`) → `out/oop_stage3_ir_full/`, `out/oop_enums.json`

Builds one `CommandEntry` per member by merging the parsed signature with the
HTML enrichment: `summary`/`description`, `constraints`, `errorModel`,
`returnsShape`, `sinceVersion`/`deprecated`/`versionBehaviorChanges` from
History tables, and See also edges.

The highest-value enrichment is resolving constant mentions against
`references/4d-constants-registry.json` so numeric parameters become
`enum_ref` instead of bare `Integer`. Three resolution paths in decreasing
confidence:

1. constants backticked in the parameter's own description;
2. a `Constant/Value/Comment` table whose sub-heading names the parameter;
3. a positional fallback, which fires only when the member has exactly one
   generically-titled constant table **and** exactly one numerically-typed
   parameter **and** that parameter's own description named no constants.

Prose association additionally requires the paragraph to refer to the name *as
a parameter*; a bare name match wrongly attributed `dk status stamp has
changed` to `Entity.save.mode`. Generated enums are **member-scoped**
(`Entity.save.mode`) rather than pointing at a whole registry theme, which
would overstate the accepted set.

Only an exact `"Added"` History marker marks introduction — `"Added status 7
and 8"` had back-dated `Entity.save` from 17 to 21.

### Multi-variant properties

Nine properties declare several `<br/>`-separated type variants — `Email.bcc`
is `Text` **or** `Object` **or** `Collection`, `Document.original` is
`4D.File` **or** `4D.Folder`. They are the property-side analogue of function
overloads, and the merge step originally kept only the first, which both
truncated `accessor.rawSyntax` and, more seriously, **narrowed
`accessor.type`**: the IR said assigning a collection of recipients to
`.bcc` was invalid when it is ordinary 4D.

`Accessor.type` therefore takes either a bare `TypeRef` or an array of them
(`minItems: 2` — a one-element array is rejected rather than accepted as an
alternative spelling of the single case). The same single-signature assumption
had to be fixed in four places: the accessor type, the accessor `rawSyntax`,
the property constant-table enum upgrade (guarded now, since a
`Number | Text` property is not a constant selector), and O4's
`returns_instance_of` edges, which must emit one edge per variant.

This class of defect is worth calling out because **no compiler check can
catch it**. A narrowed type still produces code that compiles; downstream
`check-syntax` passes go green while the IR quietly misinforms. Only comparison
against the documented source finds it, which is why the gate asserts equality.

### O4 — classes (`stage4_classes.py`) → `out/oop_classes.json`, `out/oop_relationships.json`

Builds the root-level `classes{}` Layer-2 table and the Layer-3 `member_of` /
`returns_instance_of` / `obtained_via` edges.

`instantiation` — how a caller actually obtains an instance — is hand-authored
in `class_instantiation.json`, one entry per class, each recipe carrying a
runnable `$`-prefixed 4D expression, `producedBy`, `requires` and a `_reason`
citing its evidence. This is the artifact downstream example synthesis depends
on, so the stage **exits non-zero if any class lacks an authored recipe**.

ORDA generated classes (`cs`, `cs.<DataClass>`, `cs.<DataClass>Entity`,
`cs.<DataClass>Selection`) are modelled as four `isTemplate` entries, not as
per-table entries.

### O5 — assemble (`stage5_assemble.py`) → `out/4d-oop-ir.json`

Concatenates the entries, applies semantic overlays, strips internal `_`-keys,
asserts no id collides with the classic corpus, runs **GATE G3**, validates
against the schema, and writes a fingerprint diff against the previous run.

### O6 — crosslinks (`stage6_crosslinks.py`) → `out/4d-ir-crosslinks.json`

Cross-corpus edges. `classic_equivalent` pairs are **curated**, never inferred
from name similarity — `Collection.copy` and `COPY ARRAY` are not equivalents.
`obtained_via` edges are mined from the `producedBy` of instantiation recipes
that name a classic command. Endpoints carry an explicit `corpus`.

## Semantic overlays

Machine-extracted output is never hand-edited in place. Hand judgement goes in
`semantic_overlays/<id>.json`, merged at O5, and **every overlay must carry a
`_reason`** — O5 refuses to run otherwise. An overlay may also supply `_enums`
when it introduces an `enum_ref` that O3 could not derive.

The three current overlays all resolve O2b conflicts: `4D.File.new` and
`4D.Folder.new` (no Parameter table on the page, so their constant parameters
stayed bare `Integer`) and `4D.TCPConnection.new` (`serverPort` spelled Real in
the Syntax line, Integer in the table).

## Caching and idempotency

Per-member sha1 over **both** sources under `cache/oop/`, so a member whose
sources are unchanged is not re-derived. O5 reports `+added -removed ~changed`
against the previous run's fingerprints, which is what makes a docs refresh
reviewable rather than a wall of diff. See `pipeline/MAINTENANCE.md`.

## Gates

| Gate | Meaning | Checked by | Result |
|---|---|---|---|
| **G1** | 100% byte-exact syntax round-trip | `stage2_signatures.py` | 591/591 lines, 495/495 fields |
| **G2** | the bumped schema still validates the classic corpus byte-unchanged | `check_schema_gate.py` | PASSED |
| **G3** | every in-scope member is in the IR or explicitly skipped | `stage5_assemble.py` | 502/502, 5 logged skips |
| — | every non-dynamic member reconstructs to its syntaxEN source byte-for-byte | `check_schema_gate.py` | 495/495 (277 + 218) |

`check_schema_gate.py` also validates both example documents and the OOP IR
itself, and exercises the new conditional requirements with deliberate negative
cases so they cannot silently rot into decoration.

It additionally asserts the **verbatim-source invariant**: every non-dynamic
member, reconstructed from the IR alone, must be **byte-identical to its
`Syntax` field in `syntaxEN.json`** — callables by `<br/>`-joining every
`overloads[].rawSyntax`, properties by reading `accessor.rawSyntax`, since a
property has no overload to hang it off.

Equality, not presence, is the assertion, and the difference mattered. The
first version of this check only asked whether *a* line was present. It passed
while nine multi-variant properties were silently truncated to their first
`<br/>` variant, because the merge step assumed a property has exactly one
signature. Only a byte comparison against the source of truth catches that.

The check carries four negative probes, covering every path the bug could hide
in: a property with no line, a callable with no line, a multi-variant property
truncated to its first variant, and a multi-overload function truncated to its
first overload. It fails the gate if any probe goes undetected — an assertion
nobody has seen fail is not yet evidence.

JSON Schema validation uses `boon` (provision via the `4dtools` skill), with
Python `jsonschema` as a cross-check.

## `classes[].typeName` is compiler-verified, not inferred

`typeName` is the name a caller writes in a declaration (`var $x : 4D.File`).
For 44 of the 50 classes it is a `4D.*` name; the other six are `Collection`,
the `4D`/`cs` namespaces and the three `cs.<DataClass>*` ORDA templates, which
have no fixed `4D.*` spelling.

All 44 are verified against tool4d rather than assumed, because the compiler
answers this question exactly and a hand-authored table does not. The probe
declares one variable per class plus a deliberately fabricated control:

```4d
var $v1 : 4D.Blob
// ... one line per class ...
var $ctrl1 : 4D.NotARealClassAbc
```

then runs `tool4d-lsp-stdio check-syntax` over the check project. An unknown
class is reported as `The class <name> is unknown.`, so a clean run for the 44
real names *with the control flagged* is positive evidence. Without the
control the run proves nothing — a check-syntax pass over an unopened path
looks identical to a check that was never performed.

This caught two wrong entries that no other gate could see. `Document` and
`Directory` were recorded as `4D.File` and `4D.Folder`: the type names of one
of their two concrete subclasses. That was arbitrary (`File` vs `ZipFile`,
`Folder` vs `ZipFolder`) and, more importantly, false. tool4d accepts
`var $x : 4D.Document`, accepts assigning a `File` to it, and rejects
`4D.DocumentX` — so these are real class-store types, and `4D.Document` is the
correct declaration type for a value that may be either subclass. The original
note claimed "callers never name it", which the compiler disproves; recording a
subclass's type there actively denied consumers a legal declaration.

`isAbstract` stays `true` for both. The docs present them as base classes
reached through their subclasses, and that is what the flag records —
instantiation guidance, not whether the type may be named. Note that
`check-syntax` cannot settle the instantiation half: `4D.Document.new()`
compiles clean, but so does every class-store `.new`, whereas
`4D.File.totallyBogusStatic()` is rejected — so the class-store path *is*
checked for arbitrary members and `.new` simply resolves everywhere. Compile
success there is therefore not evidence of runtime instantiability, and the
flag continues to follow the documentation.

## `docPage` is an official permalink, not a mirror path

The pipeline parses the local docs mirror, so every stage up to assembly
carries paths like `mirror/docs/21-R3/API/SMTPTransporterClass.html`. That
path is meaningless to a consumer of the redistributable IR, which ships
without the mirror, so stage 5 rewrites it to the official page:

```
docPage       https://developer.4d.com/docs/API/SMTPTransporterClass
docPageLocal  mirror/docs/21-R3/API/SMTPTransporterClass.html
```

The mirror path is preserved as `docPageLocal` rather than discarded,
because it is the provenance record of the file actually parsed and is
what makes a re-derivation reproducible.

**The URL deliberately omits the version segment.** `/docs/21-R3/API/...`
resolves today but stops resolving once 21-R3 is superseded, so embedding
it in a redistributable artifact would make the artifact rot on 4D's
release schedule rather than on ours. The version-less form always points
at the current documentation for the class.

All 45 class pages were checked against the live site rather than assumed
to follow the naming convention: every one returns 200 at
`https://developer.4d.com/docs/API/<PageName>`, and a fabricated control
(`.../API/NotARealClassXyz`) returns a genuine 404 with a "Page Not Found"
body. The control matters because a Docusaurus site can serve a soft 404
with a 200 status, in which case a sweep of real names would look
identical to a sweep that verified nothing.

`Transporter` has no API page, so both fields stay `null`.

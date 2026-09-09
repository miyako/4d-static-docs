# OOP examples: harvesting, synthesis and compiler cross-check (Phases 4–5)

This is the OOP sibling of [`pipeline/stage6_README.md`](../stage6_README.md).
Read that first: the sweep architecture, the overlay feedback loop, positional
diagnostic attribution, and above all the rule that **no diagnostic is ever
silenced without written, evidenced justification** are ported from it
unchanged. This document covers only what is different, and why.

## Stages

| Stage | File | Needs tool4d | Output |
|---|---|---|---|
| O7 | `stage7_doc_examples.py` | no | `out/oop_doc_examples.json` |
| O8 | `stage8_verify_examples.py` | **yes** | annotates `out/oop_doc_examples.json` |
| O6 | `stage6_synth_examples.py` | only `validate` | `oopcheck/Project/…`, `out/oop_synth_manifest.json`, `out/oop_lsp_crosscheck_report.json` |
| O9 | `stage9_hover_crosscheck.py` | **yes** | `out/oop_hover_crosscheck.json` |
| O10 | `stage10_corpus_stats.py` | no | `out/oop_corpus_stats.json` |

Stages O0–O5 remain pure Python: a clean clone with no 4D install still
reproduces `out/4d-oop-ir.json`. Only the cross-check stages need a licensed
4D, which is why they are separated.

Full run:

```sh
python3 pipeline/oop/stage7_doc_examples.py
python3 pipeline/oop/stage6_synth_examples.py generate     # pure Python
python3 pipeline/oop/stage6_synth_examples.py validate     # GATE G4
python3 pipeline/oop/stage8_verify_examples.py

tools/tool4d-lsp-stdio mcp --workspace "$PWD/oopcheck/Project"   # prints pid/port
python3 pipeline/oop/stage9_hover_crosscheck.py                  # GATE G5
tools/tool4d-lsp-stdio mcp --stop

python3 pipeline/oop/stage10_corpus_stats.py
```

`check-syntax` is one project-wide request: 919 blocks across 502 files in
~11 s. `hover` needs one request per member, so the persistent server matters:
~0.2 s each with it, a full tool4d startup each without.

## The check project

`oopcheck/Project/` — **not** `oopcheck/` and not any other folder name.

tool4d only opens a project whose enclosing directory is literally named
`Project`. An identical tree under `ProjectOOP/` made tool4d exit before
answering `experimental/checkSyntax`, reproducibly, ~10 s every time:

```
LSP checkSyntax session failed: waiting for experimental/checkSyntax response:
failed to read LSP header: failed to fill whole buffer
```

This was bisected: swapping in the classic corpus's known-good catalog, and
then reducing to a single one-line method, reproduced it identically. Moving
the same tree to `oopcheck/Project/` worked immediately. Hence the extra
directory level.

`Sources/catalog.4DCatalog` defines `SynthTable` (one field per 4D field type)
and `SynthRelated`, joined N→1. That is what unblocks `DataStore`,
`DataClass`, `Entity` and `EntitySelection` — about 88 members, ~18 % of the
corpus, none of which can be instantiated without a real structure. See
`oopcheck/README.md`.

Support artifacts: `Sources/Methods/SynthOOPCallback.4dm` (a `Formula()`
target) and `Sources/Classes/SynthOOPHandler.4dm` (the stub that doc recipes
naming `cs.MyClass` / `cs.MyHandler` map onto).

## What differs from the classic synthesizer

### Receivers

A classic call is self-contained; `ALERT("x")` needs no prior state. An OOP
instance member cannot be called at all without a live, correctly-typed
receiver, so `RECEIVER_RECIPES` in `stage6_synth_examples.py` holds one
compiling expression per class, derived from the IR's own
`classes{}.instantiation` recipes with the docs' illustrative names rewritten
onto the check project (`Employee` → `SynthTable`, `cs.MyClass` →
`cs.SynthOOPHandler`).

Every entry was verified by compiling one probe method per class before the
synthesizer was written: 43 of 45 passed first time, and both failures turned
out to be bugs in the hand-authored recipes rather than in the harness (see
"IR bugs found" below).

A gate asserts the table and the IR's `classes{}` describe the same class set,
so a class added upstream cannot silently go unsynthesized.

Four classes are **abstract** (`Directory`, `Document`, `Function`,
`Transporter`) and are synthesized against a concrete subclass, with a comment
saying so.

Four classes are **event-callback-only** (`IncomingMessage`, `TCPEvent`,
`UDPEvent`, `WebSocketConnection`): 4D passes instances into a callback and no
expression constructs one. They are *not* excluded. A bare typed declaration
(`var $event : 4D.TCPEvent`) resolves the type for the compiler exactly as a
callback parameter does — verified by compiling the same member access both
ways, as a local and as a `Function onTCPData($event : 4D.TCPEvent)`
parameter, and getting identical diagnostics. The generated block carries a
comment naming the real callback signature so no reader concludes the type is
constructible.

### Typed declarations

Classic leans on `Variant` placeholders. Here every local and every captured
return value is declared at its real IR type (`var $e : cs.SynthTableEntity`,
`var $r : 4D.Blob`). That is the point of the exercise: a wrong declared
return type in the IR becomes a hard `Impossible to cast X to Y` rather than a
silent pass. A negative control confirmed the oracle is strong — the compiler
reports unknown ORDA attributes, unknown members on typed receivers, and cast
mismatches.

`var $x : any` is not valid 4D. Pseudo types map through
`PSEUDO_DECLARE_TYPES`: `any`/`Variant` → `Variant`, `Expression` →
`4D.Function`.

### Sweeps

| Sweep | Varies | Classic counterpart |
|---|---|---|
| default | one block per overload, all params present | same |
| enum-value | every value of each `enum_ref` param | same |
| optional-param | each legal omission point | replaces the `*`-flag sweep |
| property read/write | read, and write when `accessor.writable` | none |
| property multi-variant | one read/write pair per alternative type | none |

Two classic sweeps have no OOP analogue:

* The **flag sweep** has none — there are no flag params to omit.
* The **union-discriminator sweep** has none *as a parameter sweep*. The OOP
  IR expresses alternatives as separate overloads: empirically 0 of 446
  parameters carry a list-valued type. Enumerating overloads, which the
  default block already does, *is* the union sweep. What does need explicit
  handling is the nine **multi-variant properties** (`Email.bcc/.cc/.from/
  .replyTo/.sender/.to` as `Text|Object|Collection`, `Document.original` as
  `4D.File|4D.Folder`, `SystemWorker.response` as `Text|Blob`,
  `WebServer.characterSet` as `Number|Text`). Sweeping only the first
  alternative leaves the rest unexercised — an assignment of the Text variant
  compiles fine while a wrong Object variant goes undetected — so every
  alternative gets its own read and write block.

### Legal omission points are derived, not denylisted

Classic maintains `MUTUALLY_EXCLUSIVE_TRAILING_PARAMS` by hand. Here the same
information is read off the syntax line's brace nesting
(`brace_group_openers`), because 4D syntax encodes it positionally:

```
.terminate( { code : Integer ; message : Text } )
4D.MailAttachment.new( file : 4D.File { ; name : Text {; cid : Text { … } } } )
```

In the first, `code` and `message` share one group and are all-or-nothing, so
`terminate(1)` is invalid even though both params are (correctly) optional. In
the second, each optional param opens its own nested group, so every trailing
truncation is legal. A `{` binds to the slot the group starts with: appearing
before the current slot has content it opens *this* slot, appearing after it
sits on the separator and opens the *next* one.

An omission point additionally requires every param from there on to be
optional. Without that, a *leading* optional param silently drops a required
trailing one — `.every( { startFrom : Integer ; } formula : 4D.Function )`
truncates to `.every()` — and the resulting error looks like an IR bug when it
is a synthesizer bug.

### Dynamic members

Seven members are name *patterns* (`4D.<classClassName>`,
`ds.<dataclassName>`, `$entity.<attributeName>`, …). Rather than skip them,
`DYNAMIC_MEMBER_STANDIN` maps each to a concrete member of the check
project's own model (`cs.SynthOOPHandler`, `ds.SynthTable`,
`$receiver.textValue`, `Web Form.myButton`), so the *mechanism* is still
compiler-verified; only the doc's literal placeholder name is not. Every such
block carries an explanatory comment, and the emission gate enforces that it
does.

## Gates

### GATE G4 — 0 errors, 0 warnings

**502 members → 919 blocks → 0 errors, 0 warnings.** No excluded members, no
denylist entries: `EXCLUDED_MEMBERS`, `REQUIRES_REFERENCE`,
`PROPERTY_WRITE_SKIP` and `PARAM_NAME_DENYLIST` are all empty, deliberately.
They exist so that a future exclusion has an obvious place to live *with its
evidence*, not so that diagnostics can be waved away. Every diagnostic seen
during development was triaged to an IR bug, an emitter bug, or a data bug,
and fixed.

### The emission-equality gate

`generate` re-reads every file it wrote and checks each block's call line
against the IR entry it claims to exercise: the member's name appears, and the
argument count matches what the block's variant intended to pass.

This exists because of a review finding on the previous phase. A check that
asks only "did the emitter produce a file, and did the compiler run over it?"
is satisfied by output that has silently lost data. `validate` applies the
same principle at the next hand-off: if a targeted file is absent from the
`check-syntax` response it is **unverified, not clean**, and the run fails
rather than counting it as passing.

### GATE G5 — hover vs. IR

`check-syntax` proves the corpus compiles; it cannot detect an obsolete or
renamed member (`skills/4dlsp/SKILL.md` names this explicitly). `hover`
returns the signature set the compiler itself holds — a third source, derived
from neither the HTML docs nor `syntaxEN.json`.

**502 members: 485 agree, 0 unknown to the compiler, 1 explained
disagreement, 9 with no hover entry, 7 dynamic members skipped.**

The 9 without a hover entry are *exactly* the 9 multi-variant properties.
tool4d's hover index holds one type per property and has no entry for a
multi-typed one; single-typed siblings on the same classes (`Email.subject`,
`WebServer.debugLog`) answer normally. This is a gap in hover's index, not a
missing member — G4 compiles a read and a write for every variant of all nine
with 0 diagnostics.

Disagreements are recorded, never auto-applied: hover renders the member's
*documentation* string, so where the docs are wrong hover repeats the error
and `check-syntax`, which exercises the real parser, is the stronger oracle.
`EXPLAINED_DISAGREEMENTS` records those cases with the evidence.

## IR bugs found by the compiler

All fixed through the sanctioned channel — a `semantic_overlays/<id>.json`
carrying a `_reason`, or `class_instantiation.json` — never by hand-editing
generated output. `rawSyntax` is left byte-identical to `syntaxEN.json` in
every case, as its gate requires; where the parsed `params[]` now diverges
from `rawSyntax`, that divergence *is* the finding.

1. **`4D.Folder.new`** — the `{ ; * }` in both documented syntax lines is a
   doc error copied from the classic `Folder` command. tool4d accepts
   `Folder("/tmp"; fk posix path; *)` and rejects
   `4D.Folder.new("/tmp"; fk posix path; *)` with a bare `Syntax error`; the
   sibling `4D.File.new` documents no `*` at all, and the page itself says
   `4D.Folder.new()` "is identical to the Folder command (shortcut)" while
   supplying no parameter table. The `*` param is dropped.
2. **`Collection.multiSort`** — `colsToSort` was typed as an `enum_ref` to the
   `ck ascending`/`ck descending` constants, but both syntax lines declare
   `colsToSort : Collection`; the constants appear in the page's prose because
   `.sort()` uses them. tool4d: *"At least one parameter type does not match
   the prototype(s) of the function multiSort."* An audit of **all 45
   `enum_ref` slots** against their `rawSyntax` declared type found this as the
   only mismatch in the corpus.
3. **`IMAPNotifier` recipe** — was `4D.IMAPNotifier.new($imap; Formula(…))`,
   but the constructor takes no parameters. tool4d: *"The function new
   received too many parameters."*
4. **`ZipFile` recipe** — was `$archive.root.file("README.md")`, but `.file()`
   is inherited from `Directory` and returns `4D.File`. tool4d: *"Impossible
   to cast 4D.File to 4D.ZipFile."* `.files()[0]` is the shape that
   type-checks.

## Doc examples (Phase 4)

Stage O7 re-parses the API pages directly rather than reusing stage O1's
`get_text()` output, which drops the `<br/>` between Docusaurus
`<span class="token-line">` elements and collapses every snippet onto one
line. Its parity gate is **containment** — every block O1 recorded must be
present here — because O1 discards code outside member `<h2>` sections; those
recovered blocks land in `unattributed`.

Attribution follows the superclass chain, so a `File` page's example for the
inherited `.exists` is attributed to `File` even though the member is modelled
once on `Document`.

Stage O8 verifies each snippet at the same bar as G4 (0 errors **and** 0
warnings) and triages into three buckets. Counting errors alone would let
snippets with undeclared locals — a *warning* in 4D — into bucket 1 unwrapped,
and would make the wrapping bucket dead code.

**490 snippets: 261 compile as published, 0 rescued by mechanical wrapping,
229 kept verbatim and unverified.**

Bucket 2 being empty is an empirical result, not an unimplemented path.
Wrapping (declare locals the fragment uses but does not declare; host a
class-body fragment in a class file) was *applicable to 55* of the failures
and rescued none, because the failures are semantic: unknown project tables
and ORDA dataclasses (`cs.EmployeeSelection`, `[Employee]`, …), user classes
whose members the page never shows, literal `...` elisions, blocks fenced as
`4d` that are actually JSON or query grammar, and some genuine typos in the
published docs. Making those compile would require inventing a data model or a
class API — which is what bucket 3 exists to refuse. They are kept
byte-for-byte and paired with the synthetic example every member has.

The harness asserts the file the compiler saw is character-identical to the
published snippet before claiming bucket 1. Choosing a method file versus a
class file is a container choice, recorded as `hostedAsClass`, not an edit.

Bucket-3 files are deleted after the run; leaving hundreds of non-compiling
snippets in the project would poison every later G4 run.

## Maintenance

* A new diagnostic is **always** triaged to exactly one of: IR bug (fix via an
  overlay, re-run O5), enum data bug (fix the registry), synthesizer bug (fix
  the emitter), or a genuine environment limitation (add a denylist entry
  **with the compiler's message quoted**). Never a silent skip.
* Prefer deriving a rule from the data — as `brace_group_openers` does — over
  adding a hand-maintained denylist entry.
* After changing `class_instantiation.json` or an overlay, re-run
  `stage4_classes.py` and `stage5_assemble.py`, then `generate` and
  `validate`.
* `generate` and `validate` both accept `--ids` and `--class` for a fast loop
  on one member or one class; both merge into the existing manifest and report
  rather than truncating them.

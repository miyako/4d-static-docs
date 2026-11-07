# OOP examples: harvesting, synthesis and compiler cross-check

This is the OOP sibling of [the classic example pipeline](../stage6_README.md).
The rule is unchanged: **no diagnostic is silenced without written,
compiler/documentation evidence**. The current full refresh is against
**21 R5 BETA**, not the stable R4 auto-selection.

## Exact source and compiler provenance

* Docs: explicit `--docs-root mirror/docs`, actual badge **21 R5 BETA**.
* Capture: `references/syntaxEN-21-R5.json`, explicit `--syntax-version 21-R5`,
  SHA256 `ee27d9689e834bd1990d60d289d8c4e86e39beb723fe88c55b719e9d1e8bc411`.
* Compiler: `/Applications/4D 21 R5/tool4d.app/Contents/MacOS/tool4d`;
  Info.plist reports **21 R5 build 21R5.100156**. The installed syntax resource
  matches that SHA256.
* Bridge: `tools/4dlsp/tool4d-lsp-stdio`, **0.3.0**, provisioned from mirrored
  skills **v0.0.32**. Do not use the obsolete `tools/tool4d-lsp-stdio` path.

Compiler stages require explicit `TOOL4D_PATH`. Their outputs record compiler,
bridge and capture provenance, and reject a mismatching readable compiler
capture. The default stable docs selector is unchanged and must not be used
for this beta update.
Fresh invocation provenance additionally records UTC capture time, the actual
`TOOL4D_PATH`, IR/source-manifest hashes, and the input synth-manifest or
documentation-example hash. Every generated method has a source SHA256 in
the synth manifest; compilation and hover refuse mismatched method bytes.

## Full run

Assemble O0–O5 using the explicit inputs in [README.md](README.md) first.

```sh
export TOOL4D_PATH='/Applications/4D 21 R5/tool4d.app/Contents/MacOS/tool4d'
python3 pipeline/oop/stage7_doc_examples.py --docs-root mirror/docs
python3 pipeline/oop/stage6_synth_examples.py generate
python3 pipeline/oop/stage6_synth_examples.py validate       # G4
python3 pipeline/oop/stage8_verify_examples.py
python3 pipeline/oop/check_type_names.py

tools/4dlsp/tool4d-lsp-stdio mcp --workspace "$PWD/oopcheck/Project"
python3 pipeline/oop/stage9_hover_crosscheck.py              # G5
tools/4dlsp/tool4d-lsp-stdio mcp --workspace "$PWD/oopcheck/Project" --stop

python3 pipeline/oop/stage10_corpus_stats.py
python3 -m unittest discover -s pipeline/oop/tests -v
```

The bridge's current `mcp --stop` also needs the workspace. Hover subprocesses
run from `oopcheck/Project`, so omitted project flags attach to the OOP server
even while a classic server is running. They use absolute method paths. The first
successful request verifies responsiveness; stop it after the sweep.

| Stage | Input/output |
|---|---|
| O7 `stage7_doc_examples.py` | API HTML → `out/oop_doc_examples.json`; old verdicts deliberately invalidated |
| O6 `stage6_synth_examples.py` | IR → generated `oopcheck` methods, `out/oop_synth_manifest.json`, `out/oop_lsp_crosscheck_report.json` |
| O8 `stage8_verify_examples.py` | Fresh compiler buckets on every harvested 4D snippet |
| Controls `check_type_names.py` | Generated probes → `out/oop_type_name_crosscheck.json`; probes cleaned up |
| O9 `stage9_hover_crosscheck.py` | Full member hover report → `out/oop_hover_crosscheck.json` |
| O10 `stage10_corpus_stats.py` | Frequency/class/example measurements → `out/oop_corpus_stats.json` |

## The check project

Use **`oopcheck/Project/`**, not `oopcheck/` or a differently named source
directory. tool4d expects the enclosing directory to be named `Project`.
Its catalog supplies `SynthTable`, `SynthRelated` and their relation, allowing
real ORDA receivers rather than undefined illustrative tables.
`SynthOOPCallback.4dm` and `SynthOOPHandler.4dm` supply callable stand-ins.

`RECEIVER_RECIPES` provides every one of the IR's 51 class records. Typed
locals and captured returns expose unknown classes/members and cast
mismatches instead of hiding them behind `Variant`. The four abstract classes
use concrete receivers; all 46 fixed class declaration names, including the
abstract names, were separately rechecked.

Four event-callback-only classes (`IncomingMessage`, `TCPEvent`, `UDPEvent`,
`WebSocketConnection`) use typed declarations, not invented constructors.
Seven dynamic pseudo-members use concrete check-project stand-ins, annotated
in their blocks; they are compiler checked, not excluded.

## Sweeps and G4

Every callable overload gets a full-parameter block. Additional sweeps cover
each enum constant, legal trailing optional-group omissions, property reads,
writable-property assignments and every alternative property type.

Optional omission points come from brace-group nesting, not a denylist. An
all-or-nothing optional pair must not be truncated midway; a leading optional
group must not cause a required trailing argument to disappear.

There are **445 parameters, zero list-valued parameter unions, and 44 enum
parameter slots**. Alternatives appear as callable overloads. Ten properties
are multi-typed: six Email recipient properties, `Document.original`,
`SystemWorker.response`, `WebServer.characterSet`, and the new
`SMTPTransporter.certificate` (`4D.File | Blob`). Every property alternative
gets its own read and, when writable, write.

**G4: 528 members → 528 method files → 968 blocks → zero errors, zero
warnings.** All 528 target files were present in the compiler's 530-file
project response. No members, reference params, writes or parameter names are
denylisted. `validate` now returns failure for either errors or warnings.

The emission-equality gate rereads every generated block and checks its
claimed member and argument count. A missing compiler-response file is
unverified, never counted as clean. Documentation-example scaffolding and
control methods are removed after checking so they cannot poison later runs.

## G5: hover and controlled source conflicts

**528 members: 508 agree, zero unexplained disagreements, three explained
disagreements, zero unknown, zero missing call sites, ten multivariant
properties without hover entries, seven dynamic stand-ins.**

The ten index gaps are retained explicitly, not interpreted as successful
hover matches. G4 separately compiles every property variant. Hover reads
documentation strings and can repeat documentation errors; the real parser
and controlled type checks are stronger evidence in these three cases:

1. `4D.Folder.new`: documentation/hover include `*`, but matched R5 tool4d
   rejects the constructor with `*` and accepts the corresponding classic
   `Folder(...; *)`. The overlay removes the invalid semantic argument,
   preserving raw source.
2. `Session.quotas` and `WebServer.quotas`: docs/hover name
   `4D.QuotaManager`, which R5 tool4d reports as unknown.
   `4D.QuotaManagerClass` works for those same assignments. New evidenced
   overlays and the quota recipe use the compiler spelling; raw syntax is
   untouched. The quota object itself is not directly assignable.

`check_type_names.py` records **66 expected outcomes, all passing**: all 46
fixed class declarations and 20 semantic/acceptance probes. These
reverify the Folder `*` correction, Collection-vs-integer `multiSort`
parameter, no-argument IMAPNotifier recipe and correct ZipFile producer.
Vector `length` and `precision` are read-only according to the documented
immutable class contract; two overlays correct the property-level default.
The wrong ZipFile producer yields `Impossible to cast 4D.File to 4D.ZipFile`;
the correct `.files()[0]` producer passes.

No R3 verdict or old overlay explanation was accepted without R5 review.
TCP port probes accept Integer, Real, and even unsuitable Text/Collection
inputs; this compiler limitation cannot settle the port domain. Its retained
overlay follows the documented Integer parameter table. `orderByMethod`
extra-argument probes accept Integer, Text and Formula, confirming that the
source's Expression pseudo-type is not a concrete Function restriction.
Compilation is not runtime-instantiation or network verification.

## O7/O8: fresh documentation examples

**523 code blocks: 483 attributed, 40 recovered/unattributed; 229 distinct
members, 22 inherited attributions.** The O1 containment gate passes:
every O1 code block is present, plus 40 blocks outside member sections.

R5 changed Prism line containers from `span.token-line` to `div.token-line`.
O7 supports both and preserves newlines/indentation. Falling back to plain
`get_text()` had collapsed R5 examples, causing artificial syntax failures;
the parser was corrected and all examples were reharvested and rechecked.
Tests cover both markup forms, plain code and a missing source member.

**499 4D snippets checked: 269 compile as published, zero rescued by
mechanical wrapping, 230 retained verbatim and unverified.** The other 24
blocks are not 4D source. Bucket 1 requires character-identical compiler
input and zero errors/warnings. Wrapping was applicable to 55 failures and
rescued none; inventing absent tables, user-class APIs or elided source is
not a mechanical wrapper.

Unverified snippets keep their diagnostics and original text. Typical
limitations are unspecified project models/classes, literal elisions,
non-4D content fenced as `4d`, and genuine published typos. None is used to
justify suppressing synthetic diagnostics. No unchanged previously verified
snippet regressed after correcting R5 line extraction.

O10 reports **147 members with verified documentation examples**, 78 with
unverified-only documentation examples, **303 synthetic-only**, **528 with
synthetic examples**, and **zero without either**.

## Maintenance

* Preserve the old baseline before overwriting; use `review_refresh.py` to
  distinguish member/section changes from navigation/hash noise.
* An IR bug is fixed via an evidenced semantic overlay or authored recipe;
  a constant bug belongs to the shared registry; an emitter bug belongs here.
* After changing recipes/overlays, rerun O4/O5 and full generate/validate.
  `--ids` and `--class` support narrow diagnostic loops, but a complete refresh
  must finish with the full gates.
* O7 discards verification; always rerun O8. Reusing R3 verdicts after a
  source/compiler update is not verification.
* Crosslinks read classic too; rerun after both assemblies. Transient classic
  changes are not an OOP extraction/compiler blocker.

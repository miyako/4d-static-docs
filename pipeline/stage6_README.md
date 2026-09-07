# Stage 6: synthetic example generation + tool4d cross-check

This document describes the maintenance workflow for `stage6_synth_examples.py`
and its artifacts (`Project/Sources/Methods/Synth_*.4dm`,
`out/synth_manifest.json`, `out/lsp_crosscheck_report.json`). It covers only
the work done **after** the IR itself was first assembled (Stages 0–5,
documented in `pipeline/README.md`) — i.e. what to do when the IR changes and
these downstream artifacts need to be brought back in sync with it.

## What this stage does

For every command/overload in `out/4d-command-ir.json`, `stage6_synth_examples.py`
synthesizes one or more real 4D method bodies that call the command, writes
them to `Project/Sources/Methods/Synth_<id>.4dm`, and cross-checks them
against a real 4D compiler (`tool4d`, driven via `tools/tool4d-lsp-stdio`'s
LSP bridge) inside the throwaway project `Project/4DCommandIRSynthCheck.4DProject`.
Where the compiler disagrees with what the IR claims, that's fed back as a
correction to the relevant `pipeline/semantic_overlays/<id>.json` overlay (or,
for enum data bugs, to `references/4d-command-ir-enums.json` /
`references/4d-command-ir-examples.json`), followed by re-running
`stage5_assemble.py` and re-validating.

### Current coverage (as of this document)

Each overload gets a "default" block (all params, using the first/preferred
alternative for anything ambiguous), plus these sweeps add more blocks:

| Sweep | What it varies | Blocks | Driven by |
|---|---|---|---|
| enum-value sweep | every value of an `enum_ref` param, across ALL values | 180 | `find_enum_refs_in_params` + `ctx_state.enum_override` |
| flag on/off sweep | every optional `literal_symbols` flag (e.g. `*`, `>`), present vs. omitted | 395 | `find_flag_omission_variants` + `call_params` override |
| union-discriminator sweep | every alternative of a union-typed param, one at a time | 537 | `find_union_params_in_params` + `ctx_state.union_override` |

Total: 2701 overload+variant entries across 1456 commands, 2576 clean, 0
warnings, 125 errors — **all 125 are ViewPro** (a separate installable
component, not a built-in command set; deliberately out of scope, see
below). Any other error is a real finding that must be triaged.

### Deliberate, documented exclusions (do not "fix" these)

A few sweep combinations are skipped on purpose because they'd produce a
call that's invalid for reasons unrelated to the IR's correctness. These are
recorded as small denylists/conditions directly in the code, each with a
comment explaining the reasoning — read them before changing:

- `FLAG_SWEEP_SKIP_EMPTY_CALL = {"ADD-RECORD", "MODIFY-RECORD", "PRINT-RECORD"}`
  — these 3 commands' fully bare zero-argument call is documented-valid 4D
  syntax, but tool4d's offline/dataless static analyzer specifically rejects
  it (can't resolve "current default table" without a live form/runtime
  context). Confirmed not a general limitation — same-shape commands like
  `HIGHLIGHT-RECORDS` validate their own zero-arg variant clean.
- `find_union_params_in_params`'s star-flag-governed skip — a union param
  immediately following a leading `*` flag (e.g. `DELETE-FROM-LIST`'s `list`
  after `asObjectName`) is not independently choosable; its valid
  alternative is strictly governed by the flag. Already covered correctly
  by the flag sweep's two on/off variants instead.
- `find_union_params_in_params`'s enum-selector skip — any union param
  sharing an overload with a plain `enum_ref` selector param (only
  `WEB-SET-OPTION`'s and `SET-DATABASE-PARAMETER`'s `value`) is
  selector-dependent, not a free union; forcing an arbitrary alternative
  against the sweep's arbitrary default selector is a real type mismatch,
  not an IR bug.
- ViewPro (125 commands, `VP-*`/`WP-*` ids under the "View Pro"/"Write Pro"
  themes) — a licensed/installable 4D component, not part of the base
  language. Its errors in `out/lsp_crosscheck_report.json` are a permanent
  baseline, not a to-do list. If ViewPro is ever provisioned in this
  environment, that baseline should shrink — treat any *reduction* below
  125 as expected progress, not a regression.

If you find yourself tempted to write a new command-specific exception,
first ask whether the IR itself is wrong (fix the overlay) before excluding
it from the sweep — the 3-command and 2-param exclusions above were only
added after confirming via tool4d + external documentation that the IR was
already correct and the sweep's generic mechanism was the thing producing
an artificial invalid combination.

## When you need to re-run this stage

Three distinct triggers, each with a different scope of what to re-run:

### 1. The IR changed (upstream: new/changed commands from Stages 0–5)

If `out/4d-command-ir.json` was regenerated because the source docs changed
(new 4D version, new commands, changed overloads), only the affected
command ids need fresh synthesis + validation:

```sh
# Determine which command ids changed -- compare old/new out/manifest.json
# content hashes (Stage 0), or diff the two out/4d-command-ir.json files by
# command id, whichever is available.
python3 pipeline/stage6_synth_examples.py generate --ids ID1,ID2,...
python3 pipeline/stage6_synth_examples.py validate --ids ID1,ID2,...
```

Then, **before committing**, run a full-corpus regression to confirm the
change didn't affect anything else (there is currently no per-command
caching in this stage, so this always reprocesses everything — budget
several minutes):

```sh
python3 pipeline/stage6_synth_examples.py generate --all
python3 pipeline/stage6_synth_examples.py validate --all
```

Compare the final line's totals against the last known-good baseline
(currently: `2701 overload(s) checked, 2576 clean, 0 warning-only, 125
error`). Any error whose command id is not `VP-*`/ViewPro-themed is a new
finding — triage it (see the loop below) before committing.

### 2. A bug is found (tool4d disagrees with the IR)

This is the actual cross-check loop the whole stage exists for:

1. Identify the failing entry in `out/lsp_crosscheck_report.json` (or from
   `validate`'s stdout) — note the command id, `variant`, and diagnostic
   message.
2. Decide what's actually wrong:
   - **IR/overlay bug** (most common: wrong enum value name/casing, wrong
     optionality, wrong param type) → fix
     `pipeline/semantic_overlays/<id>.json` (or the shared registries
     `references/4d-command-ir-enums.json` /
     `references/4d-command-ir-examples.json` /
     `references/4d-constants-registry.json` for enum data), then:
     ```sh
     python3 pipeline/stage5_assemble.py   # rebuild out/4d-command-ir.json
     ```
   - **Synthesizer bug** (the generated call itself is wrong even though
     the IR is right — e.g. wrong literal shape, wrong preference rule) →
     fix `pipeline/stage6_synth_examples.py` directly. See "Synthesizer
     internals" below for where the relevant logic lives.
   - **Tooling limitation, not a bug** (rare — confirm via an isolated
     manual test with `tools/tool4d-lsp-stdio validate` and, ideally,
     external 4D documentation before concluding this) → add a narrowly
     scoped, well-commented exclusion (see examples above), do NOT touch
     the IR.
3. Re-generate + re-validate just the affected id(s) to confirm the fix,
   then re-run the full-corpus regression (step 1's `--all` commands)
   before committing, since a fix (e.g. changing a shared preference rule
   in `build_arg_for_type`) can affect many other commands at once.

### 3. The synthesizer itself changed (new sweep, new type-kind support, etc.)

Same as trigger 1's full-corpus regression — there's no way to know in
advance which commands a synthesizer-logic change affects, so always run
`generate --all` + `validate --all` and diff against the last known-good
baseline before committing.

### 4. A command was removed from the IR

If a command id disappears from `out/4d-command-ir.json` (see
`pipeline/MAINTENANCE.md`'s Step 6 for the upstream removal process), its
Stage 6 artifacts become orphaned and must be cleaned up manually — nothing
in this stage detects or prunes them automatically:

```sh
rm -f Project/Sources/Methods/Synth_<id>*.4dm
```

Then remove the id's entries from `out/synth_manifest.json` and
`out/lsp_crosscheck_report.json` (both are JSON arrays/maps keyed by command
id — filter the removed id(s) out and rewrite), or simply regenerate both
from scratch for the full corpus (`generate --all` / `validate --all`),
which naturally excludes anything no longer in the IR. Prefer the full
regeneration unless the corpus is large enough that the targeted cleanup is
meaningfully faster.

## Prerequisites / environment dependencies

- `tools/tool4d-lsp-stdio` must be provisioned (see `pipeline/README.md`'s
  tooling section if this repo has one, or re-provision via whatever
  mechanism installed it originally — it wraps a real `tool4d` binary from
  a 4D Analyzer install).
- The underlying `tool4d` binary is **version-pinned** to the 4D release
  the docs mirror was extracted from (currently 21R3, resolved via a local
  4D Analyzer install e.g. under
  `~/Library/Application Support/Code/User/globalStorage/4d.4d-analyzer/tool4d/21R3/...`
  on macOS with the 4D VS Code extension installed). If the docs mirror is
  ever upgraded to a newer 4D version, this binary needs to be upgraded to
  match, or the cross-check will validate new syntax against a stale
  compiler and produce false positives/negatives.
- `Project/4DCommandIRSynthCheck.4DProject` is a minimal throwaway project
  with one table (`[SynthTable]`, fields `ID`/`label`) used to satisfy
  `Table`/`Field`-typed params. If a future command needs a param shape this
  catalog can't satisfy (e.g. a second table for cross-table pointer tests),
  extend the catalog rather than working around it in the synthesizer.

## Synthesizer internals (map for future changes)

- `SynthContext` — per-command state: `prelude` (declared vars), `counter`
  (for `fresh_name`), `star_active`/`star_present` (the `*`
  dual-signature toggle, see below), `self_array_element`, `enum_override`,
  `union_override`.
- `build_arg_for_type(ir, type_obj, ctx, ctx_state, direction)` — the core
  per-param value synthesizer. `type_obj` may be a single `TypeRef` dict or
  a `list` (union). All override dicts (`enum_override`, `union_override`)
  are consulted at the very top of the union branch, before any other
  preference rule. Concrete-type literals live in `CONCRETE_LITERALS`;
  types needing an addressable variable use `DECLARABLE_VAR_TYPES`.
- `build_call_args(ir, params, ctx_state, command_id)` — turns a params
  list into a call's argument-expression list; consults
  `MUTUALLY_EXCLUSIVE_TRAILING_PARAMS` and `PSEUDO_REQUIRES_REFERENCE`.
- `synthesize_command(ir, command) -> list[dict]` — the per-overload block
  emitter. Each block is `{"overload_index", "variant", "lines"}`. The
  inner `render_block(variant, comment_suffix, overrides, call_params,
  union_overrides)` closure is the single place all four block kinds
  (default/enum/flag/union) go through — extend it (not a parallel
  mechanism) for any new sweep.
- `find_enum_refs_in_params`, `find_flag_omission_variants`,
  `find_union_params_in_params` — the three sweep-candidate finders, each
  with a docstring explaining its inclusion/exclusion rules in detail.
- `cmd_generate`/`cmd_validate`/`cmd_report` — CLI subcommands. Diagnostic
  attribution in `cmd_validate` is **positional** (`enumerate(starts)`),
  not keyed by `overload_index`, since multiple blocks can share one
  `overload_index` — preserve this if you touch that function.
- `tools/tool4d-lsp-stdio validate --json --workspace Project/ <paths...>`
  is called in chunks of `VALIDATE_CHUNK_SIZE` (150) files at a time.

## What this document does NOT cover

Refreshing the IR itself (new 4D docs version, new/changed commands,
constants registry updates, semantic overlay authoring for brand-new
commands) is the responsibility of Stages 0–5, documented in
`pipeline/README.md`. This document starts from "the IR changed" or "the
synthesizer changed" and covers only how to bring `out/synth_manifest.json`,
`out/lsp_crosscheck_report.json`, and the generated `.4dm` files back in
sync with it.

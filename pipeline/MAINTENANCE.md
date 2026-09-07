# Updating the 4D Command IR

This is the runbook for keeping `out/4d-command-ir.json` in sync after the
underlying docs mirror (`mirror/docs/`) changes — a new 4D version adds
commands, an existing command's signature/behavior changes, or a command is
removed/deprecated. It assumes you already have a working checkout with
`pipeline/requirements.txt` installed.

Read this together with `pipeline/README.md` (pipeline architecture/scope
decisions) and `references/4d-command-ir-README.md` (schema/file layout).
This document is about the **update loop**, not the initial build.

## Why this isn't just "re-run everything"

Only Stage 0 and Stage 1 are fully self-cleaning on re-run (content-hash
cached, rebuilt fresh from the current manifest every time). Everything
downstream — the Stage 3 bulk ledger, the hand-authored overlays, the 13
fixtures, and the Layer-2 registries — has irreversible human judgment baked
into it and is **not** automatically invalidated when source docs change.
Blindly re-running the whole pipeline will silently keep serving stale
"done" verdicts for changed commands and will never notice removed ones.
The steps below exist specifically to surface what actually needs
re-review.

## Step 0 — refresh the mirror

Regenerate/update `mirror/docs/` with whatever process produced it originally
(out of scope for this pipeline — it treats the mirror as a read-only input).
Confirm which version folder you're targeting; Stage 0 auto-picks the
highest non-BETA version unless you pass `--version`/`--docs-root`.

## Step 1 — snapshot the old manifest, then regenerate it

```sh
cp out/manifest.json out/manifest.json.before   # keep the pre-update snapshot
python3 pipeline/stage0_manifest.py             # -> out/manifest.json (new)
```

## Step 2 — classify what changed

Compare `manifest.json.before` and the new `manifest.json` by `id` and
`contentHash`:

```python
import json
old = {e["id"]: e for e in json.load(open("out/manifest.json.before"))["entries"]}
new = {e["id"]: e for e in json.load(open("out/manifest.json"))["entries"]}

added   = sorted(new.keys() - old.keys())
removed = sorted(old.keys() - new.keys())
changed = sorted(cid for cid in (old.keys() & new.keys())
                  if old[cid]["contentHash"] != new[cid]["contentHash"])

print("added:", added)
print("removed:", removed)
print("changed:", changed)
```

Keep these three lists — every subsequent step is driven by them. Note the
13 hand-authored fixtures (`ORDER-BY`, `ORDER-BY-FORMULA`, `Table`, `OB-SET`,
`MULTI-SORT-ARRAY`, `SET-LIST-ITEM-PROPERTIES`, `SET-LIST-PROPERTIES`,
`GRAPH`, `GRAPH-SETTINGS`, `QUERY-BY-ATTRIBUTE`, `SQL-EXECUTE`,
`WA-EXECUTE-JAVASCRIPT-FUNCTION`, `WP-SET-ATTRIBUTES` — the current
`FIXTURE_IDS` set in `pipeline/stage3_bulk.py`) are excluded from the bulk
manifest/ledger entirely; if any of them show up in `changed`, handle them
separately in Step 7, not through the bulk workflow below.

## Step 3 — re-run Stage 1 (safe, idempotent, always do this)

```sh
python3 pipeline/stage1_extract.py
```

This rebuilds `out/stage1_raw.json` fresh from the *current* manifest every
time: `removed` ids simply drop out, `changed` ids get a cache miss and are
re-parsed, everything else is served from `cache/raw/<id>.<hash>.json`
unchanged. Nothing manual is needed here.

## Step 4 — handle `added` commands

These are brand-new to the corpus. They need the same treatment as the
original bulk rollout:

```sh
python3 pipeline/stage3_bulk.py init            # adds new pending ids to the ledger
python3 pipeline/stage3_bulk.py report           # confirm the new pending count
python3 pipeline/stage3_bulk.py next-batch 25    # hand out ids to review
```

For each id in a batch: read the live/mirrored doc, decide whether the
mechanical draft (Stage 1 extraction + Stage 3's automatic overload-merge
logic) is already correct, or whether it needs an overlay
(`pipeline/semantic_overlays/<id>.json`) to add/correct `constraints`,
`discriminatedBy`, `sentinelValues`, `enum_ref`/`callbackContractRef`/
`protocolRefs`, or a fully-replaced `overloads` array (see the "Technical
details" section below for exactly when each mechanism applies). Then:

```sh
python3 pipeline/stage3_bulk.py validate ID [ID ...]
```

Repeat until `pipeline/stage3_bulk.py report` shows 0 pending and 0
`draft_ok` needing attention (a `draft_ok` status is a legitimate final
state for a genuinely simple, unambiguous command with no overlay needed —
but always read the doc first before concluding that).

## Step 5 — handle `changed` commands (the ledger doesn't do this for you)

**This is the step that's easy to silently skip.** `stage3_bulk.py init` is
purely additive — it never resets an existing "done" id back to "pending"
just because its source content changed. You must do this explicitly:

```python
import json
ledger = json.load(open("out/stage3_progress.json"))
for cid in changed:               # from Step 2, minus any FIXTURE_IDS
    if cid in ledger:
        ledger[cid] = {"status": "pending", "error": None, "updated_at": "<now, ISO8601>"}
json.dump(ledger, open("out/stage3_progress.json", "w"), indent=2, sort_keys=True)
```

Then work through them the same way as `added` commands
(`next-batch`/read-doc/author-or-update-overlay/`validate`), but with one
extra check specific to changed commands: **read the existing overlay file
first and diff the old vs. new doc content yourself** before touching
anything. A previously-correct overlay can silently become wrong when the
underlying doc changes — e.g. an `overloadPatches` entry keyed by numeric
`index` will patch the *wrong* overload if the doc reordered or added an
overload; a `constraints` entry can become stale prose describing behavior
that no longer applies; a `discriminatedBy` rule can break if a parameter
was renamed. Never assume "the overlay already exists, it must still be
right."

## Step 6 — handle `removed` commands

There's no `prune` subcommand yet, so this is a manual (but simple) cleanup:

```sh
for id in $REMOVED_IDS; do
  rm -f "pipeline/semantic_overlays/${id}.json"
  rm -f "out/stage3_ir_full/${id}.json"
  rm -f cache/raw/"${id}".*.json
done
python3 - <<'EOF'
import json
ledger = json.load(open("out/stage3_progress.json"))
for cid in REMOVED_IDS:            # substitute the actual list
    ledger.pop(cid, None)
json.dump(ledger, open("out/stage3_progress.json", "w"), indent=2, sort_keys=True)
EOF
```

Also check whether a removed command appears in:
- any other command's `constraints` prose (cross-references, e.g. "see also
  DOM Parse XML source") — a dangling mention isn't fatal but is worth a
  grep-and-clean pass;
- `references/4d-command-ir-examples.json`'s `relationships` array, or any
  registry's `usedByCommands` list (`protocols.multiCallChains.*`,
  `protocols.stateMachines.*`, `handleTypes.*.producedBy/consumedBy/
  destroyedBy`) — these **do** need manual editing, since Stage 5 merges
  registries as-is and won't notice a stale reference to a command that no
  longer exists.
- `pipeline/stage3_bulk.py`'s `FIXTURE_IDS` set, if a removed id happens to
  be a fixture (should not normally happen, but check).

## Step 7 — the 13 hand-authored fixtures

`references/4d-command-ir-examples.json`'s `commands` array is not
mechanically derived — there is no draft/overlay merge for these, the JSON
*is* the final entry. If any fixture id appears in `changed` (from Step 2)
or you otherwise learn its doc changed:

1. Re-fetch the live/mirrored doc for that command.
2. Manually edit its entry directly in `4d-command-ir-examples.json` to
   match the new doc content (overloads, params, constraints, etc.).
3. Validate the file is still schema-valid:
   ```sh
   python3 -c "import json, jsonschema; \
     schema = json.load(open('references/4d-command-ir-schema.json')); \
     doc = json.load(open('references/4d-command-ir-examples.json')); \
     jsonschema.Draft202012Validator(schema).validate(doc)"
   ```
4. If `pipeline/stage3_semantic.py` has any fixture-specific regression
   assertions for this id, re-run it and update those too.

If a *new* command needs to become a fixture (e.g. it demonstrates a
genuinely new tricky pattern worth permanent regression coverage), add it to
both `4d-command-ir-examples.json`'s `commands` array **and**
`pipeline/stage3_bulk.py`'s `FIXTURE_IDS` set (so the bulk ledger correctly
excludes it) — get the `id` exactly right: it must equal
`slugify_id(displayName)` where `displayName` is the doc's literal `<h1>`
text (see `pipeline/common/htmlutil.py:slugify_id`/`command_title`), *not*
a hand-picked casing. Getting this wrong produces the exact
`TABLE`-vs-`Table` drift documented in this project's git history — the
symptom is a phantom entry in "ids present in the IR but not in
manifest.json" when you do the Step 9 sanity check.

## Step 8 — Layer-2 registries (enums, callbacks, foreign grammars, constants)

These are hand-maintained flat files, not derived from Stage 1/3 at all:

- `references/4d-command-ir-enums.json`, `4d-command-ir-callbacks.json`,
  `4d-command-ir-foreign-grammars.json` — if an `added` or `changed` command
  needs a new/updated `EnumDef`/`CallbackContractDef`/`ForeignGrammarDef`,
  author it here directly (cite the live doc in your own working notes, not
  necessarily in the file), then reference it from the command's overlay
  via `enum_ref`/`callbackContractRef`/`foreign_grammar_ref`. Do not
  duplicate an enum inline in an overlay if an equivalent one already
  exists in the registry — check `byName`/`byTheme` in
  `references/4d-constants-registry.json` first (see below) for the
  authoritative selector-value list.
- `references/4d-constants-registry.json` is generated, not hand-maintained
  — regenerate it if 4D ships updated XLIFF constants exports
  (`4D_ConstantsEN.xlf` / `4D_ConstantsThemesEN.xlf`, dropped in
  `pipeline/data/`):
  ```sh
  python3 pipeline/tools/parse_xliff_constants.py
  ```
- `protocols.multiCallChains`/`protocols.stateMachines` (only defined today
  in `4d-command-ir-examples.json`) — if a changed/added command's overlay
  sets `protocolRefs.multiCallChain`/`.stateMachine`, remember the lesson
  from this project's Stage 5 work: only use `multiCallChain` for a
  genuinely repeated *single* command with a real continuation-flag
  parameter (like `queryThemeChain`'s trailing `*`). A sequence of
  *different* commands used together by convention (lifecycle patterns like
  "parse → navigate → close") is **not** a multiCallChain and should not be
  forced into `stateMachine` either unless the sequence is genuinely
  syntactically/contractually enforced — otherwise just describe it in
  plain `constraints` prose, as was done for the ~54 DOM/SAX/HTTP/Mail/Web
  Service commands during this project's Stage 5 pass.

## Step 9 — reassemble and validate

```sh
python3 pipeline/stage5_assemble.py
```

This merges the fixtures + all `out/stage3_ir_full/*.json` + the three
standalone Layer-2 registry files into `out/4d-command-ir.json` and runs
full-document JSON Schema validation. It will fail loudly (non-zero exit,
printed error list) on any schema violation — fix and re-run rather than
committing a document that doesn't pass.

After a successful run, sanity-check id parity against the manifest (this
should always be an exact match except for `Table`/fixture-vs-manifest
casing, which is why Step 7 tells you to get the casing right):

```python
import json
ir_ids = {c["id"] for c in json.load(open("out/4d-command-ir.json"))["commands"]}
manifest_ids = {e["id"] for e in json.load(open("out/manifest.json"))["entries"]}
print("in manifest not in IR:", manifest_ids - ir_ids)   # expect: set()
print("in IR not in manifest:", ir_ids - manifest_ids)   # expect: set() (no more off-mirror fixtures)
```

## Step 10 — LSP/compiler cross-check (if provisioned)

If the `tool4d`-based compiler cross-check pipeline has been set up (see the
`stage6_synth_examples.py`-based work — check whether it's been merged to
`main` yet), re-run it at least for every `added`/`changed` command id
before considering the update done. This is the only step that actually
compiles the modeled signatures rather than just schema-validating their
shape, and it has already caught real IR bugs (missing parameters) that
schema validation alone could not.

## Step 11 — housekeeping and commit

- If your update meaningfully changes corpus-wide counts (total commands,
  fixture count, tracked-id count), grep for stale hardcoded numbers in
  comments/docstrings/READMEs (`pipeline/README.md`,
  `references/4d-command-ir-README.md`, docstrings in `stage3_bulk.py`/
  `stage3_semantic.py`/`stage5_assemble.py`) and update them — this project
  has twice had to fix stale counts left over from a prior state.
- Delete the temporary `out/manifest.json.before` snapshot from Step 1 (or
  keep it as a dated backup outside `out/` if you want a paper trail).
- Commit `out/manifest.json`, `out/stage1_raw.json`, updated/new/removed
  `pipeline/semantic_overlays/*.json`, `out/stage3_progress.json`,
  `out/stage3_ir_full/*.json` (added/changed/removed as appropriate),
  any Layer-2 registry edits, and the regenerated `out/4d-command-ir.json`
  together in one commit (or a small tightly-scoped series) — these files
  are only consistent with each other as a set.
- Do **not** hand-edit `out/4d-command-ir.json` directly; it's a build
  artifact of Stage 5. Always change the upstream source (overlay/fixture/
  registry) and re-run `stage5_assemble.py`.

## Quick reference

| Change type | What to do |
|---|---|
| New command in the mirror | Step 4 (`stage3_bulk.py init` → review → `validate`) |
| Existing bulk command's doc changed | Step 5 (manually reset ledger status to `pending` first — `init` won't do it) |
| Command removed from the mirror | Step 6 (manual cleanup — no `prune` subcommand exists yet) |
| One of the 13 fixtures changed | Step 7 (hand-edit `4d-command-ir-examples.json` directly) |
| New enum/callback/foreign-grammar needed | Step 8 (author in the relevant registry file, reference via `*_ref`) |
| 4D shipped new XLIFF constants exports | Step 8 (`pipeline/tools/parse_xliff_constants.py`) |
| Any of the above | Always finish with Step 9 (`stage5_assemble.py`) and, if available, Step 10 (LSP cross-check) |

## Lessons already learned the hard way (don't repeat these)

- **Never leave a `_needsReview` flag unresolved** once you've actually
  attempted live-doc verification and reached a conclusion — either convert
  it to a definitive `constraints` entry or fix the structural gap it
  points at. An open question that's already been answered is worse than no
  flag at all.
- **JSON-validate a file immediately after any manual multi-part edit**
  (`python3 -c "import json; json.load(open('path'))"`) before running the
  heavier `stage3_bulk.py validate` — a stray line left outside an array is
  a silent JSON syntax break that's much faster to catch this way.
- **An overlay can fully replace `overloads`** (bypassing
  `overloadPatches`/`overloadMerges`) by setting a top-level `"overloads"`
  key directly — this is how a Stage-1-missed overload (documented only in
  a worked example, not a syntax line) gets added. See
  `pipeline/semantic_overlays/QUERY.json` for the precedent.
- **A command id must equal `slugify_id(displayName)` from the doc's actual
  `<h1>`**, never a hand-typed convention guess — this is what caused the
  `TABLE`/`Table` drift this project had to fix after the fact.
- **Don't force a real "family of different commands used together by
  convention" pattern into `multiCallChain` or `stateMachine`** just because
  the schema has a slot for it — if the sequence isn't syntactically
  enforced, plain `constraints` prose is the honest choice.

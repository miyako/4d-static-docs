# 4D Command IR extraction pipeline

Reusable, re-runnable pipeline that extracts the 4D Command IR (see
`references/4d-command-ir-schema.json`) from the local static HTML mirror
under `mirror/docs/`. No network access; the mirror is the sole source.

For the initial build, the final assembled output is `out/4d-command-ir.json`
(see `stage5_assemble.py`). **To update the IR after the docs mirror
changes** (commands added/updated/removed), see `MAINTENANCE.md` instead of
re-running these stages blindly.

## Stages (implemented: 0, 1, 2, 3, 5; skipped: 4; separate follow-on: 4.5/6)

| Stage | Script | Input | Output |
|---|---|---|---|
| 0 | `stage0_manifest.py` | `mirror/docs/<version>/{commands,WritePro/commands,ViewPro/commands}` | `out/manifest.json` |
| 1 | `stage1_extract.py` | `out/manifest.json` + source HTML | `out/stage1_raw.json`, cached per-command in `cache/raw/` |
| 2 | `stage2_candidates.py` | `out/stage1_raw.json` | `out/candidates.json` (category A–S heuristic hits, for human review) |
| 3 | `stage3_bulk.py` (1443 bulk commands) + `stage3_semantic.py` (13 hand-authored fixtures) | `out/stage1_raw.json` + `pipeline/semantic_overlays/*.json` | `out/stage3_ir_full/*.json`, schema-validated per command |
| 4 | relationships enrichment | — | explicitly skipped (schema-optional, no consumer need identified yet) |
| 4.5 / 6 | `stage6_synth_examples.py` (separate follow-on effort) | `out/4d-command-ir.json` | `out/lsp_crosscheck_report.json` (`tool4d-lsp-stdio` compiler cross-check) |
| 5 | `stage5_assemble.py` | fixtures + Stage 3 output + Layer-2 registries | `out/4d-command-ir.json` (final root IR document) |

## Run

```sh
pip install -r pipeline/requirements.txt
python3 pipeline/stage0_manifest.py      # -> out/manifest.json
python3 pipeline/stage1_extract.py       # -> out/stage1_raw.json (cached)
python3 pipeline/stage5_assemble.py      # -> out/4d-command-ir.json (assumes Stage 3 already populated out/stage3_ir_full/)
```

Both scripts accept `--repo-root` (default: cwd) and print a summary
(counts, cache hits/misses, warnings) to stdout.

## Version selection

Stage 0 auto-picks the highest-numbered version folder under `mirror/docs/`
whose badge does **not** contain "BETA" (currently resolves to `21-R3`; the
top-level `mirror/docs/commands/` is the in-development next release and is
deliberately never auto-selected). Override with `--version 21` or an
explicit `--docs-root path/to/folder`.

## Scope decisions made in Stage 0 (see `out/manifest.json.skipped[]` for the
full, logged list — nothing is dropped silently)

- **In scope**: classic commands (`commands/`), 4D Write Pro commands
  (`WritePro/commands/`), 4D View Pro commands (`ViewPro/commands/`,
  indexed alphabetically via `commands-legacy/*.html` rather than by theme —
  included because they are still classic procedural pages, not OOP class
  docs; exclude with `--exclude-dir ViewPro/commands` if this pass should be
  narrower).
- **Out of scope**: `API/*.html` (OOP class reference — different HTML
  shape, excluded per the task brief), `commands/command-index.html` /
  `WritePro/commands/command-index.html` (listing pages, not commands),
  `commands/constant-list.html` (constants index), `On ... database method`
  pages (framework callback hooks — no command number, not user-callable,
  distinct doc grammar from real commands).
- A page whose `<h1>` title doesn't match its own syntax line's bolded name
  (a real, observed doc inconsistency, e.g. one View Pro page) is still
  included, using the syntax line's name (the rendered source of truth) as
  `id`/`displayName`, with a `_review` marker carrying both names.
- Legacy compiler directives (the `C_xxx` family, e.g. `C_LONGINT`) have no
  standalone page in the `21-R3` snapshot — confirmed absent from this
  version's docs entirely, not a pipeline bug. An earlier fixture for
  `C_LONGINT` was removed for this reason: it had no traceable source page,
  so the pipeline's scope is exactly the commands present in the mirror.

## Caching / idempotency

`out/manifest.json` records a content hash per command (sha1 over its
source HTML file(s)). Stage 1 (and later Stage 3) look up
`cache/<kind>/<id>.<hash>.json`; a hit skips re-parsing entirely. Re-running
after the docs change only reprocesses commands whose hash changed — this
is what makes the pipeline safe to re-run against a newer docs snapshot
without redoing unaffected work, and is the basis for Stage 5's diff report.

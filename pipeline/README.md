# 4D Command IR extraction pipeline

Reusable, re-runnable pipeline that extracts the 4D Command IR (see
`references/4d-command-ir-schema.json`) from the local static HTML mirror
under `mirror/docs/`. No network access; the mirror is the sole source.

## Stages (implemented so far: 0, 1)

| Stage | Script | Input | Output |
|---|---|---|---|
| 0 | `stage0_manifest.py` | `mirror/docs/<version>/{commands,WritePro/commands,ViewPro/commands}` | `out/manifest.json` |
| 1 | `stage1_extract.py` | `out/manifest.json` + source HTML | `out/stage1_raw.json`, cached per-command in `cache/raw/` |
| 2 | `stage2_candidates.py` (planned) | `out/stage1_raw.json` | `out/candidates.json` (category A–S heuristic hits, for human review) |
| 3 | `stage3_semantic.py` (planned) | `out/stage1_raw.json` | `cache/ir/*.json`, schema-validated per command |
| 4 | `stage4_relationships.py` (planned) | Stage 2 + Stage 3 output | `out/relationships.json` |
| 4.5 | `stage4_5_lsp_check.py` (planned) | Stage 3 output | `out/lsp_report.json` (tool4d-lsp-stdio cross-check) |
| 5 | `stage5_report.py` (planned) | everything above | `out/ir_corpus.json`, `out/diff_report.json`, `out/sample_report.md` |

## Run

```sh
pip install -r pipeline/requirements.txt
python3 pipeline/stage0_manifest.py      # -> out/manifest.json
python3 pipeline/stage1_extract.py       # -> out/stage1_raw.json (cached)
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
- `C_LONGINT` (a regression-fixture command) has no standalone page in the
  `21-R3` snapshot — confirmed absent from this version's docs entirely, not
  a pipeline bug; expected to surface as a known gap in Stage 5's report.

## Caching / idempotency

`out/manifest.json` records a content hash per command (sha1 over its
source HTML file(s)). Stage 1 (and later Stage 3) look up
`cache/<kind>/<id>.<hash>.json`; a hit skips re-parsing entirely. Re-running
after the docs change only reprocesses commands whose hash changed — this
is what makes the pipeline safe to re-run against a newer docs snapshot
without redoing unaffected work, and is the basis for Stage 5's diff report.

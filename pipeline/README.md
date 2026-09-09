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
| 4.5 / 6 | `stage6_synth_examples.py` (separate follow-on effort, see `stage6_README.md`) | `out/4d-command-ir.json` | `out/lsp_crosscheck_report.json` (`tool4d-lsp-stdio` compiler cross-check) |
| 5 | `stage5_assemble.py` | fixtures + Stage 3 output + Layer-2 registries | `out/4d-command-ir.json` (final root IR document) |

## Tooling divide: pure Python vs. licensed 4D install

Stages 0, 1, 2, 3, and 5 — the entire core pipeline that produces
`out/4d-command-ir.json` — are **pure Python** with no proprietary
dependency: they parse the static HTML mirror already checked into this
repo and require nothing beyond `pip install -r pipeline/requirements.txt`.
Anyone can clone this repo and reproduce the IR from scratch.

**Stage 6** (`stage6_synth_examples.py`, see `stage6_README.md`) is the one
exception: it synthesizes real 4D method calls and compiles them against
`tool4d`, which requires a genuine, licensed 4D installation (or the 4D
Analyzer VS Code extension's bundled copy) on the host. This is a
compiler/LSP cross-check layer used to catch real semantic bugs (e.g.
missing parameters) that schema validation alone can't — it's additive QA
on top of the IR, not a build dependency of it. `out/4d-command-ir.json` is
complete and usable without ever running Stage 6; skip it entirely if no
licensed 4D install is available.

## Out of scope: static page generation

This pipeline's output is the structured `out/4d-command-ir.json` document
itself — a machine-readable IR, not rendered documentation. Generating
human-facing static pages (an HTML/Markdown reference site, IDE
autocomplete snippets, etc.) *from* the IR is explicitly out of scope for
this repo; that is left to downstream consumers of the IR. Likewise, this
pipeline only *reads* the pre-existing `mirror/docs/` HTML snapshot — it
does not fetch, scrape, or regenerate that mirror itself.

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

## `docPage`: official permalinks, added at assembly

Every command carries an official documentation permalink:

```
docPage       https://developer.4d.com/docs/commands/copy-array
docPageLocal  mirror/docs/21-R3/commands/copy-array.html
```

Nothing is re-parsed to produce this. Stage 0 already recorded the source
page of every command in `out/manifest.json`, so stage 5 joins that by id
and derives the URL from the same path. The join is required to be
**total**: a command with no manifest entry fails the build rather than
silently shipping without a link, because that means the corpus and the
manifest disagree, not that the command is undocumented.

**The URL omits the version segment on purpose.** `/docs/21-R3/commands/...`
resolves today but stops resolving once 21-R3 is superseded, so embedding it
in a redistributable artifact would make the artifact rot on 4D's release
schedule. `docPageLocal` keeps the mirror path, which is the provenance
record of the file actually parsed and is not recoverable from the URL.

### The derivation was verified, not assumed

A version-less URL means "the current docs", and the classic corpus contains
deprecated commands whose pages could plausibly have been dropped. All 1456
were checked against the live site:

- **1456/1456 return 200**, including deprecated commands such as
  `SET LIST PROPERTIES` and `GRAPH SETTINGS`.
- Each page's `<h1>` was compared to the command's `displayName`. **Status
  codes alone are not sufficient** here: a derived slug that collided with a
  different command's page would return 200 while being the wrong page
  entirely. Only one heading disagreed, `VP Get table column attributes`,
  whose live page is headed `VP Get column attributes` -- and the mirror page
  carries that same heading, so the URL is correct and the disagreement is a
  pre-existing docs/IR inconsistency, not a mapping error.
- Negative controls in all three namespaces (`commands/`,
  `ViewPro/commands/`, `WritePro/commands/`) return a genuine 404, so the
  200s mean something. A Docusaurus site can serve a soft 404 with status
  200, in which case a sweep of real names would look identical to a sweep
  that verified nothing.

The stage additionally asserts that the set of emitted URLs is exactly the
set that was swept, so a future change to the derivation cannot quietly
produce URLs that were never checked.

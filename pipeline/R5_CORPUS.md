# 21 R5 BETA language snapshot

Both `out/4d-command-ir.json` and `out/4d-oop-ir.json` target **21 R5
BETA**, not stable R4. `out/r5_snapshot.json` records the complete input,
compiler, report and vendoring-asset hashes. This is a reviewed and
compiler-checked corpus commit, not a Release publication, merge or
substitute for required PR approvals.

## Pinned inputs

The HTML comes from `4d/docs` `gh-pages` commit
`78952faa7ceba81909b6b757a76108afa76f8993`; its installation provenance
is `mirror/snapshot.json`. R5 lives at **`mirror/docs` itself**. The
automatic selector still chooses stable `mirror/docs/21-R4`.

`references/syntaxEN-21-R5.json` and `references/21-R5/*.xlf` are
unchanged official resources from `/Applications/4D 21 R5/4D.app`,
**21 R5 build 21R5.100156**. Their SHA256/build provenance is
`references/syntaxEN-21-R5.provenance.json`. Historical R3
`references/syntaxEN.json` and stable R4
`references/syntaxEN-21-R4.json` are retained, not relabeled.
The two official XLIFF files retain their source trailing whitespace.
Do not normalize it to satisfy Git's whitespace check: their unchanged
bytes and SHA256s are the capture gate. Whitespace checks on authored
changes exclude only those two immutable files.

The compiler is
`/Applications/4D 21 R5/tool4d.app/Contents/MacOS/tool4d`, the same build.
The bridge and schema validator were provisioned from the pinned
`miyako/skills` Release **v0.0.32**, into `tools/4dlsp/` and
`tools/4dform/`. These binaries are not committed.

## Review evidence and limitations

Classic source review compares the old R3 raw records against fresh R5
records, removing only HTML, badges, source/hash metadata and whitespace/
zero-width-space noise. `out/classic_r5_review.json` has **4 added,
0 removed, 86 content-changed and 1370 unchanged** commands, with an
authored disposition for every addition/change. Existing overlays were
inspected against the word-level deltas, not accepted merely because their
ledger status was done. The OB SET fixture's duplicate Object table type
was fixed upstream; its already-correct authored signature stays unchanged.

The additions are `defer` and `Deferred formulas` (**introduced in R4**),
and `OBJECT Get padding` / `OBJECT SET PADDING` (**introduced in R5**).
R5 also adds RGB `borderColor`, three vector-index constants, two border
styles and broader radius/alignment object support. The official constants
registry additionally preserves two MCP selector constants not documented
by these command pages; they are not assumed supported members of the
documented selector enum.

`out/r5_conflict_inventory.json` consolidates parameter flags and authored
cross-command/within-page/compiler findings. It embeds the pinned R4
baseline: **10 parameter flags in R4, the same 10 in R5**, not ten new
confirmed bugs. Source reconciliation, hover-index gaps and historical
pipeline defects are kept distinct.

Selector 135's official symbol is `QUIC Connection Timeout`; its pages
call it QUIC session timeout. Both R4 and R5 GET pages describe
**seconds/default 900/minimum 60**, while SET describes
**minutes/default 15/minimum 1**. Preserve the two readings; no
compiler-success claim establishes runtime units. WEB GET BODY PART's
`name`/original-filename prose ambiguity likewise remains explicitly
documented. Other modeled corrections and upstream-open findings are
listed with dispositions and source hashes in the inventory.

Classic has **1460 commands**. Its **1338** non-View-Pro synthetic methods
exercise **2563** overload/variant blocks, freshly compiled with R5 with
zero errors/warnings. All 122 View Pro commands remain in the IR but are
intentionally excluded from synthesis because the component is not
installed. Full classic hover recognizes **1336** command tokens; the
`Begin SQL` / `End SQL` structural delimiters have no hover entry, but their
real paired blocks compile. Do not report these gaps as signature agreement.
See the OOP README and `out/oop_refresh_review.json` for OOP source and gate
dispositions; the exact final counts are in `out/r5_snapshot.json`.

OOP has **528 members**, up from 502, with no removals: quota management,
`DataClass.getIndexes`, SMTP certificate properties and Vector precision
account for the 26 additions relative to R3. It has **51 class records**
(46 built-ins), 38 enums and **968 clean synthetic compiler blocks** in
528 methods. Fresh hover has 508 agreements, three evidenced disagreements,
ten multivariant index gaps and seven dynamic stand-ins; none are unexplained.
The documented quota type name differs from the accepted compiler name
`4D.QuotaManagerClass`, and TCP port acceptance does not validate the
documented Integer/runtime port domain.

Five additions already existed in stable R4: `Session.quotas` and
`QuotaManagerClass.currentValues`, `.defaultEntitySetTimeout`,
`.maxEntitySetTimeout`, `.nbEntitySets`. The **21 new R5 members** are
`DataClass.getIndexes`, the remaining 15 quota limit/rate properties,
`SMTPTransporter.certificate` / `.certificateName` / `.certificatePassword`,
`Vector.precision` and `WebServer.quotas`. The exact partition against
the pinned R4/R5 fixed signatures is recorded in the OOP review.
QuotaManagerClass itself was introduced in R4; its new class record is
an addition relative to this repository's R3 baseline, not a claim of
R5 class introduction. R5 additionally extends `4D.Vector.new` with an
optional precision parameter; `Session.setPrivileges`' Boolean return
annotation is a documentation correction, not a new API.

`python3 pipeline/verify_oop_project.py` reruns the full R5 project pass
and retains every diagnostic, including `SynthOOPHandler.4dm` and
`SynthOOPCallback.4dm`. `out/oop_project_compiler_report.json` and its
provenance confirm **530 project files, zero diagnostics**. This closes
the evidence gap in the earlier target-only G4 report; helper diagnostics
are not silently discarded.

All 523 published OOP code blocks were reharvested. The 499 checked 4D
snippets yield **269 compiler-verified, zero wrapped rescues and 230
unverified**; unverified fragments remain verbatim, with explicit reasons,
not fabricated tables/classes or copied R3 verdicts. Example coverage is
147 members with verified documentation examples, 78 with only unverified
documentation examples and 303 synthetic-only; all 528 have a synthetic
example. These verdicts mean the performed `checkSyntax` checks, not runtime
execution, exhaustive arity validation or a full-application compile.

## Rebuilding

Install `pipeline/requirements.txt`, provision tools per `skills/4dtools`,
and keep the compiler path explicit:

```sh
export TOOL4D_PATH="/Applications/4D 21 R5/tool4d.app/Contents/MacOS/tool4d"
python3 pipeline/tools/parse_xliff_constants.py --data-dir references/21-R5
python3 pipeline/stage0_manifest.py --docs-root mirror/docs
python3 pipeline/stage1_extract.py
python3 pipeline/stage2_candidates.py
python3 pipeline/stage3_semantic.py
python3 pipeline/stage3_bulk.py init
python3 pipeline/stage3_bulk.py validate --all
python3 pipeline/stage5_assemble.py
python3 pipeline/stage6_synth_examples.py generate --all
python3 pipeline/stage6_synth_examples.py validate --all
```

`validate --all` explicitly rebuilds even done ledger entries. It does not
perform semantic review; the authored overlays and review decisions are
inputs to this reproducible build. Missing targeted compiler files are
unverified and fail the gate instead of receiving a clean verdict.

For OOP, run stages O0 through O5 with
`--docs-root mirror/docs` on source-reading stages and
`--syntax-json references/syntaxEN-21-R5.json` on syntax-reading stages;
O0b additionally takes `--syntax-version 21-R5`. Follow
`oop/README.md` and `oop/stage6_README.md` for their precise flags.
Then rerun O7/O6/O8/O9/O10 in order. Reharvesting O7 intentionally discards
the old examples' verification state; R3 verdicts must not be copied back.
Regenerate crosslinks after both final IRs are assembled.

Start the classic hover server only after compiler checks finish; concurrent
checks on the same project can interfere with the LSP session:

```sh
tools/4dlsp/tool4d-lsp-stdio mcp \
  --project "$PWD/Project/4DCommandIRSynthCheck.4DProject"
python3 pipeline/stage6_hover_crosscheck.py
tools/4dlsp/tool4d-lsp-stdio mcp --stop \
  --project "$PWD/Project/4DCommandIRSynthCheck.4DProject"
```

The OOP server is project-scoped separately. Do not attach its hover calls
to the classic server. Record compiler/hover limitations, not a
success-shaped fallback.

The six new vector-constant call sites are retained as the **compile-only**
fixture `pipeline/tests/fixtures/R5VectorIndexProbe.4dm`. Run
`python3 pipeline/run_classic_r5_controls.py` before the final full compiler
pass; it removes its temporary methods and records
`out/classic_r5_controls.json`. These calls check symbol/signature acceptance,
not vector index applicability to that test table's fields. A fabricated
command is a required rejection control. Historical empty-call restrictions
for `QR REPORT` / `REGISTER CLIENT` are not reproduced by this R5
`checkSyntax` interface, and are not counted as passed negative tests.
Conservative synthesis constraints remain; this gate does not establish
empty-call runtime/full-compiler validity.

```sh
python3 pipeline/review_classic_refresh.py --baseline-ref fa1ca73b4 \
  --decisions pipeline/reviews/21-R5-classic.json
python3 pipeline/verify_oop_project.py
python3 pipeline/build_conflict_inventory.py
python3 pipeline/record_r5_snapshot.py
python3 -m unittest discover -s pipeline/tests -v
python3 -m unittest discover -s pipeline/oop/tests -v
python3 -m unittest discover -s scripts/static_docs/tests -v
tools/4dform/boon references/4d-command-ir-schema.json \
  out/4d-command-ir.json out/4d-oop-ir.json
```

## Downstream vendoring

Both existing `scripts/refresh-vendor.sh` scripts take
`<full-upstream-commit-sha> [local-source-repo]`. Run them from their
respective CLI repositories **after** this upstream snapshot is committed:

```sh
scripts/refresh-vendor.sh <full-upstream-commit-sha> <this-worktree-path>
```

Classic consumes `out/4d-command-ir.json`, `out/synth_manifest.json` and
`Project/Sources/Methods/Synth_*.4dm`. OOP consumes
`out/4d-oop-ir.json`, `out/oop_doc_examples.json`,
`out/oop_synth_manifest.json`, `out/oop_corpus_stats.json` and
`oopcheck/Project/Sources/Methods/SynthOOP_*.4dm`. Their existing JSON root
shapes are retained. Pin every input to the **same commit**, then run each
CLI's `cargo test` and review ranking/count changes there. The refresh
scripts currently write `branch=main` even for a feature commit; the
explicit pinned commit is the authoritative source identity.

No downstream CLI files, Releases or merges are performed by this update.

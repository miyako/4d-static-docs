# `pipeline/oop/` — the 4D OOP intermediate representation

This pipeline builds `out/4d-oop-ir.json`: **528 in-scope members** of **46
built-in classes**, plus class-store access, in the same three-layer shape as
the separate classic IR. Both validate against
`references/4d-command-ir-schema.json`. The OOP document contains **51 class
records**: 46 built-ins, `4D` and `cs` namespaces, and three ORDA templates.
See [SCOPE.md](SCOPE.md) and [stage6_README.md](stage6_README.md).

## Current sources: explicit 21 R5 beta

| Source | Content |
|---|---|
| `references/syntaxEN-21-R5.json` | Unmodified authoritative signatures: 521 fixed members, 618 overload/type lines |
| `mirror/docs/API/*.html` | 47 API pages; actual badge **21 R5 BETA** |
| `references/4d-constants-registry.json` | Shared constant values, generated separately before O3 |

The capture SHA256 is
`ee27d9689e834bd1990d60d289d8c4e86e39beb723fe88c55b719e9d1e8bc411`.
`out/oop_manifest.json` records the badge, path, declared syntax version
**21-R5**, SHA1 and SHA256. This is not a stable-release claim.
`out/oop_refresh_review.json` additionally embeds the official capture
provenance, refreshed shared-constants hashes/counts, compiler provenance,
gate/example summaries, and substantive semantic review.
It binds final OOP artifacts/examples/manifests and source pages/captures by
SHA256, and verifies every method against the compiled manifest. The review's
own hash belongs in the parent snapshot to avoid circular hashing.

The matched compiler is
`/Applications/4D 21 R5/tool4d.app/Contents/MacOS/tool4d`; its Info.plist reports
**21 R5 build 21R5.100156**. Its installed syntax resource has the same SHA256.
The LSP bridge is `tools/4dlsp/tool4d-lsp-stdio`, **0.3.0**, provisioned through
the mirrored skills **v0.0.32**. Compiler stages require explicit `TOOL4D_PATH`
and record provenance; a readable installed capture must match the manifest.

**Never run this refresh through the stable auto-selector.** It intentionally
still selects the highest non-beta version (currently R4). The beta lives at
the unversioned `mirror/docs` root. Existing stable defaults are unchanged.

## Reproduce the corpus

O0–O5 are pure Python; only compiler checks need tool4d.

```sh
pip install -r pipeline/requirements.txt
SYNTAX=references/syntaxEN-21-R5.json
python3 pipeline/oop/stage0_reconcile.py --docs-root mirror/docs --syntax-json "$SYNTAX"
python3 pipeline/oop/stage0_manifest.py --docs-root mirror/docs --syntax-json "$SYNTAX" --syntax-version 21-R5
python3 pipeline/oop/stage1_extract.py --docs-root mirror/docs --no-cache
python3 pipeline/oop/stage2_signatures.py --syntax-json "$SYNTAX"
python3 pipeline/oop/stage2b_crosscheck.py --syntax-json "$SYNTAX"
python3 pipeline/oop/stage3_merge.py --syntax-json "$SYNTAX" --no-cache
python3 pipeline/oop/stage4_classes.py --syntax-json "$SYNTAX"
python3 pipeline/oop/stage5_assemble.py
python3 pipeline/oop/check_schema_gate.py --syntax-json "$SYNTAX"

# Crosslinks read both corpora: run after classic assembly, not during it.
python3 pipeline/oop/stage6_crosslinks.py
```

## Stages and invariants

* **O0 reconciliation / manifest:** every member-shaped heading is accounted
  for, including inherited and dynamic members. The 608 headings include 523
  matched headings representing 521 unique fixed members, 78 inherited
  headings, and seven dynamic members. Two duplicate matches are recorded
  separately; missing and unaccounted fixed members are both zero.
* **O1 extraction:** descriptions, parameter/history/constant/shape tables,
  syntax, examples and See also. R5 has a dedicated `Transporter.html` page;
  its 11 abstract-base members remain modelled once. `WebForm` and
  `WebFormItem` use `h3` members.
* **O2 syntax parser:** trivia-preserving tokenizer and recursive-descent AST.
  AST rendering must consume every token and reconstruct its original bytes.
  Optional brace groups, variadics, overloads and malformed source markdown
  are preserved, not silently normalized.
* **O2b parameter cross-check:** ten recorded source-convention/conflict
  items, not ten missing members. Named normalizations handle variadics,
  capitalization and nullable result conventions; constructor conflicts are
  reviewed via overlays.
* **O3 merge:** joins signatures and enrichment, including member-scoped
  constant enums. Numeric type alone is not proof that a prose constant is
  that parameter's accepted value. Quota contracts additionally retain
  narrative under Scope levels / At startup / At runtime rather than only the
  short Description section. Only exact History `Added` marks introduction.
* **O4 classes:** authored recipes in `class_instantiation.json` are required
  for every class. ORDA templates use the check project's concrete model.
  `member_of`, `returns_instance_of` and `obtained_via` edges are generated.
* **O5 assembly:** applies evidenced overlays, removes internal bookkeeping,
  checks id collisions, enforces manifest parity and validates the full IR.
  Generated artifacts are never manually patched.
* **Crosslinks:** `out/4d-ir-crosslinks.json` contains explicit-corpus edges;
  classic equivalents are curated, not inferred from name similarity.

Ten properties have multiple type variants. `Accessor.type` carries every
variant (a single type or a list with at least two entries), and
`accessor.rawSyntax` preserves the whole `<br/>`-joined field. This includes
the new `SMTPTransporter.certificate : 4D.File | Blob`. A narrow but legal type
can compile, so compiler success alone cannot detect a lost variant.

## Semantic review of the R3 → R5 refresh

The old artifacts were preserved in ignored `extraction/oop-baseline/` before
overwriting. `review_refresh.py` generates `out/oop_refresh_review.json`,
separating section/signature changes from page hashes/navigation:

* **26 added members, none removed; one added built-in class.**
  Additions are 19 `QuotaManagerClass` properties, `Session.quotas`,
  `WebServer.quotas`, `DataClass.getIndexes`, three SMTP certificate properties,
  and `Vector.precision`. Quota support spans R4/R5: these are additions
  versus R3, not all first introduced in R5.
* **Two changed fixed signatures:** optional Vector constructor precision
  (32/64, `mk single precision` / `mk double precision`) and the explicitly
  Boolean Collection overload of `Session.setPrivileges` (a correction, not
  a newly added API).
* **11 changed extracted sections.** Substantive existing contracts include
  `Session.info.unreachableSince` and read-only status, and quotas in
  `WebServer.start` settings. Other changes include refreshed examples,
  punctuation, a leading article, and a duplicate See also heading.
* **Eight overlays reviewed, none orphaned.** The four prior File/Folder/TCP
  constructor and `Collection.multiSort` overlays remain applicable.
  Folder's invalid constructor `*`, multiSort's Collection parameter, the
  no-argument IMAPNotifier recipe and ZipFile's producer were re-probed with
  positive/negative R5 controls, not accepted from old verdicts.
* **Two new quota overlays:** docs and hover spell `4D.QuotaManager`, but
  tool4d 21R5.100156 rejects that declaration and accepts
  `4D.QuotaManagerClass`. Semantic types follow the compiler while raw source
  remains verbatim. `WebServer.quotas` itself is not assignable; modify its
  existing properties instead.
* Two Vector overlays apply the documented immutable class contract to both
  `length` and the new `precision` property; neither is writable.

## Gates and provenance

The review artifact includes every mechanical/manual conflict and its
disposition. Fresh R4 comparison has the same **ten flags across nine
members**, with zero added/removed/changed flags in R5. Eight manual
compiler/documentation issues are also recorded; one overlaps the TCP
mechanical flag, giving **17 distinct reviewed items**, not 17 compiler
failures. The compiler corpus still has zero diagnostics.

To reproduce the isolated R4 comparison before `review_refresh.py`, use
`stage1_extract.py --docs-root mirror/docs/21-R4` and
`stage2_signatures.py --syntax-json references/syntaxEN-21-R4.json`, sending
their outputs to `extraction/oop-r4-conflict-comparison/raw.json`,
`signatures.json` and `roundtrip.json`. Then run `stage2b_crosscheck.py` with
that capture, `--raw`/`--signatures` pointing at those outputs and
`--out extraction/oop-r4-conflict-comparison/conflicts.json`. This reads only
OOP sources and does not claim R4 compiler verification.

| Gate | Fresh result |
|---|---|
| G1 byte-exact syntax rendering | **618/618 lines; 521/521 fields** |
| G2 schema compatibility | Both corpora and both example documents valid; seven conditional cases pass |
| Verbatim source invariant | **521/521**: 278 callables + 243 properties; four negative probes detected |
| G3 manifest coverage | **528/528**; four logged scope exclusions, no member excluded |
| G4 synthetic compiler check | **528 methods / 968 blocks; zero errors and warnings** |
| G5 hover cross-check | **508 agree; three evidenced disagreements; zero unknown; ten multivariant index gaps; seven dynamic stand-ins** |
| Class/semantic controls and acceptance probes | **66 expected outcomes pass**, including all 46 fixed class declarations and deliberate invalid controls |
| Member-link audit | **528/528** anchors name their member; 43 pages fetched, zero fetch failures |

Schema gates used installed Python `jsonschema`; the OOP IR and example
document were additionally revalidated with the subsequently provisioned
`tools/4dform/boon`. The review artifact records both engines.
`check_type_names.py` generates and then cleans up
its control methods, recording `out/oop_type_name_crosscheck.json`. TCP port
probes even accept unsuitable Text/Collection arguments, so compilation alone
does not validate the port domain; the IR follows the documented Integer
parameter table. Abstract
class declaration names are checked directly even though synthesis uses
concrete receivers. Compile success does not establish runtime
instantiability, network behavior, REST enforcement or permission semantics.

`docPage` is an official version-less permalink with the member's section
anchor; `docPageLocal` preserves the exact beta mirror path. Constructors
anchor on their fully-qualified names, not a shared `#new`.

O7 deliberately invalidates old example verdicts. The R5 refresh reran O7/O8
completely, supporting both old `span.token-line` and new `div.token-line`
markup without collapsing newlines. Remaining examples and hover limitations
are reported in [stage6_README.md](stage6_README.md), not silently skipped.

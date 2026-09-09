# OOP IR synthesis check project

Throwaway 4D project used by `pipeline/oop/stage6_synth_examples.py`
(Phase 5) and `pipeline/oop/stage7_doc_examples.py` (Phase 4) to
compiler-check generated and harvested OOP code with `tool4d`.

It is the OOP sibling of the classic corpus's `Project/`
(`4DCommandIRSynthCheck`) and is deliberately kept separate so the two
corpora never contaminate each other's `check-syntax` results.

## Why the extra `oopcheck/` directory level

`tool4d` only opens a project whose enclosing folder is literally named
`Project`. This was confirmed empirically: an identical project laid out
as `ProjectOOP/4DOOPIRSynthCheck.4DProject` + `ProjectOOP/Sources/...`
made `tool4d` exit before answering `experimental/checkSyntax`
(`failed to read LSP header: failed to fill whole buffer`, ~10 s, every
time, even with a one-line `var $t : Text` method and with the classic
corpus's own known-good catalog copied in). Moving the exact same tree to
`oopcheck/Project/` made it work immediately. Two `.4DProject` anchors
could not share the repo-root `Project/` folder either, hence the extra
level.

Invoke it as:

```sh
tools/tool4d-lsp-stdio check-syntax --json --workspace oopcheck/Project/
```

## Catalog

`Project/Sources/catalog.4DCatalog` exists to make the ORDA class family
(`DataStore`, `DataClass`, `Entity`, `EntitySelection`, and the `cs.`
templates — ~88 IR members) synthesizable at all: none of them can be
obtained without a real structure.

- `SynthTable` — a Longint auto-sequence primary key plus **one field per
  4D field type** (Boolean, Integer, Longint, Real, Date, Time, Alpha,
  Picture, Text, Blob, Object), so any typed ORDA attribute expression a
  sweep needs already exists.
- `SynthRelated` + an N→1 relation (`relatedRow` / `synthRows`) — so
  related-entity and related-entities ORDA attributes are reachable too.

Validate after any change (per `skills/4dcatalog/SKILL.md`):

```sh
tools/xmllint --noout --nonet --dtdvalid schemas/4dcatalog/base.dtd \
  oopcheck/Project/Sources/catalog.4DCatalog
```

Extend the catalog rather than working around a missing shape in the
synthesizer.

## Generated sources

`Project/Sources/Methods/SynthOOP_*.4dm` (Phase 5) and
`Project/Sources/Methods/DocEx_*.4dm` (Phase 4) are generated — never
hand-edit them. `Project/Sources/Classes/` holds the small set of
hand-written support classes the generators need (see the classes' own
header comments).

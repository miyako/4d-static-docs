# 4D Command IR — three-layer schema

Files:
- `4d-command-ir-schema.json` — the JSON Schema (Draft 2020-12) itself.
- `4d-command-ir-examples.json` — worked examples covering every worst-case
  command we stress-tested (`ORDER BY`, `ORDER BY FORMULA`, `C_LONGINT`,
  `Table`, `OB SET`, `MULTI SORT ARRAY`, `SET LIST ITEM PROPERTIES`,
  `SET LIST PROPERTIES`, `GRAPH`/`GRAPH SETTINGS`, `QUERY BY ATTRIBUTE`,
  `SQL EXECUTE`, `WA EXECUTE JAVASCRIPT FUNCTION`, `WP SET ATTRIBUTES`).
  Validates cleanly against the schema (0 errors, checked with `jsonschema`).

## Why three layers, not one flat per-command schema

A flat `{command: {overloads: [...]}}` schema handles most of the corpus fine,
but several real patterns are either (a) relationships *between* command
entries, not properties *within* one, or (b) reusable substructures that
hundreds of commands share and shouldn't each re-derive. Forcing those into a
per-command object either duplicates data across hundreds of entries or
silently loses the relationship entirely (e.g. "these two commands must not
both be called" can't live inside either command's own JSON object).

**Layer 1 — per-command signatures.** `commands[]`, each a `CommandEntry` with
one or more `Overload`s. This is the bulk of the corpus.

**Layer 2 — shared, named substructures**, referenced by key from Layer 1
instead of inlined: `enums`, `subGrammars`, `foreignGrammars`, `protocols`
(`multiCallChains`, `stateMachines`), `handleTypes`, `callbackContracts`.
Author these once; hundreds of commands point at them.

**Layer 3 — relationships**, a flat array of edges between command/overload
entries: `supersedes`, `conflicts_with`, `diff_from`, `equivalent_overloads`,
`same_mechanism_family`, `platform_variant`.

## Category → schema construct traceability

Every category from the taxonomy (see `4d-syntax-scan-prompt.md`, categories
A–S) maps to a specific construct below. If a future scan finds a command that
doesn't fit any row, that's a signal the schema itself needs a new construct,
not just a new command entry.

| Cat. | Pattern | Schema construct |
|---|---|---|
| A | Multi-call builder continuation | `protocols.multiCallChains`, referenced via `CommandEntry.protocolRefs.multiCallChain` |
| B | Repeatable interlaced pairs/tuples | `VariadicGroup` (`members`, `cardinality.min/max`, `position`) |
| C | Leading `*` dual signature | `Parameter` with `type: literal_symbols`, plus `Overload.discriminatedBy` on the affected sibling param; cross-command instances tagged `same_mechanism_family` in Layer 3 |
| D | Property/constant → value-type dependency | `TypeRef` kind `enum_ref` pointing into `enums{}` |
| E | Optional param omission triggers UI dialog | `Parameter.blocksOnOmission` |
| F | Special literal symbols as argument values | `TypeRef` kind `literal_symbols` |
| G | Array element type selects call semantics | `Parameter.elementTypeSelectsMode` |
| H | Magic/sentinel reference values | `Parameter.sentinelValues` |
| I | Variadic pairs vs. object-map equivalence | Two `Overload`s with `mechanism: "object_map_equivalent"` + Layer 3 `equivalent_overloads` edge |
| J | Embedded foreign-language grammar in a string param | `TypeRef` kind `foreign_grammar_ref` → `foreignGrammars{}` (explicitly `validatableByThisCorpus: false`) |
| K | Signature defined by an external/discovered artifact | `CommandEntry.externalSchemaSource` |
| L | Multi-command ordered/nested sequence | `protocols.stateMachines`, referenced via `CommandEntry.protocolRefs.stateMachine` |
| M | Opaque produce/consume/destroy handle | `handleTypes{}`, referenced via `CommandEntry.handleRoles` |
| N | Deferred callback with implicit contract | `callbackContracts{}`, referenced via `CommandEntry.callbackContractRef` |
| O | 4D pseudo-types (`Operator`, `Expression`, `any`, ...) | `TypeRef` kind `pseudo` |
| P | Silent coercion to a default type across a language boundary | `Parameter.silentCoercionDefault` |
| Q | Deprecated-but-must-pass-a-placeholder param | `Parameter.placeholderRequired` |
| R | Cross-parameter joint validation (not a repeating group) | `Overload.jointConstraints` |
| S | Statically indistinguishable overloads (same declared type, different meaning) | `TypeRef` kind `pointer_unresolved` + `Overload.staticallyDistinguishable: false` |
| — | 4D-native sub-grammar inside a Text param (distinct from J) | `TypeRef` kind `subgrammar_ref` → `subGrammars{}` |
| — | Directional partial flag override (MODIFY SELECTION's two trailing `*`) | `Overload.interactionNotes` |
| — | Near-duplicate commands (delta-doc) | Layer 3 `diff_from` edge |
| — | Command deprecated by absorption into a sibling overload | Layer 3 `supersedes` edge, `to.overloadIndex` scoped |
| — | Mutual exclusion between commands | Layer 3 `conflicts_with` edge |
| — | Platform-conditional overload validity | `Overload.platformConstraints` |

## What's deliberately *not* mechanized

Per the "Tier 2" discussion earlier: some fields exist to **carry an honest
warning**, not to resolve an ambiguity mechanically. `pointer_unresolved`,
`foreign_grammar_ref`, and `externalSchemaSource` are the clearest examples —
a validator can't check these calls are "correct" the way it can check a
concrete-typed parameter; it can only confirm the schema has flagged that the
correctness of this call depends on something outside the corpus's authority
(a pointer's runtime target, an external grammar, a fetched WSDL). That's
intentional: forcing false determinism into those fields would be worse than
representing the gap accurately, since a coding agent needs to know exactly
where it must hedge, trace a value's origin, or ask, rather than pattern-match
with false confidence.

## Suggested next steps

1. Run the exhaustive scan (`4d-syntax-scan-prompt.md`) to get real corpus-wide
   counts per category, then prioritize which `Layer 2` templates (especially
   the ~167-command `star_operator_dual_signature` pattern and the
   ~92-command `writepro_variadic_or_object_map` pattern) get authored and
   validated first, since fixing/improving a shared template pays off across
   every command that references it.
2. Build the extraction pipeline: deterministic HTML-table parsing for the
   parameter table → LLM-assisted extraction constrained to emit valid
   instances of this schema (validate every extraction against
   `4d-command-ir-schema.json` before accepting it) → targeted prose
   extraction for `constraints`, `jointConstraints`, `interactionNotes`, and
   Layer 2/3 relationships, which live in free text today.
3. Spot-check a stratified sample (weighted toward multi-overload/variadic
   commands, per the earlier discussion) against the live doc pages before
   trusting the corpus at scale.

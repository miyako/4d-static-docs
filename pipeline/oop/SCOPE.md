# OOP IR — scope decisions

Companion to `PLAN.md`. This file records what the OOP IR covers, what it
deliberately does not, and why. It follows the same discipline as the classic
pipeline's `out/manifest.json.skipped[]`: **nothing is dropped silently**.

Machine-readable counterpart: `out/oop_source_diff.json` (Phase 1.2), produced
by `pipeline/oop/stage0_reconcile.py`.

## Sources and version pinning

| Source | Path | Role |
|---|---|---|
| Typed spine | `references/syntaxEN.json` | signatures, param types/directions, summaries |
| Prose enrichment | `mirror/docs/21-R3/API/*.html` | descriptions, constraints, history, see-also, examples |

Both are pinned to **21-R3**. `mirror/docs/21-R3/` is auto-selected by the
shared `pipeline/common/docsroot.py` (highest non-BETA version folder), and can
be overridden with `--version` / `--docs-root`.

`syntaxEN.json` carries no version marker of its own. The repository owner has
confirmed it was captured from 21-R3, matching the mirror. Every stage takes a
`--syntax-json` flag so a future capture is swappable, and O0 records the
pinning (path, sha1, declared version) in `out/oop_manifest.json`.

## Corpus size (verified, not assumed)

| Surface | Count |
|---|---|
| Built-in classes in `syntaxEN.json` | 45 |
| API pages in `mirror/docs/21-R3/API/` | 45 |
| Functions (keys ending in `)`) | 258 |
| Properties | **218** |
| `4D.<X>.new()` constructors | 19 |
| **Total syntaxEN members** | **495** |
| Overload lines (`<br/>`-separated) across all members | 591 |

> The brief's figure of 227 properties (and hence 504 members) counted the nine
> `_inheritedFrom_` sentinel keys as properties. They are superclass
> declarations, not members. The corrected total is **495**.

## In scope

- The 45 built-in classes and all 495 of their members: functions, properties
  and the 19 class-store constructors.
- `Transporter`, an abstract base class with **no API page of its own**. Its 11
  members are documented only on the `IMAPTransporter`, `POP3Transporter` and
  `SMTPTransporter` pages. It is modelled as a real class
  (`isAbstract: true`, `docPage: null`) so its members are declared exactly
  once and the three subclasses inherit them.
- Inherited members. Nine classes declare a superclass via `_inheritedFrom_`
  (`File→Document`, `Folder→Directory`, `ZipFile→Document`,
  `ZipFolder→Directory`, `IMAPTransporter`/`POP3Transporter`/`SMTPTransporter`
  `→Transporter`, `Method→Function`, `Formula→Function`). Each such member is
  **declared once on the declaring class** and linked to every inheriting class
  with a Layer-3 `member_of` edge — not duplicated as a second entry.
- Documented dynamic pseudo-members (7 of them, see below), carried as
  `dynamicMember: true` entries with a name pattern instead of a fixed name.
- `cs.` / `4D.` class-store *access* semantics, as a Layer-2 protocol rather
  than per-class entries.

## Out of scope (logged, not silently dropped)

| Excluded | Reason |
|---|---|
| `mirror/docs/21-R3/aikit/` | 4D AIKit is a **component**, not the base language. Same reasoning that kept 4D View Pro's OOP surface out of the classic corpus. It also cannot be provisioned in the throwaway check project that Phase 5 needs, so its entries could never be compiler-verified. Revisit only if that changes. |
| ORDA *generated* classes (`cs.<DataClass>`, `cs.<DataClass>Entity`, `cs.<DataClass>Selection`) | Their members are derived from the user's data model, so they have no fixed signatures. Modelled as a Layer-2 template/protocol, not as command entries. |
| `mirror/docs/21-R3/Concepts/` | Language *grammar* (class declaration syntax, `Function`/`property` keywords, `#DECLARE`, shared objects), not member signatures. Only the subset needed to synthesize valid calls is captured, as a Layer-2 sub-grammar. |
| `_command_` key in `syntaxEN.json` (1353 entries) | The classic corpus, already covered by `out/4d-command-ir.json`. |
| `mirror/docs/21-R3/ORDA/`, `WebServer/`, `REST/` narrative pages | Conceptual guides; the class reference for these lives in `API/`, which is in scope. |

## Phase 1.2 reconciliation result

`out/oop_source_diff.json` joins every member-shaped heading on the 45 API
pages against the `syntaxEN.json` keys for the corresponding class. The join
balances exactly — 0 unaccounted members on either side.

| Category | Count | Meaning |
|---|---|---|
| `matched` | 484 | present in both sources |
| `inherited_from_superclass` | 78 | documented on a subclass page, declared on an ancestor in `syntaxEN` |
| `dynamic_member` | 7 | placeholder heading, no fixed name |
| `syntaxen_missing` | **0** | — |
| `doc_missing` | **0** | — |
| **Total doc headings** | **569** | |

Accounting on the `syntaxEN` side: 484 matched + 11 declared on the orphan base
class `Transporter` = **495**, i.e. **0 unaccounted**.

**The 559-vs-495 delta is essentially all inheritance.** 78 of the 85 deltas
are members that a subclass page re-documents but `syntaxEN` files once on the
ancestor. Every one carries an `evidence` string naming the `_inheritedFrom_`
hop that classified it.

The 7 dynamic members:

| Class | Member | Why it has no fixed name |
|---|---|---|
| `DataClass` | `.attributeName` | attribute name comes from the user's data model |
| `Entity` | `.attributeName` | ditto |
| `EntitySelection` | `.attributeName` | ditto |
| `DataStore` | `.dataclassName` | dataclass name comes from the user's data model |
| `4D` (ClassStore) | `.classStoreName` | names a class store (`4D` or `cs`) |
| `4D` (ClassStore) | `.classClassName` | names a class inside a class store |
| `WebForm` | `.componentName` | names a component in the web form |

### Normalizations applied to make the join (recorded, not hidden)

These are transformations this pipeline performs, not disagreements between the
sources. They are annotated on the matched pairs in `out/oop_source_diff.json`.

1. **Zero-width space.** Every member heading in the mirror ends with `U+200B`
   (a Docusaurus anchor artifact). Stripped on all 484 matches.
2. **Parameter-list truncation.** Headings render the full parameter list
   (`.copyTo( destinationFolder ; ... )`); `syntaxEN` keys carry only
   `copyTo()`. The heading is truncated to `()` for joining only — the real
   parameters come from the parsed `Syntax` string, never from the heading.
3. **Heading level.** 43 pages use `<h2>` for members; `WebForm` and
   `WebFormItem` use `<h3>` (9 members). Both levels are accepted.
4. **Page title vs class key.** Six pages title themselves differently from
   their `syntaxEN` key: `Directory Class`→`Directory`,
   `Document Class`→`Document`, `ZIPArchive`/`ZIPFile`/`ZIPFolder`→
   `ZipArchive`/`ZipFile`/`ZipFolder`, `ClassStore`→`4D`.
5. **Constructor placement.** `4D.<X>.new()` is documented on `<X>`'s own class
   page (e.g. `4D.Blob.new()` on `BlobClass.html`), *not* on
   `ClassStoreClass.html`. The joiner attributes it to the target class.

103 non-member headings (`Description`, `Example`, `See also`, `History`,
`[index]`, `IMAPNotifier object`, `Commands and functions`, …) are recorded in
`nonMemberHeadings` rather than discarded.

## Known source defects carried forward

Found while parsing the 591 overload lines; each is preserved verbatim in the
IR's raw syntax and normalized only for the semantic member name.

| Member | Defect |
|---|---|
| `CryptoKey.sign` (2 overloads) | markdown emphasis misplaced: `.**sign** (…)` instead of `**.sign**(…)` |
| `CryptoKey.verify` (1 overload) | markdown emphasis misplaced: `*.verify**(…)` |
| `4D.Folder.new` (2 overloads) | trailing bare `*` flag param, modelled with the existing `literal_symbols` `TypeRef` |

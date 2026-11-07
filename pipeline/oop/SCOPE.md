# OOP IR — scope decisions

Nothing is dropped silently. Machine-readable scope and reconciliation live
in `out/oop_manifest.json` and `out/oop_source_diff.json`.

## Current sources and size

The current corpus uses explicit `--docs-root mirror/docs` (**21 R5 BETA**)
and `references/syntaxEN-21-R5.json` with `--syntax-version 21-R5`.
The shared stable auto-selector remains unchanged; it does not choose this
unversioned beta root. [README.md](README.md) records exact hashes and compiler
provenance.

| Surface | Count |
|---|---|
| Built-in syntax-resource classes, excluding `4D` / `_command_` | 46 |
| API pages | 47 |
| Fixed callable members, including 19 constructors | 278 |
| Fixed properties | 243 |
| Fixed syntax-resource members | 521 |
| Overload/type-variant lines | 618 |
| Dynamic pseudo-members | 7 |
| **Total IR members** | **528** |
| Class records (46 built-ins + two namespaces + three ORDA templates) | 51 |

The `_inheritedFrom_` sentinels are superclass declarations, not properties.
The seven dynamic entries are counted as property-kind members, bringing the
IR's kind totals to 259 functions, 250 properties and 19 constructors.

## In scope

* Every fixed member in the 46 built-in class maps and all 19 class-store
  constructors.
* Abstract `Transporter`, with its own R5 `API/Transporter.html` page. R3 had
  no page, but its 11 members were already in scope through subclasses.
* Inherited members, modelled once on the declaring class, not duplicated
  per subclass. Nine class maps encode inheritance.
* `4D` and `cs` class-store access semantics.
* ORDA generated classes as three Layer-2 templates, not per-model APIs.
* All documented dynamic pseudo-members:

| Class | Heading | Meaning |
|---|---|---|
| DataClass | `.attributeName` | user-model attribute |
| Entity | `.attributeName` | user-model attribute |
| EntitySelection | `.attributeName` | user-model attribute projection |
| DataStore | `.dataclassName` | user-model dataclass |
| 4D | `.classStoreName` | class-store name |
| 4D | `.classClassName` | class inside a store |
| WebForm | `.componentName` | web-form component |

Dynamic entries are synthesized using concrete check-project stand-ins; they
are not omitted from the compiler check. Hover cannot match the literal
placeholder and records them separately.

## Out of scope

The manifest logs four scope exclusions, none excluding an in-scope member:

* `aikit/`: component API, not the built-in base language.
* `Concepts/`: grammar/narrative, not fixed member signatures.
* `ORDA/`: conceptual guide; its class reference in `API/` is included.
* `_command_`: classic commands are maintained in the separate classic IR.

Other WebServer/REST narrative pages are not standalone command entries;
relevant API-page narrative is retained as member enrichment.

## Reconciliation and source artifacts

608 member headings are accounted for: **523 matched headings** representing
**521 unique fixed members**, 78 inherited headings and seven dynamic
headings. Two duplicate matches are recorded separately. Missing syntax,
missing documentation and unaccounted fixed members are all **zero**.

105 non-member headings are recorded separately. The join normalizes heading
zero-width spaces, removes rendered argument lists for key matching, accepts
`h2`/`h3` members and maps page-title aliases, including
`QuotaManager` → `QuotaManagerClass`. Constructors join to their target-class
page, not the class-store page.

Three malformed markdown signature lines (`CryptoKey.sign` twice,
`CryptoKey.verify` once) are preserved byte-exactly while semantic member
names are normalized. Ten multi-variant properties retain all their source
lines and types, including the new SMTP certificate property.

The R3→R5 review has **26 genuine member additions, zero removals, two changed
signatures and 11 changed extracted sections**. Quota introduction spans R4/R5;
do not invent individual property introduction dates from the class History
table. [stage6_README.md](stage6_README.md) records compiler controls,
documented/compiled quota-type disagreement and remaining example/hover
limitations.

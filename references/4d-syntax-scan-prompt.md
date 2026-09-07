# Task: Exhaustive syntax-pattern audit of the 4D language command reference

## Background

4D is a proprietary 4GL/database language with roughly 1,300 built-in "classic"
commands (procedural, e.g. `ORDER BY`, `OB SET`) documented at
https://developer.4d.com/docs/commands/command-index, plus a smaller set of
OOP-style classes with member methods (e.g. `4D.Blob`), documented separately
under https://developer.4d.com/docs/category/class-API-reference. This task
concerns **only the classic commands**, not the OOP classes.

Each classic command's documentation page (e.g.
https://developer.4d.com/docs/commands/order-by) contains:
- One or more **signature lines** near the top, e.g.:
  `ORDER BY ( {aTable : Table} {; ...(aField : Field {; order : >, <}) } {; *} )`
  A command can have multiple such lines (overloads).
- A **parameter table** (Parameter / Type / Description columns).
- A **Description** section in prose, which often contains the *real* semantics
  (defaults, side effects, restrictions) that aren't visible in the signature
  or type column alone.
- Sometimes a **History** table showing which 4D releases changed the command's
  behavior.

You are auditing this reference to find commands whose **calling syntax or
parameter semantics** are unusually hard to generate correctly from a
signature alone — the kinds of things that would cause an AI coding assistant
or a naive code generator to produce plausible-looking but wrong 4D code.

You have no prior context about this project beyond this prompt. Do not assume
anything about the language beyond what you read on the actual doc pages.

## Objective

Produce a **full-corpus, exhaustive** classification of all classic commands
against the fixed taxonomy below (Section 2). "Exhaustive" means every command
in the command index must be visited and classified — not a sample, not a
per-theme spot-check, not a subset chosen because it seemed illustrative.

**This constraint exists because a prior attempt at this exact task silently
sampled a subset of commands per documentation theme instead of scanning all
of them, and reported category sizes as if they were corpus-wide counts. That
mistake invalidated the prioritization work done downstream of it. Do not
repeat it.**

If, for any reason (tool limits, time, page-fetch failures), you cannot visit
every command, you must:
1. State the exact number of commands you actually visited out of the total
   found in the command index.
2. State which commands or themes you skipped and why.
3. NOT extrapolate or scale up partial counts into corpus-wide estimates.
   Report only what you actually counted, with the coverage caveat attached.

## Method

1. Fetch https://developer.4d.com/docs/commands/command-index (or theme-by-theme
   index pages under https://developer.4d.com/docs/commands/theme/<ThemeName> if
   that's more reliable for enumeration) and build a complete list of every
   classic command name and its doc URL. Report the total count you found.
2. For each command, fetch its doc page and read the signature line(s),
   parameter table, and description in full — not just the signature line in
   isolation, since several of the categories below are only detectable from
   the prose (e.g. a parameter that triggers a UI dialog when omitted is not
   visible in the signature).
3. Classify the command against **every** category in Section 2 that applies.
   Categories are **not mutually exclusive** — a single command frequently
   matches several (e.g. `ORDER BY` matches both "builder continuation" and
   "special literal symbols"). Tag every match, don't force a single bucket.
4. If a command's classification is genuinely ambiguous (you can see it might
   qualify but the docs are unclear or contradictory), tag it as
   `uncertain: <category>` rather than silently deciding one way. Keep a
   separate list of these.
5. Use the **current/latest** documentation version available (avoid mixing
   version snapshots where avoidable) so counts reflect one coherent state of
   the language rather than a blend of old and new signatures.

## Section 2 — Fixed taxonomy

Use these exact category IDs. Each includes a tight operational definition and
positive/negative examples to reduce classifier drift. A command matches a
category only if it satisfies the operational test, not just the general
theme of the description.

---

**A. `builder_continuation_star`**
Operational test: the command can be called multiple times in sequence to
build up a single logical operation (e.g. a multi-level sort or query), where
a trailing `*` parameter (or equivalent marker) means "more calls are coming,
don't execute yet" and its absence on the final call triggers execution of
the accumulated definition.
Positive example: `ORDER BY` (repeated calls with trailing `*`, final call
with no `*` performs the sort).
Negative example: a command with a single optional trailing flag that doesn't
imply a multi-call sequence at all.

**B. `repeatable_interlaced_pairs`**
Operational test: a single call's signature contains a **repeating group of
2+ parameters** (a tuple), where the group repeats as a unit an arbitrary
number of times in one call — as opposed to category A, which repeats across
*separate calls*.
Positive example: `ORDER BY FORMULA(aTable; formula; order {; formula2; order2; ...})`.
Negative example: a plain variadic list of same-typed single values (not a
multi-member tuple).

**C. `star_operator_dual_signature`**
Operational test: a leading (or otherwise positional) literal `*` parameter,
when present vs. absent, changes the **type or meaning** of a *different*
parameter elsewhere in the same call (most commonly: whether an
"object"/"list"/"field" parameter should be read as a name string vs. a
direct reference/pointer/variable).
Positive example: `SET LIST ITEM PROPERTIES({* ;} list; itemRef; ...)` — presence
of the first `*` changes whether `list` is a name string or a reference number.
Negative example: a `*` that is simply an independent optional flag with a
fixed, single meaning regardless of other parameters.

**D. `property_constant_value_dependency`**
Operational test: a parameter's expected/returned value type is determined by
the *value* of another parameter that is itself drawn from a named constant
set (an enum), not by static typing alone.
Positive example: `OB Get(object; property {; type})` — passing `Is longint`
vs `Is text` in `type` changes what type of value comes back.
Negative example: a parameter whose type is simply fixed regardless of other
arguments.

**E. `optional_dialog_overload`**
Operational test: omitting one or more optional parameters does not fall back
to a documented default value — it causes 4D to **display a blocking
interactive UI dialog/editor** to the end user at runtime, instead of
executing headlessly.
Positive example: `ORDER BY` displays the "Order By" editor if `aField` is
omitted entirely.
Negative example: an omitted optional parameter that silently uses a
documented default value with no UI involved.

**F. `special_literal_symbols`**
Operational test: the command's signature requires passing a **literal
symbol character** (e.g. `>`, `<`, `&`, `|`, `#`, `%`, `@`) as a meaningful
argument value (not as language punctuation), where that symbol is drawn from
a small fixed set with specific meanings.
Positive example: `MULTI SORT ARRAY(...; sort : >, <)`.
Negative example: a parameter that happens to be typed `Text` but doesn't
require one of a small fixed set of literal symbols.

**G. `polymorphic_array_input`**
Operational test: a single array-typed parameter accepts arrays of two (or
more) **different element types** (e.g. Integer array vs. Boolean array),
where which element type you pass **changes the behavior/semantics** of the
whole call, not just superficially converts.
Positive example: a command whose target-selection array can be a Boolean
"include/exclude" mask array or an Integer array of explicit indices, with
different selection semantics for each.
Negative example: an array parameter that accepts multiple element types but
behaves identically regardless (pure type coercion, no semantic change).

**H. `magic_ref_values`**
Operational test: a numeric or reference-typed parameter has one or more
**reserved sentinel values** (a specific number like `0` or `-1`, or a literal
symbol like `*`) carved out of its otherwise-open range, with a distinct
special meaning (e.g. "0 = last item", "* = current item", "-1 = reset").
Positive example: `itemRef` in list-box/hierarchical-list commands, where `0`
means "last item appended" and `*` means "the current item."
Negative example: a parameter where every value in its declared type behaves
uniformly (no carved-out special cases).

**I. `writepro_variadic_or_object_map`**
Operational test: a command (most commonly in the 4D Write Pro / Quick Report
/ similar "attributes" families) offers **two equivalent overloads** for
setting multiple named values: (1) a flat variadic list of alternating
name/value pairs, and (2) a single object parameter whose keys/values
represent the same pairs.
Positive example: `WP SET ATTRIBUTES(targetObj; attribName; attribValue {; ...})`
vs `WP SET ATTRIBUTES(targetObj; attribObj)`.
Negative example: a command that only supports the variadic-pairs form with no
object-map alternative, or vice versa.

**J. `foreign_grammar_string_param`**
Operational test: a `Text`-typed parameter's actual content must conform to
the grammar of an **external, non-4D language or format** (SQL, regular
expressions, XPath, JSON, XML, WSDL/SOAP payloads, JavaScript, URL query
strings, etc.) — a grammar this documentation set and this scan cannot itself
fully specify because it belongs to a different, external spec.
Positive example: `SQL EXECUTE("SELECT * FROM ? WHERE id = ?"; ...)`, `Match regex(...)`.
Negative example: a `Text` parameter with a 4D-native sub-grammar you *can*
fully specify from 4D's own docs (e.g. 4D's own dotted attribute-path syntax
with `[]` array markers) — tag that instead as `foreign_grammar_string_param: no,
4d_native_subgrammar: yes` in your notes, but do not count it in this category.

**K. `external_or_discovered_schema_source`**
Operational test: the valid property/parameter names or types for the command
are not fixed by 4D's documentation at all, but are instead defined by some
**external artifact fetched or discovered separately** (a WSDL/SOAP service
description, the current shape of a runtime data context, a database schema
introspected at runtime, etc.), such that the signature is only fully knowable
by inspecting that external thing, not from this doc page alone.
Positive example: `WEB SERVICE CALL` against a SOAP/WSDL service, where the
actual parameter names/types come from the WSDL document.
Negative example: a command whose object/property names are fixed and fully
enumerable from 4D's own documented constants.

**L. `multi_command_state_machine`**
Operational test: correct use of the command **requires calling it as part of
a specific ordered sequence involving other, different, named commands** (not
repeated calls to the same command as in category A), where the sequence
itself constitutes a small grammar (e.g. open/append/close nesting) that must
be respected across the whole method, not just within one call.
Positive example: the SAX XML parsing command family
(`SAX OPEN XML ELEMENT` / `SAX SET XML ATTRIBUTE` / `SAX CLOSE XML ELEMENT` ...),
which must be called in properly nested order to produce valid XML.
Negative example: two commands that are merely "related" or commonly used
together but have no required ordering or nesting contract.

**M. `opaque_handle_lifecycle`**
Operational test: the command returns (or consumes) an **opaque
reference/handle/ID** (e.g. a DOM element reference, a SAX context, a list
reference) produced by one command and required as input by one or more
*different* named commands later, forming a produce → consume (→ optionally
destroy) relationship across the command family.
Positive example: `DOM Parse XML source` returns a DOM reference consumed by
`DOM Find XML element`, `DOM Get next sibling XML element`, etc.
Negative example: a command that returns a plain, self-describing value (a
Text, a Real) with no other command depending on its specific reference
identity.

**N. `callback_contract`**
Operational test: the command accepts a **method name or method pointer**
that 4D will invoke automatically later, on some future trigger/event, where
the expected parameter signature of that invoked method is documented only in
prose about the *callback's* contract, not in this command's own signature.
Positive example: `ON ERR CALL` — the method it registers has an implicit
expected calling convention for what 4D will pass it when an error occurs.
Negative example: a command that takes a method name and calls it
synchronously and immediately, right there, with parameters visible in the
same call (that's a normal call-by-reference, not a deferred callback).

**O. `pseudo_type_parameter`**
Operational test: a parameter or return type in the signature is not a real,
concrete 4D data type but one of 4D's own catch-all placeholders — e.g.
`Operator`, `Expression`, `any`, a bare `Array` with no element type, generic
`Variant` — used specifically because the real type varies by context or
can't be pinned down.
Positive example: `value : Expression` in `OB SET`, `queryOp : Text, Operator`.
Negative example: a parameter typed as one specific concrete type (`Integer`,
`Text`, `4D.Blob`), even if it happens to accept `Null`.

**P. `silent_coercion_default`**
Operational test: when a parameter's type is left ambiguous or unspecified
(commonly true of parameters passed through to something outside 4D, like a
JavaScript function or external process), the documentation states that 4D
applies a **specific, deterministic fallback type conversion** rather than
erroring or leaving it fully unknown.
Positive example: `WA EXECUTE JAVASCRIPT FUNCTION` — "if the parameter type is
not defined, the text type is used by default."
Negative example: a parameter whose type is simply always required and
checked, with no silent fallback behavior described.

**Q. `deprecated_placeholder_param`**
Operational test: the signature retains one or more parameters that the
documentation explicitly marks as deprecated/non-functional, but that must
still be **explicitly passed a specific dummy literal value** (commonly `0`)
in order to reach a later, still-functional positional parameter.
Positive example: `SET LIST PROPERTIES` — "appearance and icon parameters are
deprecated, you must pass 0 for them."
Negative example: a deprecated parameter that can simply be omitted entirely
with no positional consequence.

**R. `cross_parameter_joint_constraint`**
Operational test: the validity or effective value of one parameter depends
jointly on the value of a **sibling parameter that is not part of a repeating
group** (contrast with category B) — e.g. "if either of this pair is null,
both fall back to a shared default," or "parameter B's effect only applies
when parameter A is true."
Positive example: `GRAPH SETTINGS`'s `xmin`/`xmax` pair, where either being
null causes both to fall back to defaults.
Negative example: parameters that are independently optional with independent
defaults and no cross-dependency.

**S. `statically_indistinguishable_overloads`**
Operational test: two or more overloads of the same command declare
**identical parameter types**, such that no static signature check can tell
them apart — disambiguation depends on runtime information not visible in the
call itself (e.g. what a `Pointer` argument actually points to).
Positive example: `Table(tablePtr : Pointer) : Integer` vs.
`Table(fieldPtr : Pointer) : Integer` — same declared parameter type, disjoint
real meanings.
Negative example: overloads that differ in declared parameter type or count,
even if superficially similar in purpose.

---

## Output format

Produce a single report with these sections:

### 1. Coverage statement
Total commands found in the command index. Total commands actually visited
and classified. If less than 100%, explain exactly why and what was skipped.

### 2. Per-category results
For **each** of categories A–S, report:
- The category ID and a one-line restatement of its operational test.
- **Total matching commands, out of the total visited** (not out of a sample).
- The **full list of matching command names** (not just "+N more" — list all
  of them; if a category is very large, an appendix table is fine, but the
  main body must state the true total).
- 2–3 representative examples with a one-line note on *why* each matches the
  operational test specifically (not just "it's tricky").

### 3. Uncertain/borderline list
Every command you tagged `uncertain` for any category, with a one-line note
on what made the classification unclear.

### 4. Multi-label overlap summary
A count of how many commands matched 2+ categories simultaneously, and the
most common category *co-occurrence pairs* (e.g. "how many commands are both
A and F").

### 5. Anything uncatalogued
If you encounter a command with a syntax quirk that doesn't fit any of
categories A–S but seems similarly likely to trip up a code generator,
describe it and propose a new category ID/definition/test for it, with the
specific command(s) that prompted the addition. Do not force-fit it into an
existing category if it's genuinely a different mechanism.

## Constraints

- Do not rely on memory/training data for any command's actual syntax — fetch
  and read the live documentation page for every command you classify.
- Do not average, extrapolate, or round category totals from partial
  coverage. Report exact counts over exactly what you visited, with the
  coverage caveat from Section 1 attached to every number.
- Prefer the canonical rendered signature line(s) and parameter table over
  auto-generated meta/description tags on the page, which are sometimes
  stale, truncated, or garbled relative to the actual rendered content.
- A command may and often will match multiple categories — do not force a
  single-label classification.

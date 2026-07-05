# Approach

## Domain and subset

Domain A, scoped to Python's **typing system** specifically (as opposed to
concurrency or general syntax). I picked typing for three reasons:

1. It's the single most active, most argued-about area of PEP development in
   the last decade. There's a real, recurring problem here: someone proposing
   a typing feature today genuinely has no easy way to check whether their
   idea already came up and lost, and why.
2. Typing PEPs share a strong, consistent structure (Abstract, Rationale,
   Rejected Ideas / Alternatives, Backwards Compatibility) which makes it
   possible to build a real hand-written parser instead of a fragile,
   general-purpose one. Consistency in source structure was a first-class
   factor in scoping, since the assignment forbids leaning on a library to
   do this for me.
3. Typing PEPs cross-reference each other constantly — TypeGuard leads to
   TypeIs, TypedDict leads to Required/NotRequired and read-only fields,
   ParamSpec leads to Concatenate — so the "what came before" relationship is
   genuinely rich, not artificially constructed for the exercise.

I fetched 29 PEPs directly from `python/peps` on GitHub (PEP 482 through PEP
746), covering generics, protocols, narrowing, literal types, TypedDict,
ParamSpec, variadic generics, Self, deprecation marking, and typing
governance. This is a deliberately focused slice, not the ~300+ PEP corpus.

## Entities and relationships

I designed the schema before writing any parsing code, based on what a
developer actually needs when they ask "has this been tried before":

- **PEP** — the proposal: id, title, status, created date, Python version,
  authors, curated concepts it touches, count of extracted arguments.
- **Person** — authors and BDFL-delegates, so provenance (who argued for or
  against what) is traceable, not just "some PEP said X."
- **Concept** — a curated, closed vocabulary of 21 typing concepts (generics,
  protocols/structural typing, type narrowing, literal types, TypedDict,
  ParamSpec, variadic generics, Self type, final qualifier, type aliases,
  dataclass transforms, override decorator, deprecation marking, kwargs
  typing, runtime type info, governance, annotated metadata, literal string
  type, and a few more). Each concept is defined by a hand-picked list of
  surface-form triggers (e.g. `type_narrowing` triggers on "TypeGuard",
  "TypeIs", "narrows the type", "isinstance check", "flow-sensitive"). This
  is the part of the assignment's hard constraint that mattered most: rather
  than pulling out "topics" automatically with a library, I read the PEPs and
  decided what the meaningful concept boundaries are, the same way a
  developer who's spent time in this space would recognize them.
- **Argument** — an individual rationale/rejected-idea/objection point,
  extracted from Rationale, Rejected Ideas, Alternatives, Objections, and
  Backwards Compatibility sections. Extraction splits each section into
  blank-line-separated paragraphs, filters out anything that reads like a
  code block (low alphabetic-character ratio), and keeps paragraphs over 40
  characters that either sit in a section with "reject" in its title or
  contain stance language ("instead," "however," "considered," "chose not
  to," "objection," "drawback," etc.). This produced 425 argument nodes
  across 29 PEPs — real, individually addressable pieces of past reasoning,
  not paragraph dumps.

Relationships: `AUTHORED_BY`, `DELEGATED_TO`, `REFERENCES` (from `:pep:`nnn``
cross-references in body text), `SUPERSEDES` / `SUPERSEDED_BY` (from the
`Replaces:` / `Superseded-By:` header fields, with the inverse derived
automatically when only one direction is explicit), `DISCUSSES_CONCEPT`
(PEP to Concept, via the same curated trigger match used for new inputs),
`HAS_ARGUMENT` (PEP to Argument), and `ARGUMENT_ABOUT` (Argument to Concept,
so an individual objection is traceable back to what it was actually about,
not just which PEP it came from).

## How the knowledge representation was built

`src/build_knowledge.py` does everything with the standard library: `re` for
pattern matching, manual RST section splitting (a title line immediately
followed by a line of `=` characters, which is how PEP source files are
structured), and a hand-rolled header-field parser for the `PEP:`, `Title:`,
`Author:`, `Status:`, `Replaces:` block at the top of each file. No NLP
library, no NER model, no automatic relationship extraction — every rule in
that file is one I wrote by reading the actual PEP source and deciding what
pattern to look for.

Tradeoffs I made deliberately:

- **Curated concepts over automatic topic extraction.** This is less
  flexible (a genuinely novel concept won't be recognized until I add it to
  the list) but it's honest, inspectable, and exactly what the assignment
  asks for: the schema is mine, not a library's.
- **Paragraph-level arguments, not sentence-level.** Individual sentences
  extracted alone lose the "because" that makes an objection meaningful.
  Whole paragraphs stay coherent at some cost to precision (a few extracted
  "arguments" are really just supporting detail rather than a standalone
  objection).
- **No embeddings, no vector search.** Everything is exact keyword/trigger
  matching plus graph traversal. This means the system's reasoning is fully
  explainable — every result in a report can be traced back to a specific
  trigger phrase and a specific PEP section — at the cost of missing
  paraphrases that don't share vocabulary with the curated trigger list.
  I mitigated this a little with a fallback word-overlap match against
  concept labels themselves, but it's intentionally a shallow fallback, not
  a second matching system. That fallback needed a second pass: an early
  version matched on any single overlapping word, which meant a generic word
  like "type" or "string" alone (present in several concept labels, e.g.
  `type_narrowing`, `string_literal_type`) triggered a false precedent match
  for inputs that had nothing to do with that concept. Fixed by excluding
  generic stopwords from the overlap count and requiring at least two
  meaningful overlapping words before the fallback fires, so an off-topic or
  vague input now correctly reports no match instead of a misleading one.

## How the system handles a new input

`src/reason.py` is the testable interface. Given free text describing a
feature idea:

1. It runs the same curated concept-matching used at ingestion time against
   the new text (identical trigger list, so ingestion and reasoning share one
   vocabulary rather than drifting apart).
2. It walks `DISCUSSES_CONCEPT` in reverse to find every PEP that touches any
   matched concept, and ranks those PEPs by how many matched concepts they
   share (a simple, transparent precedent-strength score).
3. It walks `ARGUMENT_ABOUT` in reverse to pull actual extracted Argument
   nodes tied to the matched concepts, so "arguments you'll likely face" is
   never invented text, it's a real paragraph from a real PEP's Rationale or
   Rejected Ideas section.
4. It produces one recommendation sentence naming the strongest-precedent
   PEP and pointing at exactly which section to read, based on the overlap
   score.

This satisfies "operating on new inputs": the report for an idea never
literally appeared in the 29 ingested PEPs, but every fact in the report
traces to something that did.

## What I'd build next

- **Cross-concept argument chains.** Right now arguments are tied to a
  single PEP's stance. The more valuable next step is linking an argument in
  PEP-647 to the counter-argument that later appeared in PEP-742, so the
  system can show not just "this was objected to" but "this was objected to,
  and here's how a later PEP resolved that exact objection."
- **Confidence-scored concept matching** instead of boolean trigger hits, so
  overlapping concepts (e.g. `type_narrowing` vs `protocols_structural_typing`
  co-occurring in PEP-647) are weighted rather than counted equally.
- **Expanding past typing** into concurrency or syntax PEPs using the same
  schema, to test whether the Concept/Argument model generalizes or needs
  per-domain rework.
- **A small web UI** over `reason.py` so a developer can paste an idea and
  get the report without touching the CLI, since the underlying logic is
  already fully separated from presentation.

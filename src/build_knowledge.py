"""
Custom knowledge graph builder for Python typing PEPs.

No entity/relationship-extraction libraries are used. All parsing is done with
hand-written regex and heuristics tuned to the actual structure of PEP RST files
(header block, ==== underlined sections, :pep:`nnn` cross-reference role).

Entities produced:
  - PEP            (the proposal itself)
  - Person         (authors / BDFL-Delegates)
  - Concept        (typing concepts, curated vocabulary + detection)
  - Argument       (a single rejected-idea / objection / rationale point, extracted
                     from "Rejected Ideas", "Rationale", "Alternatives" sections)

Relationships produced:
  - AUTHORED_BY        PEP -> Person
  - DELEGATED_TO        PEP -> Person (BDFL-Delegate)
  - REFERENCES          PEP -> PEP   (via :pep:`nnn` mentions outside the header)
  - SUPERSEDES          PEP -> PEP   (explicit "Supersedes:" header field)
  - SUPERSEDED_BY       PEP -> PEP   (derived inverse, or explicit "Superseded-By:")
  - DISCUSSES_CONCEPT   PEP -> Concept (curated keyword match against PEP body)
  - HAS_ARGUMENT        PEP -> Argument (rationale / rejected-idea / alternative points)
  - ARGUMENT_ABOUT      Argument -> Concept (concept the argument concerns)
"""
import re
import json
import os
from collections import defaultdict

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "processed")

# -----------------------------------------------------------------------
# Curated concept vocabulary.
# This is the schema decision that matters most: rather than pulling keywords
# out of the text automatically (which the assignment explicitly forbids),
# each concept is defined by hand as a set of surface-form triggers that a
# domain expert (someone who has read these PEPs) would recognize as
# referring to that concept. This is deliberately a closed, curated list,
# not an open-ended NER vocabulary.
# -----------------------------------------------------------------------
CONCEPTS = {
    "generics": ["generic type", "generics", "Generic[", "type parameter", "TypeVar"],
    "variadic_generics": ["variadic generic", "TypeVarTuple", "Unpack[", "variable number of type parameters"],
    "protocols_structural_typing": ["protocol", "structural subtyping", "duck typing", "nominal subtyping"],
    "type_narrowing": ["type narrowing", "TypeGuard", "TypeIs", "narrows the type", "narrowing", "narrow the", "isinstance check", "flow-sensitive"],
    "literal_types": ["Literal[", "literal type", "literal values"],
    "typed_dict": ["TypedDict", "typed dictionary", "fixed set of keys"],
    "annotations_syntax": ["variable annotation", "function annotation", "annotation syntax", "__annotations__"],
    "postponed_evaluation": ["postponed evaluation", "stringized annotation", "lazy evaluation of annotations", "from __future__ import annotations"],
    "union_syntax": ["union type", "X | Y", "Optional[", "pipe operator", "PEP 604"],
    "callable_specs": ["ParamSpec", "parameter specification", "Callable[", "decorator that changes"],
    "self_type": ["Self type", "typing.Self", "return type of a method that returns an instance"],
    "final_qualifier": ["final qualifier", "Final[", "prevent reassignment", "prevent subclassing"],
    "type_aliases": ["type alias", "TypeAlias", "explicit alias"],
    "dataclass_transforms": ["dataclass_transform", "data class transform", "attrs-like", "synthesized __init__"],
    "overrides": ["override decorator", "@override", "overriding a method"],
    "deprecation": ["deprecated", "@deprecated", "deprecation warning"],
    "kwargs_typing": ["**kwargs", "unpack kwargs", "keyword arguments typing"],
    "runtime_type_info": ["distributing type information", "py.typed", "stub file", "inline type information"],
    "governance": ["governance", "steering council", "typing council", "decision process"],
    "annotated_metadata": ["Annotated[", "annotated metadata", "runtime metadata"],
    "string_literal_type": ["LiteralString", "literal string type", "arbitrary literal string"],
}

FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z\- ]+):\s*(.*)$")
PEP_ROLE_RE = re.compile(r":pep:`(\d+)`")
SECTION_HEADER_RE = re.compile(r"^=+$")

ARGUMENT_SECTION_MARKERS = ("reject", "rationale", "alternative", "objection",
                           "design consideration", "backwards compat")


def is_argument_section(title):
    low = title.lower()
    return any(marker in low for marker in ARGUMENT_SECTION_MARKERS)


def parse_header(lines):
    """Parse the RST field-list header block (PEP:, Title:, Author:, ...)."""
    fields = {}
    for line in lines:
        if line.strip() == "":
            break
        m = FIELD_RE.match(line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            fields.setdefault(key, val)
    return fields


def split_sections(lines):
    """Return list of (title, body_lines) using the '<title>\\n====' RST pattern."""
    sections = []
    current_title = "Header"
    current_body = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if i + 1 < n and SECTION_HEADER_RE.match(lines[i + 1].strip()) and line.strip():
            # flush previous
            sections.append((current_title, current_body))
            current_title = line.strip()
            current_body = []
            i += 2
            continue
        current_body.append(line)
        i += 1
    sections.append((current_title, current_body))
    return sections


def extract_authors(field_value):
    """'Guido van Rossum <guido@python.org>, Jukka Lehtosalo <...>' -> list of names"""
    people = []
    for chunk in field_value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name = re.sub(r"<.*?>", "", chunk).strip()
        if name:
            people.append(name)
    return people


def extract_arguments(pep_id, section_title, body_lines):
    """
    Split an argument-bearing section into individual argument points.
    Heuristic: a new argument point starts at a bullet ('-', '*') at column 0,
    or at a bolded/italicized lead-in sentence, or a sub-heading.
    Fallback: split the section into paragraphs (blank-line separated) and
    keep paragraphs that look like a stance ("would", "should", "rejected",
    "instead", "because", "however", "chose not to", "considered").
    """
    text = "\n".join(body_lines)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    stance_markers = ("rejected", "considered", "instead", "however", "would",
                      "should", "chose not", "decided", "alternative", "objection",
                      "argument", "concern", "drawback", "downside", "prefer")
    arguments = []
    idx = 0
    for p in paragraphs:
        clean = re.sub(r"\s+", " ", p).strip()
        clean = re.sub(r"^[-*]\s*", "", clean)
        if len(clean) < 40:
            continue
        alpha_chars = sum(1 for ch in clean if ch.isalpha())
        if alpha_chars / max(1, len(clean)) < 0.55:
            continue  # looks like a code block, not prose argument
        lower = clean.lower()
        if any(m in lower for m in stance_markers) or "reject" in section_title.lower():
            idx += 1
            arguments.append({
                "id": f"ARG-{pep_id}-{section_title[:3].upper()}-{idx}",
                "pep": pep_id,
                "section": section_title,
                "text": clean[:600],
            })
    return arguments


def match_concepts(pep_id, full_text):
    matched = []
    for concept, triggers in CONCEPTS.items():
        for trig in triggers:
            if trig.lower() in full_text.lower():
                matched.append(concept)
                break
    return matched


def build():
    peps = {}
    people = {}
    arguments = []
    edges = defaultdict(list)

    files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".rst"))
    for fname in files:
        path = os.path.join(RAW_DIR, fname)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()

        header_end = 0
        for i, l in enumerate(lines):
            if l.strip() == "":
                header_end = i
                break
        header_fields = parse_header(lines[:header_end])
        pep_id = header_fields.get("PEP", fname.replace("pep-", "").replace(".rst", "").lstrip("0"))
        pep_id = f"PEP-{int(pep_id):d}" if pep_id.isdigit() else pep_id

        full_text = "\n".join(lines)

        sections = split_sections(lines)

        pep_arguments = []
        for title, body in sections:
            if is_argument_section(title):
                pep_arguments.extend(extract_arguments(pep_id, title, body))

        concepts_found = match_concepts(pep_id, full_text)

        authors = extract_authors(header_fields.get("Author", ""))
        for a in authors:
            people.setdefault(a, {"id": a, "type": "Person", "role": "author", "peps": []})
            people[a]["peps"].append(pep_id)
            edges["AUTHORED_BY"].append({"from": pep_id, "to": a})

        delegate = header_fields.get("BDFL-Delegate") or header_fields.get("Typing-Council-Delegate")
        if delegate:
            dname = re.sub(r"<.*?>", "", delegate).strip()
            if dname:
                people.setdefault(dname, {"id": dname, "type": "Person", "role": "delegate", "peps": []})
                people[dname]["peps"].append(pep_id)
                edges["DELEGATED_TO"].append({"from": pep_id, "to": dname})

        referenced = set()
        body_only_text = "\n".join(lines[header_end:])
        for m in PEP_ROLE_RE.finditer(body_only_text):
            ref = int(m.group(1))
            if f"PEP-{ref}" != pep_id:
                referenced.add(f"PEP-{ref}")
        for ref in sorted(referenced):
            edges["REFERENCES"].append({"from": pep_id, "to": ref})

        supersedes_field = header_fields.get("Replaces")
        if supersedes_field:
            for m in re.finditer(r"\d+", supersedes_field):
                edges["SUPERSEDES"].append({"from": pep_id, "to": f"PEP-{int(m.group(0))}"})

        superseded_by_field = header_fields.get("Superseded-By")
        if superseded_by_field:
            for m in re.finditer(r"\d+", superseded_by_field):
                edges["SUPERSEDED_BY"].append({"from": pep_id, "to": f"PEP-{int(m.group(0))}"})

        for c in concepts_found:
            edges["DISCUSSES_CONCEPT"].append({"from": pep_id, "to": c})

        for arg in pep_arguments:
            arg_concepts = match_concepts(pep_id, arg["text"])
            if not arg_concepts:
                arg_concepts = concepts_found[:1]
            arg["concepts"] = arg_concepts
            arguments.append(arg)
            edges["HAS_ARGUMENT"].append({"from": pep_id, "to": arg["id"]})
            for c in arg_concepts:
                edges["ARGUMENT_ABOUT"].append({"from": arg["id"], "to": c})

        peps[pep_id] = {
            "id": pep_id,
            "type": "PEP",
            "title": header_fields.get("Title", ""),
            "status": header_fields.get("Status", ""),
            "topic": header_fields.get("Topic", ""),
            "created": header_fields.get("Created", ""),
            "python_version": header_fields.get("Python-Version", ""),
            "authors": authors,
            "concepts": sorted(set(concepts_found)),
            "num_arguments_extracted": len(pep_arguments),
        }

    # derive SUPERSEDED_BY from SUPERSEDES if not explicit
    explicit_superseded_by = {(e["from"], e["to"]) for e in edges["SUPERSEDED_BY"]}
    for e in edges["SUPERSEDES"]:
        pair = (e["to"], e["from"])
        if pair not in explicit_superseded_by:
            edges["SUPERSEDED_BY"].append({"from": e["to"], "to": e["from"]})

    concept_nodes = {c: {"id": c, "type": "Concept", "label": c.replace("_", " ")} for c in CONCEPTS}

    knowledge_state = {
        "meta": {
            "domain": "Python typing system evolution (PEPs)",
            "num_peps": len(peps),
            "num_people": len(people),
            "num_concepts": len(concept_nodes),
            "num_arguments": len(arguments),
        },
        "entities": {
            "peps": peps,
            "people": people,
            "concepts": concept_nodes,
            "arguments": {a["id"]: a for a in arguments},
        },
        "relationships": edges,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "knowledge_state.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(knowledge_state, f, indent=2)

    print(f"Built knowledge state: {len(peps)} PEPs, {len(people)} people, "
          f"{len(concept_nodes)} concepts, {len(arguments)} arguments")
    print(f"Edge counts: " + ", ".join(f"{k}={len(v)}" for k, v in edges.items()))
    print(f"Written to {out_path}")


if __name__ == "__main__":
    build()

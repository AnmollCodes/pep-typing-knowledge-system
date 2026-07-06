"""
Reasoning engine for the Python-typing-evolution knowledge base.

Takes a NEW input -- a free-text description of a language-feature idea a
developer is considering proposing -- and produces a structured report:

  1. Which existing concepts in the knowledge base this idea touches
  2. Which PEPs already dealt with those concepts (precedent)
  3. What arguments / objections were raised for those concepts in the past
     (grounded in the actual extracted Argument nodes, not invented)
  4. Related PEPs the person should read, ranked by concept overlap
  5. A same-vocabulary "objection you should prepare for" summary

This is NOT a similarity search over embeddings and NOT a call out to an LLM.
It walks the explicit graph built in build_knowledge.py: concept matching uses
the same curated trigger list, then graph traversal (PEP -> Concept -> PEP,
PEP -> Argument -> Concept) surfaces grounded, explainable results.
"""
import json
import os
import re
import sys
from collections import defaultdict, Counter

BASE = os.path.dirname(__file__)
STATE_PATH = os.path.join(BASE, "..", "data", "processed", "knowledge_state.json")

# Same curated concept vocabulary used at ingestion time. Reasoning must use
# the identical schema as ingestion, or "new input" matching would be
# inconsistent with what's stored.
from build_knowledge import CONCEPTS  # noqa: E402


def load_state():
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def match_concepts_in_text(text):
    matched = []
    low = text.lower()
    for concept, triggers in CONCEPTS.items():
        for trig in triggers:
            if trig.lower() in low:
                matched.append(concept)
                break
    return matched


def reason_over_new_input(new_text, state, top_k=5):
    matched_concepts = match_concepts_in_text(new_text)

    if not matched_concepts:
        # Fallback: fuzzy word-overlap against concept labels so the system
        # still returns something useful for phrasing that doesn't hit an
        # exact trigger (e.g. "returning the enclosing class type" for Self).
        # Generic words that appear in many concept labels (type, types) are
        # excluded from the overlap count, since matching on those alone
        # produces false precedent (e.g. "string method" incorrectly hitting
        # "string_literal_type" through the word "string" only). Require at
        # least 2 meaningful overlapping words before accepting a fallback
        # match, so a vague or off-topic input correctly matches nothing.
        STOPWORDS = {"type", "types"}
        words = set(re.findall(r"[a-z]+", new_text.lower())) - STOPWORDS
        scored = []
        for concept in CONCEPTS:
            label_words = set(concept.split("_")) - STOPWORDS
            overlap = len(words & label_words)
            if overlap >= 2:
                scored.append((overlap, concept))
        scored.sort(reverse=True)
        matched_concepts = [c for _, c in scored[:3]]

    peps = state["entities"]["peps"]
    arguments = state["entities"]["arguments"]
    edges = state["relationships"]

    concept_to_peps = defaultdict(set)
    for e in edges["DISCUSSES_CONCEPT"]:
        concept_to_peps[e["to"]].add(e["from"])

    concept_to_args = defaultdict(list)
    for e in edges["ARGUMENT_ABOUT"]:
        concept_to_args[e["to"]].append(e["from"])

    # Rank related PEPs by number of matched concepts they discuss (precedent strength).
    # Tie-break by how many extracted arguments that PEP has about the matched
    # concepts specifically. A PEP that only mentions a concept in passing
    # (one DISCUSSES_CONCEPT edge, zero arguments about it) should not
    # outrank the PEP that actually built and defended the concept. Counter
    # alone ties on raw concept-overlap count and breaks ties by insertion
    # order, which surfaced exactly this problem: a TypedDict question
    # ranked PEP-593 (which mentions TypedDict once, in passing) above
    # PEP-589 (the PEP that defines TypedDict and argues about it at length).
    pep_scores = Counter()
    pep_arg_density = Counter()
    for c in matched_concepts:
        for pep_id in concept_to_peps.get(c, []):
            pep_scores[pep_id] += 1
        for arg_id in concept_to_args.get(c, []):
            pep_arg_density[arguments[arg_id]["pep"]] += 1

    ranked_pep_ids = sorted(
        pep_scores.keys(),
        key=lambda p: (pep_scores[p], pep_arg_density.get(p, 0)),
        reverse=True,
    )
    ranked_peps = [(p, pep_scores[p]) for p in ranked_pep_ids[:top_k]]

    related_arguments = []
    seen_arg_ids = set()
    for c in matched_concepts:
        for arg_id in concept_to_args.get(c, []):
            if arg_id in seen_arg_ids:
                continue
            seen_arg_ids.add(arg_id)
            arg = arguments[arg_id]
            related_arguments.append({
                "concept": c,
                "from_pep": arg["pep"],
                "section": arg["section"],
                "point": arg["text"],
            })

    report = {
        "input": new_text,
        "matched_concepts": matched_concepts,
        "precedent_peps": [
            {
                "pep": pep_id,
                "title": peps[pep_id]["title"],
                "status": peps[pep_id]["status"],
                "python_version": peps[pep_id]["python_version"],
                "concept_overlap_score": score,
                "shared_concepts": sorted(set(peps[pep_id]["concepts"]) & set(matched_concepts)),
            }
            for pep_id, score in ranked_peps
        ],
        "arguments_you_will_likely_face": related_arguments[:8],
        "recommendation": build_recommendation(matched_concepts, ranked_peps, peps),
    }
    return report


def build_recommendation(matched_concepts, ranked_peps, peps):
    if not matched_concepts:
        return ("No matching prior concept found in the knowledge base. This may be a "
                "genuinely novel direction, or it may use vocabulary the knowledge base "
                "doesn't recognize yet -- worth widening the concept list.")

    if not ranked_peps:
        return (f"This touches known concepts ({', '.join(matched_concepts)}) but no PEP "
                "in this dataset discusses them directly. Precedent may exist outside "
                "the ingested subset.")

    top_pep_id, top_score = ranked_peps[0]
    top_pep = peps[top_pep_id]
    if top_score >= len(matched_concepts):
        strength = "very strong"
    elif top_score >= max(1, len(matched_concepts) // 2):
        strength = "moderate"
    else:
        strength = "weak"

    return (f"{strength.capitalize()} precedent overlap with {top_pep_id} "
            f"('{top_pep['title']}', status: {top_pep['status']}). "
            f"Read that PEP's Rationale/Rejected-Ideas section before drafting a proposal, "
            f"since {top_score} of {len(matched_concepts)} matched concept(s) were already "
            f"litigated there.")


def print_report(report):
    print("=" * 70)
    print("NEW INPUT")
    print("-" * 70)
    print(report["input"].strip())
    print()
    print("MATCHED CONCEPTS:", ", ".join(report["matched_concepts"]) or "(none)")
    print()
    print("PRECEDENT (existing PEPs, ranked by concept overlap):")
    for p in report["precedent_peps"]:
        print(f"  - {p['pep']}: {p['title']}  [status={p['status']}, "
              f"py={p['python_version']}, overlap={p['concept_overlap_score']}]")
        print(f"      shared concepts: {', '.join(p['shared_concepts'])}")
    print()
    print("ARGUMENTS YOU WILL LIKELY FACE (grounded in actual PEP text):")
    for a in report["arguments_you_will_likely_face"]:
        print(f"  - [{a['from_pep']} / {a['section']}] ({a['concept']})")
        print(f"      {a['point'][:220]}")
    print()
    print("RECOMMENDATION:")
    print(f"  {report['recommendation']}")
    print("=" * 70)


if __name__ == "__main__":
    state = load_state()
    if len(sys.argv) > 1:
        new_text = " ".join(sys.argv[1:])
    else:
        new_text = sys.stdin.read()
    report = reason_over_new_input(new_text, state)
    print_report(report)
    out_path = os.path.join(BASE, "..", "output", "last_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

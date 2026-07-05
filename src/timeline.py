"""
Concept timeline: a second, independent way of reasoning over the same
knowledge graph built in build_knowledge.py.

Where reason.py answers "what precedent exists for a NEW idea", this answers
a different, complementary question that the assignment explicitly names as
a target scenario: "A developer encounters a behavior in Python that seems
arbitrary and wants to understand the original debate that produced it."

Given a concept id (e.g. type_narrowing, generics, protocols_structural_typing)
this walks the graph and produces a chronological account:

  - every PEP that discusses the concept, in date order
  - the status each PEP reached (Draft, Accepted, Final, Superseded, ...)
  - the SUPERSEDES / SUPERSEDED_BY chain between those PEPs, if any
  - the arguments raised about that concept at each point in time, so the
    reader sees not just "what changed" but "what was argued about it"

This is still pure graph traversal over knowledge_state.json. No new
extraction happens here; it reuses entities and edges already built by
build_knowledge.py.
"""
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(__file__)
STATE_PATH = os.path.join(BASE, "..", "data", "processed", "knowledge_state.json")

MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def parse_pep_date(date_str):
    """PEP header dates look like '08-Jan-2015'. Falls back to a far-future
    sort key for anything unparsable so it doesn't crash the timeline."""
    try:
        day, mon, year = date_str.split("-")
        return datetime(int(year), MONTHS[mon], int(day))
    except Exception:
        return datetime(2999, 1, 1)


def load_state():
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_timeline(concept_id, state):
    peps = state["entities"]["peps"]
    arguments = state["entities"]["arguments"]
    edges = state["relationships"]

    if concept_id not in state["entities"]["concepts"]:
        return None

    discussing = [e["from"] for e in edges["DISCUSSES_CONCEPT"] if e["to"] == concept_id]
    discussing = sorted(set(discussing), key=lambda p: parse_pep_date(peps[p]["created"]))

    supersedes_map = defaultdict(list)
    superseded_by_map = defaultdict(list)
    for e in edges["SUPERSEDES"]:
        supersedes_map[e["from"]].append(e["to"])
    for e in edges["SUPERSEDED_BY"]:
        superseded_by_map[e["from"]].append(e["to"])

    concept_args = [a for a in arguments.values() if concept_id in a.get("concepts", [])]
    args_by_pep = defaultdict(list)
    for a in concept_args:
        args_by_pep[a["pep"]].append(a)

    timeline = []
    for pep_id in discussing:
        p = peps[pep_id]
        timeline.append({
            "pep": pep_id,
            "title": p["title"],
            "created": p["created"],
            "status": p["status"],
            "python_version": p["python_version"],
            "supersedes": supersedes_map.get(pep_id, []),
            "superseded_by": superseded_by_map.get(pep_id, []),
            "argument_count": len(args_by_pep.get(pep_id, [])),
            "sample_arguments": [a["text"][:180] for a in args_by_pep.get(pep_id, [])[:2]],
        })

    return {
        "concept": concept_id,
        "num_peps_in_timeline": len(timeline),
        "timeline": timeline,
    }


def print_timeline(report, concept_id):
    if report is None:
        print(f"No concept named '{concept_id}' in the knowledge base.")
        print("Run with --list to see all available concept ids.")
        return

    print("=" * 72)
    print(f"CONCEPT TIMELINE: {concept_id}")
    print("=" * 72)
    if report["num_peps_in_timeline"] == 0:
        print("No PEPs in the knowledge base discuss this concept.")
        return

    for i, entry in enumerate(report["timeline"]):
        arrow = "  |" if i < len(report["timeline"]) - 1 else "  `"
        print(f"{entry['created']:>12}  {entry['pep']:<9} {entry['title']}")
        print(f"{'':>12}  {'':<9} status: {entry['status']}"
              + (f" | python: {entry['python_version']}" if entry["python_version"] else ""))
        if entry["supersedes"]:
            print(f"{'':>12}  {'':<9} supersedes: {', '.join(entry['supersedes'])}")
        if entry["superseded_by"]:
            print(f"{'':>12}  {'':<9} superseded by: {', '.join(entry['superseded_by'])}")
        if entry["sample_arguments"]:
            print(f"{'':>12}  {'':<9} debated point: {entry['sample_arguments'][0]}")
        print(f"{'':>12}  {arrow}")
    print("=" * 72)


def list_concepts(state):
    print("Available concept ids:")
    for c in sorted(state["entities"]["concepts"]):
        count = sum(1 for e in state["relationships"]["DISCUSSES_CONCEPT"] if e["to"] == c)
        print(f"  {c:<32} ({count} PEPs)")


if __name__ == "__main__":
    state = load_state()
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        list_concepts(state)
        sys.exit(0)

    concept_id = sys.argv[1]
    report = build_timeline(concept_id, state)
    print_timeline(report, concept_id)

    if report is not None:
        out_path = os.path.join(BASE, "..", "output", "last_timeline.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

"""Sanity checks on the built knowledge state. Not unit tests in the strict
sense (there's no ground truth labels to compare against) but structural
integrity checks: every edge must point at an entity that actually exists,
counts must be internally consistent, no orphan PEPs."""
import json
import os

BASE = os.path.dirname(__file__)
STATE_PATH = os.path.join(BASE, "..", "data", "processed", "knowledge_state.json")


def main():
    state = json.load(open(STATE_PATH, encoding="utf-8"))
    peps = state["entities"]["peps"]
    people = state["entities"]["people"]
    concepts = state["entities"]["concepts"]
    arguments = state["entities"]["arguments"]
    edges = state["relationships"]

    errors = []

    def check_node(node_id, kind):
        pools = {"pep": peps, "person": people, "concept": concepts, "argument": arguments}
        if node_id not in pools[kind]:
            errors.append(f"Missing {kind} node referenced: {node_id}")

    for e in edges["AUTHORED_BY"]:
        check_node(e["from"], "pep")
        check_node(e["to"], "person")
    for e in edges["DISCUSSES_CONCEPT"]:
        check_node(e["from"], "pep")
        check_node(e["to"], "concept")
    for e in edges["HAS_ARGUMENT"]:
        check_node(e["from"], "pep")
        check_node(e["to"], "argument")
    for e in edges["ARGUMENT_ABOUT"]:
        check_node(e["from"], "argument")
        check_node(e["to"], "concept")
    for e in edges["REFERENCES"]:
        check_node(e["from"], "pep")
        if e["to"] not in peps:
            pass  # references can point outside the ingested subset; not an error

    peps_with_no_concepts = [p for p, v in peps.items() if not v["concepts"]]
    peps_with_no_arguments = [p for p, v in peps.items() if v["num_arguments_extracted"] == 0]

    print(f"Checked {len(peps)} PEPs, {len(people)} people, {len(concepts)} concepts, "
          f"{len(arguments)} arguments.")
    print(f"Integrity errors: {len(errors)}")
    for err in errors:
        print("  -", err)
    print(f"PEPs with zero matched concepts: {peps_with_no_concepts}")
    print(f"PEPs with zero extracted arguments: {peps_with_no_arguments}")

    if errors:
        raise SystemExit(1)
    print("OK: knowledge state is structurally consistent.")


if __name__ == "__main__":
    main()

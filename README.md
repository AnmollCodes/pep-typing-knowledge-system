# Python Typing Evolution Knowledge System

A knowledge system that reads the real history of Python's typing system, from PEP 482 through PEP 746, and turns it into a structured graph of proposals, people, concepts, and arguments. When a developer describes a new feature idea, the system reasons over that graph and returns grounded precedent: which past proposals are closest, what objections were already raised, and what to read before writing a new PEP.

Built for the Calyb AI Engineering Intern Assignment, Domain A (Language Evolution).

## Table of contents

1. Overview
2. System architecture
3. Project structure
4. Requirements and installation
5. Building the knowledge state
6. Using the reasoning interface
7. Configuration
8. Scope and limitations
9. Further reading

## 1. Overview

Python's typing system did not appear all at once. It was built PEP by PEP over roughly a decade, and every design choice, generics, protocols, type narrowing, TypedDict, ParamSpec, came with a debate that is now buried in plain text files. A developer who wants to propose something new has no easy way to check whether the idea already came up, what happened to it, and why.

This project treats that history as a knowledge problem rather than a search problem. It does three things:

- Transforms 29 real PEP documents into an explicit knowledge representation with named entities and typed relationships between them.
- Reasons over that representation when given a new input, a feature idea that was never in the original dataset.
- Produces a structured, grounded report a developer can act on directly: precedent PEPs, real past objections, and a recommendation.

No entity or relationship extraction library is used anywhere in this project. Every rule that decides what counts as a concept, what counts as an argument, and how they connect was written by hand after reading the source PEPs directly.

## 2. System architecture

```
                     ┌──────────────────────────┐
                     │   data/raw/*.rst          │
                     │   29 typing PEPs          │
                     │   (python/peps, GitHub)   │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │  src/build_knowledge.py   │
                     │  hand written RST parser  │
                     │  concept trigger matching │
                     │  argument extraction      │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │ data/processed/           │
                     │ knowledge_state.json      │
                     │ entities + relationships  │
                     └────────────┬─────────────┘
                                  │
                     ┌────────────┴─────────────┐
                     ▼                            ▼
        ┌──────────────────────┐     ┌──────────────────────────┐
        │   src/validate.py     │     │      src/reason.py        │
        │ structural integrity  │     │  new input -> concepts    │
        │       checks          │     │  -> precedent PEPs        │
        └──────────────────────┘     │  -> grounded arguments     │
                                      │  -> recommendation          │
                                      └──────────────┬───────────┘
                                                     ▼
                                       ┌──────────────────────────┐
                                       │  output/last_report.json  │
                                       │  printed report to CLI    │
                                       └──────────────────────────┘
```

### Entity and relationship model

```
   Person ──AUTHORED_BY / DELEGATED_TO──▶ PEP
   PEP ──REFERENCES──▶ PEP
   PEP ──SUPERSEDES / SUPERSEDED_BY──▶ PEP
   PEP ──DISCUSSES_CONCEPT──▶ Concept
   PEP ──HAS_ARGUMENT──▶ Argument
   Argument ──ARGUMENT_ABOUT──▶ Concept
```

Four entity types (PEP, Person, Concept, Argument) and eight relationship types connect the graph. The full reasoning behind each of these choices is documented in `approach.md`.

## 3. Project structure

```
pep-knowledge/
├── README.md                      this file
├── approach.md                    design reasoning, read this first
├── data/
│   ├── raw/                       29 source PEP files, fetched from python/peps
│   └── processed/
│       └── knowledge_state.json   the built knowledge graph, inspectable on its own
├── src/
│   ├── build_knowledge.py         parses data/raw into knowledge_state.json
│   ├── reason.py                  CLI, takes a new input and returns a report
│   ├── timeline.py                CLI, walks one concept's history chronologically
│   └── validate.py                structural integrity checks on the graph
└── output/
    └── last_report.json           written each time reason.py runs
```

## 4. Requirements and installation

This project uses the Python standard library only. There is nothing to install.

```bash
python3 --version   # 3.9 or newer required
```

Clone or unzip the project, then move into it:

```bash
cd pep-knowledge
```

## 5. Building the knowledge state

The 29 PEP source files are already included in `data/raw/`, so the knowledge state can be built immediately. If you want to refresh them from GitHub first, that is optional:

```bash
cd data/raw
for p in 0482 0483 0484 0526 0544 0560 0561 0563 0585 0586 0589 0591 0593 \
         0604 0612 0613 0646 0647 0655 0673 0675 0681 0692 0695 0698 0702 \
         0729 0742 0746; do
  curl -sL -o "pep-${p}.rst" "https://raw.githubusercontent.com/python/peps/main/peps/pep-${p}.rst"
done
cd ..
```

Build the graph:

```bash
cd src
python3 build_knowledge.py
```

Expected output looks like this:

```
Built knowledge state: 29 PEPs, 27 people, 21 concepts, 425 arguments
Edge counts: AUTHORED_BY=45, REFERENCES=96, DISCUSSES_CONCEPT=139, ...
Written to ../data/processed/knowledge_state.json
```

Then confirm the graph is structurally sound, meaning every edge points at an entity that actually exists in the graph:

```bash
python3 validate.py
```

## 6. Using the reasoning interface

This is the testable interface. Give it a feature idea that was never part of the original 29 PEPs, either as a command line argument or through standard input.

```bash
cd src
python3 reason.py "Should Python allow marking a TypedDict field as read-only so a type checker can prevent mutation?"
```

or

```bash
echo "I want flow sensitive narrowing tied to isinstance checks against Protocol classes" | python3 reason.py
```

The report printed to the terminal includes:

- Matched concepts, the curated topics in the knowledge base that the new input touches
- Precedent PEPs, ranked by how many matched concepts they share
- Arguments you will likely face, real extracted objections pulled from the actual PEP text, not generated
- A one paragraph recommendation naming the strongest precedent and which section of it to read first

The same report is also written as structured JSON to `output/last_report.json` after every run.

### Concept timeline, a second way of reasoning over the same graph

`reason.py` answers "what precedent exists for a new idea." A related but different question shows up directly in the assignment brief: a developer who encounters a behavior that seems arbitrary and wants to understand the original debate behind it. `timeline.py` answers that one.

List every concept the knowledge base knows about:

```bash
python3 timeline.py --list
```

Walk the chronological history of one concept, including the supersession chain and the actual debated points at each stage:

```bash
python3 timeline.py type_narrowing
```

This traces PEP-544 through PEP-586 through PEP-647 through PEP-742, showing the point where `TypeGuard` was replaced by `TypeIs` and the real objection text that drove that change, straight from the PEP source, not generated. The same graph, walked a second way.

## 7. Configuration

No environment variables, no API keys, and no external services are required to run this project. Network access is only used once, to fetch the raw PEP files from GitHub, and the files are already included in this repository so that step is optional.

## 8. Scope and limitations

This project is scoped to Python's typing PEPs specifically, not the full set of roughly 300 PEPs. That scoping decision, along with every other design tradeoff, is explained in `approach.md`.

The concept vocabulary used for matching is a fixed, hand curated list of 21 typing concepts. A genuinely novel idea that shares no vocabulary with that list will correctly return no match rather than a forced, misleading one. This is a deliberate tradeoff in favor of explainable, honest results over broader but less grounded coverage.

## 9. Further reading

`approach.md` covers the reasoning behind every decision in this project: what data was chosen and why, how entities and relationships were modeled, how the knowledge representation was built, how the system handles new input, and what would be built next given more time. It is the document to read before looking at anything else.

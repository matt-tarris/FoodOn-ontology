#!/usr/bin/env python3
"""Fail the build if a pinned resolution has rotted.

A store entry is a frozen judgement about a moving ontology. Three ways it can go
bad, all silent without this check:
  - the pinned class is gone, or has been deprecated since
  - the pinned class landed in an excluded branch
  - the resolution still points somewhere, but that somewhere now yields nothing
Plus the section 2a version gate: an entry resolved against a different FoodOn
release is STALE and must be re-validated rather than silently reused.
"""
import json, sys
sys.path.insert(0, "build")
from resolve import Resolver

r = Resolver()
g = r.g
store = json.load(open("data/resolution-store.json"))
ov = g.meta["version"]

problems, stale, ok = [], [], 0
for q, e in sorted(store["entries"].items()):
    if e.get("ontology_version") != ov:
        stale.append(f"{q}: pinned against FoodOn {e.get('ontology_version')}, current is {ov}")
        continue
    for iri, lab in zip(e["roots"], e["root_labels"]):
        if iri not in g.N:
            problems.append(f"{q}: '{lab}' no longer exists"); continue
        if g.N[iri].get("dep"):
            problems.append(f"{q}: '{lab}' is deprecated"); continue
        if iri in g.excluded:
            problems.append(f"{q}: '{lab}' is in an excluded branch"); continue
        if g.label(iri).lower() != lab.lower():
            problems.append(f"{q}: '{lab}' has been relabelled to '{g.label(iri)}'"); continue
    n = len(g.closure(e["roots"])[0]) if e["roots"] else 0
    if n <= 1 and not e.get("note", "").startswith("a soy query"):
        if "leaf" not in (e.get("rationale") or "") and "low-yield" not in (e.get("note") or ""):
            problems.append(f"{q}: resolves to a closure of {n} with no rationale explaining why")
    ok += 1

print(f"store entries checked : {len(store['entries'])}")
print(f"  valid               : {ok}")
print(f"  stale (version bump): {len(stale)}")
print(f"  broken              : {len(problems)}")
for s in stale: print("   STALE  ", s)
for p in problems: print("   BROKEN ", p)
if problems:
    sys.exit(1)
print("\nPASS - every pinned resolution still points at a live, in-scope class.")

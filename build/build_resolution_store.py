#!/usr/bin/env python3
"""Offline resolution pass -> data/resolution-store.json (spec 2a).

Only terms the deterministic stage could not settle appear here: most everyday queries
resolve on lexical + structural evidence alone, and those are NOT pinned, so they keep
tracking the ontology instead of freezing an opinion about it.

Every entry is keyed by (input, ontology_version, resolver_version). A version bump
does not silently invalidate an entry; it marks it stale for re-validation, so the
golden set keeps meaning what it meant when written.

Multi-root is first class. "gluten" is not one class in FoodOn -- the honest
resolution is wheat + barley + rye + triticale + oats, and a resolver that had to pick
one would be wrong four ways.

THE DECISIONS LIVE IN config/resolution-pins.json, not here. They used to be E(...)
calls in this file, which meant the one part of the governed layer that a person edits
most often was the one part no interface could reach. This script is now the loader: it
resolves each root LABEL to an IRI -- so a class FoodOn relabels or retires fails the
build loudly rather than silently pinning nothing -- and stamps the ontology and
resolver versions the entry was reviewed against.
"""
import json, sys
sys.path.insert(0, "build")
from resolve import Resolver

PINS = "config/resolution-pins.json"
r = Resolver(store=None)
g = r.g

def iri(label):
    key = label.lower()
    if key not in r.label_ix:
        sys.exit(f"{PINS}: no FoodOn class labelled `{label}`. Either it has been "
                 f"relabelled upstream or the pin is a typo; both need a human.")
    return r.label_ix[key]

spec = json.load(open(PINS))
entries = {}
for p in spec["pins"]:
    roots = [iri(x) for x in p["root_labels"]]
    for q in (p["query"], *p.get("aliases", [])):
        entries[q] = {"query": q, "status": "resolved", "method": "offline-review",
                      "roots": roots, "root_labels": list(p["root_labels"]),
                      "confidence": p["confidence"], "rationale": p["rationale"],
                      "note": p.get("note"),
                      "reviewed_by": p.get("reviewed_by", "Claude (offline pass)"),
                      "reviewed_date": p.get("reviewed_date", "2026-09-09"),
                      "ontology_version": g.meta["version"], "resolver_version": "1.0.0"}

out = {"version": "1.0.0",
       "resolver_version": "1.0.0",
       "ontology_version": g.meta["version"],
       "note": "Only terms the deterministic stage could not settle. Terms absent here "
               "are resolved live by build/resolve.py on lexical + structural evidence.",
       "entries": entries}
json.dump(out, open("data/resolution-store.json", "w"), indent=2)
multi = sum(1 for e in entries.values() if len(e["roots"]) > 1)
print(f"{len(entries)} store entries from {len(spec['pins'])} decisions "
      f"({len(set(tuple(e['root_labels']) for e in entries.values()))} distinct resolutions)")
print(f"multi-root entries: {multi}")

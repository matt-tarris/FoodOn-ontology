#!/usr/bin/env python3
"""Ad-hoc structural probe: how do the spec's test cases actually connect?"""
import json, collections, sys

g = json.load(open("data/foodon-asserted.obo.json"))["graphs"][0]
lbl = {n["id"]: n.get("lbl", "") for n in g["nodes"]}
dep = {n["id"] for n in g["nodes"] if n.get("meta", {}).get("deprecated")}

def curie(iri):
    t = iri.rsplit("/", 1)[-1]
    return t.replace("_", ":", 1) if "_" in t else t

# all typed edges: subject -> [(pred, object)] and reverse
out = collections.defaultdict(list)
inc = collections.defaultdict(list)
for e in g["edges"]:
    out[e["sub"]].append((e["pred"], e["obj"]))
    inc[e["obj"]].append((e["pred"], e["sub"]))
for ax in g["logicalDefinitionAxioms"]:
    c = ax["definedClassId"]
    for gid in ax.get("genusIds") or []:
        out[c].append(("is_a", gid)); inc[gid].append(("is_a", c))
    for r in ax.get("restrictions") or []:
        if r and r.get("propertyId"):
            out[c].append((r["propertyId"], r["fillerId"]))
            inc[r["fillerId"]].append((r["propertyId"], c))

def find(sub, limit=12):
    s = sub.lower()
    hits = [(i, l) for i, l in lbl.items() if l and s in l.lower() and i not in dep]
    hits.sort(key=lambda x: (len(x[1]), x[1]))
    return hits[:limit]

def show(iri, depth=0):
    print(f"  {curie(iri):<22} {lbl.get(iri,'?')}")
    for p, o in sorted(out.get(iri, []))[:14]:
        print(f"      --{lbl.get(p, p if p=='is_a' else curie(p)):<26}-> {curie(o):<20} {lbl.get(o,'?')}")

for term in sys.argv[1:]:
    print(f"\n{'='*100}\nSEARCH: {term}\n{'='*100}")
    for iri, l in find(term):
        show(iri)
        print()


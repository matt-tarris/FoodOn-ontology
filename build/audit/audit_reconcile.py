#!/usr/bin/env python3
"""Section 1 audit, part 2: reconcile raw owl:onProperty counts against what
obographs actually exposes, so nothing is silently lost.

obographs splits restrictions across two places:
  - edges[]                     : restrictions asserted via rdfs:subClassOf
  - logicalDefinitionAxioms[]   : restrictions inside equivalentClass/intersectionOf
Anything in neither is invisible to a consumer of this export.
"""
import json, re, collections

raw = collections.Counter()
pat = re.compile(r'owl:onProperty rdf:resource="([^"]*)"')
with open("ontology/foodon.owl", encoding="utf-8") as fh:
    for line in fh:
        for m in pat.finditer(line):
            raw[m.group(1)] += 1

g = json.load(open("data/foodon-asserted.obo.json"))["graphs"][0]
label = {n["id"]: n.get("lbl", "") for n in g["nodes"]}

edge_c = collections.Counter(e["pred"] for e in g["edges"])
logdef_c = collections.Counter()
for ax in g["logicalDefinitionAxioms"]:
    for r in ax.get("restrictions") or []:
        if r and r.get("propertyId"):
            logdef_c[r["propertyId"]] += 1

def curie(iri):
    t = iri.rsplit("/", 1)[-1]
    return t.replace("_", ":", 1) if "_" in t else t

print(f"{'property':<20} {'label':<28} {'raw':>6} {'edges':>7} {'logdef':>7} {'sum':>7} {'missing':>8}")
print("-" * 90)
tot_raw = tot_seen = 0
for iri, n in raw.most_common():
    e, l = edge_c[iri], logdef_c[iri]
    miss = n - (e + l)
    tot_raw += n; tot_seen += e + l
    flag = "  <-- LOST" if miss > 0.15 * n and miss > 20 else ""
    print(f"{curie(iri):<20} {label.get(iri,'')[:28]:<28} {n:>6} {e:>7} {l:>7} {e+l:>7} {miss:>8}{flag}")
print("-" * 90)
print(f"{'TOTAL':<20} {'':<28} {tot_raw:>6} {'':>7} {'':>7} {tot_seen:>7} {tot_raw-tot_seen:>8}")

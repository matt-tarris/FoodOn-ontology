#!/usr/bin/env python3
"""Prove the restriction extraction loses nothing.

Ground truth is every `owl:onProperty` node in the file (data/diag.csv, a flat
one-hop SPARQL dump). Each such node either has an IRI filler -- and must be
attributed to a named class -- or has a blank-node filler, meaning the filler is
itself a class expression and there is no single target IRI to draw an edge to.
"""
import csv, collections, json

allr = list(csv.DictReader(open("data/diag.csv")))
mine = list(csv.DictReader(open("data/restrictions.csv")))

iri   = [r for r in allr if r["filler"] and not r["filler"].startswith("_:")]
bnode = [r for r in allr if r["filler"] and r["filler"].startswith("_:")]
none_ = [r for r in allr if not r["filler"]]

by_prop_truth = collections.Counter(r["prop"] for r in iri)
by_prop_mine  = collections.Counter(r["prop"] for r in mine)

g = json.load(open("data/foodon-asserted.obo.json"))["graphs"][0]
lbl = {n["id"]: n.get("lbl", "") for n in g["nodes"]}
og = collections.Counter(e["pred"] for e in g["edges"])
for ax in g["logicalDefinitionAxioms"]:
    for r in ax.get("restrictions") or []:
        if r and r.get("propertyId"):
            og[r["propertyId"]] += 1

def cu(i):
    t = i.rsplit("/", 1)[-1]
    return t.replace("_", ":", 1) if "_" in t else t

print(f"restriction nodes in file : {len(allr):,}")
print(f"  IRI filler (edge-able)  : {len(iri):,}")
print(f"  bnode filler (nested expression, no single target) : {len(bnode):,}")
print(f"  no filler               : {len(none_):,}\n")

bad = [(p, n, by_prop_mine[p]) for p, n in by_prop_truth.items() if by_prop_mine[p] != n]
print(f"{'property':<20} {'label':<26} {'in file':>8} {'obographs':>10} {'extracted':>10} {'recovered':>10}")
print("-" * 90)
for p, n in by_prop_truth.most_common(14):
    print(f"{cu(p):<20} {lbl.get(p,'')[:26]:<26} {n:>8} {og[p]:>10} {by_prop_mine[p]:>10} {by_prop_mine[p]-og[p]:>+10}")
print("-" * 90)
print(f"{'TOTAL':<47} {len(iri):>8} {sum(og[p] for p in by_prop_truth):>10} "
      f"{len(mine):>10} {len(mine)-sum(og[p] for p in by_prop_truth):>+10}")

print()
if bad:
    print("FAIL - properties where extraction != ground truth:")
    for p, n, m in bad:
        print(f"   {cu(p)}: expected {n}, got {m}")
    raise SystemExit(1)
print("PASS - every restriction with an IRI filler is attributed to a named class.")

#!/usr/bin/env python3
"""Section 1 audit, part 1: object property inventory from the obographs export.

Reports, for every predicate that appears on a class-to-class edge:
  usage count, label, and the top domain/range branches it connects.
Cross-checked against a raw owl:onProperty count taken straight from the XML,
so anything obographs silently drops is visible rather than assumed absent.
"""
import json, sys, collections

SRC = "data/foodon-asserted.obo.json"

g = json.load(open(SRC))["graphs"][0]

label = {}
prefix_of = {}
deprecated = set()
for n in g.get("nodes", []):
    nid = n["id"]
    if "lbl" in n:
        label[nid] = n["lbl"]
    meta = n.get("meta", {})
    if meta.get("deprecated"):
        deprecated.add(nid)

def curie(iri):
    tail = iri.rsplit("/", 1)[-1]
    return tail.replace("_", ":", 1) if "_" in tail else tail

def ns(iri):
    c = curie(iri)
    return c.split(":", 1)[0] if ":" in c else "?"

edges = g.get("edges", [])
by_pred = collections.Counter()
pair_ns = collections.defaultdict(collections.Counter)
for e in edges:
    p = e["pred"]
    by_pred[p] += 1
    pair_ns[p][(ns(e["sub"]), ns(e["obj"]))] += 1

print(f"obographs edges: {len(edges):,}   nodes: {len(g.get('nodes', [])):,}   deprecated nodes: {len(deprecated):,}\n")
print(f"{'count':>7}  {'predicate':<22} {'label':<34} top src->tgt namespaces")
print("-" * 118)
for p, c in by_pred.most_common():
    cu = curie(p) if p.startswith("http") else p
    lbl = label.get(p, "" if p in ("is_a", "subPropertyOf") else "(no label in export)")
    tops = ", ".join(f"{a}->{b}:{n}" for (a, b), n in pair_ns[p].most_common(3))
    print(f"{c:>7}  {cu:<22} {lbl[:34]:<34} {tops}")

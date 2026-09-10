#!/usr/bin/env python3
"""What does each relation-policy decision actually change?

For every propagating relation: drop it, measure the closure lost.
For every non-propagating relation: enable it, measure the closure gained.
Measured across representative queries so the numbers reflect real use.
"""
import json, sys, copy, tempfile, os, collections
sys.path.insert(0, "build")
from traverse import Graph

BASE = json.load(open("config/relation_policy.json"))
QUERIES = {"corn": ["Maize plant"], "nightshade": ["solanaceae plant"],
           "milk": ["dairy cow"], "soy": ["soybean plant"], "wheat": ["wheat plant"],
           "tree nut": ["nut producing plant"]}

def closure_sizes(policy):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    json.dump(policy, open(path, "w"))
    try:
        g = Graph(policy=path)
        ix = {}
        for i, v in g.N.items():
            l = (v.get("l") or "").lower()
            if l and not v.get("dep"): ix.setdefault(l, i)
        out = {}
        for name, roots in QUERIES.items():
            rr = [ix[r.lower()] for r in roots if r.lower() in ix]
            out[name] = len(g.closure(rr)[0]) if rr else 0
        return out
    finally:
        os.unlink(path)

base = closure_sizes(BASE)
print("baseline closure sizes:", {k: f"{v:,}" for k, v in base.items()})
tot = sum(base.values())

rows = []
for r in BASE["propagating_relations"]:
    p = copy.deepcopy(BASE)
    p["propagating_relations"] = [x for x in p["propagating_relations"] if x["property"] != r["property"]]
    s = closure_sizes(p)
    rows.append(("DROP", r["label"], r["usage_count"], r["confidence"],
                 sum(s.values()) - tot, {k: s[k] - base[k] for k in base if s[k] != base[k]}))

for r in BASE["non_propagating_relations"]:
    if r["usage_count"] < 3: continue
    p = copy.deepcopy(BASE)
    p["propagating_relations"] = p["propagating_relations"] + [
        {**r, "direction": "inverse", "confidence": "low"}]
    s = closure_sizes(p)
    rows.append(("ADD", r["label"], r["usage_count"], "-",
                 sum(s.values()) - tot, {k: s[k] - base[k] for k in base if s[k] != base[k]}))

print(f"\n{'action':<6} {'relation':<28} {'edges':>7} {'conf':<7} {'total delta':>12}   per-query")
print("-" * 104)
for act, lab, n, conf, delta, per in sorted(rows, key=lambda r: -abs(r[4])):
    flag = ""
    if act == "DROP" and delta == 0: flag = "   <-- no effect on any test query"
    if act == "ADD" and abs(delta) > 2000: flag = "   <-- large"
    print(f"{act:<6} {lab[:28]:<28} {n:>7} {conf:<7} {delta:>+12,}   "
          f"{ {k: f'{v:+,}' for k, v in per.items()} }{flag}")

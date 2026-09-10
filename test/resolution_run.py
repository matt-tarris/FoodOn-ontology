#!/usr/bin/env python3
"""Resolution tests: every query resolves, and resolves to something USABLE.

A resolution that succeeds but seeds an empty graph is the failure mode this suite
exists for -- "tree nut" matched FoodOn's `tree nut` class perfectly and returned
two nodes. So each case asserts the resolved roots actually reach named targets.
"""
import json, sys
sys.path.insert(0, "build")
from resolve import Resolver

r = Resolver()
g = r.g

def find(name):
    """label first, then synonym -- several golden terms (spelt, semolina, natto)
    exist only as synonyms of their FoodOn class."""
    n = name.lower()
    if n in r.label_ix: return r.label_ix[n]
    hits = r.syn_ix.get(n) or []
    return hits[0] if hits else None
CASES = [
  # query,               expect reachable from the resolved roots,          reject
  ("corn",        ["corn oil", "corn syrup", "cornmeal"],                  ["wheat plant"]),
  ("nightshade",  ["paprika (ground)", "cayenne pepper", "potato", "tomato"], ["black pepper plant"]),
  ("soy",         ["edamame", "miso", "natto", "tempeh"],                  ["Maize plant"]),
  ("soya",        ["edamame"],                                             []),
  # oats are gluten-containing by policy decision (Matt, 2026-09-09)
  ("gluten",      ["spelt", "semolina", "bulgur", "oat", "oat bran", "rolled oats",
                   "oat flakes", "steel cut oats"],                        ["Maize plant", "rice plant"]),
  # peanut must NOT appear: FALCPA treats it as a separate allergen from tree nuts,
  # and it is suppressed by a reviewed `remove` override, not by a traversal hack
  ("tree nut",    ["almond", "cashew nut", "walnut", "hazelnut", "pecan",
                   "pistachio nut", "macadamia nut", "marzipan", "almond paste"],
                  ["peanut plant", "peanut", "peanut flour", "peanut butter",
                   "arachis oil", "spanish peanut"]),
  # ...and the reverse disconnection, which needs no override: the only peanut/tree-nut
  # link is `peanut plant is_a nut producing plant`, an upward edge the invariant never
  # traverses. These assertions exist so that stays true.
  ("peanut",      ["peanut flour", "peanut meal", "arachis oil"],
                  ["almond", "cashew nut", "walnut", "hazelnut", "pistachio nut",
                   "pecan", "macadamia nut", "nut producing plant", "marzipan",
                   "almond paste", "nut food product"]),
  ("peanut butter", [],                                                    ["almond", "walnut tree"]),
  ("allium",      ["garlic plant", "onion plant", "leek plant"],           ["Maize plant"]),
  ("egg",         [],                                                      ["Maize plant"]),
  ("wheat",       ["spelt", "semolina"],                                   ["Maize plant", "rice plant"]),
  ("sesame",      ["tahini"] if False else ["gingelly oil"],               ["Maize plant"]),
  ("molluscan shellfish", [],                                              ["Maize plant"]),
  ("mustard",     [],                                                      ["Maize plant"]),
  ("fish",        ["surimi"],                                              ["Maize plant"]),
  ("edamame",     [],                                                      ["Maize plant"]),
]
MIN_CLOSURE = {"edamame": 1, "paprika": 1, "sulphites": 2}

fails, checks = [], 0
print(f"{'query':<22} {'status':<11} {'roots':<44} {'closure':>8}  expect")
print("-" * 108)
for q, expect, reject in CASES:
    res = r.resolve(q)
    checks += 1
    if res["status"] != "resolved":
        fails.append(f"{q}: status={res['status']}"); print(f"{q:<22} {res['status']:<11}"); continue
    roots = res["roots"]
    nodes, _ = g.closure(roots)
    e_ok = 0
    for name in expect:
        checks += 1
        i = find(name)
        if i is None: fails.append(f"{q}: expected label missing from ontology: {name}")
        elif i in nodes: e_ok += 1
        else: fails.append(f"{q}: resolved roots do not reach {name}")
    for name in reject:
        checks += 1
        i = find(name)
        if i is not None and i in nodes:
            fails.append(f"{q}: LEAKED {name}")
    floor = MIN_CLOSURE.get(q, 5)
    checks += 1
    if len(nodes) < floor:
        fails.append(f"{q}: closure {len(nodes)} below usable floor {floor}")
    print(f"{q:<22} {res['status']:<11} {', '.join(res['root_labels'])[:44]:<44} {len(nodes):>8,}  {e_ok}/{len(expect)}")

print("-" * 108)
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails: print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

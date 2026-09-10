#!/usr/bin/env python3
"""Golden-set and invariant tests for the avoidance traversal."""
import json, sys, collections
sys.path.insert(0, "build")
from traverse import Graph, AGENCY_ROOT

g = Graph()
spec = json.load(open("test/golden.json"))

byl = {}
for i, v in g.N.items():
    l = (v.get("l") or "").lower()
    if l and not v.get("dep"):
        byl.setdefault(l, i)

def lookup(name):
    return byl.get(name.lower())

fails, total, missing_labels = [], 0, set()
print(f"{'case':<52} {'nodes':>7} {'expect':>8} {'reject':>8}")
print("-" * 82)

for case in spec["cases"]:
    roots = []
    for r in case["roots"]:
        i = lookup(r)
        if i is None: missing_labels.add(r)
        else: roots.append(i)
    if not roots:
        fails.append(f"{case['name']}: no roots resolved"); continue

    nodes, edges = g.closure(roots)
    reached = set(nodes)

    exp_ok = exp_bad = 0
    for name in case["expect"]:
        total += 1
        i = lookup(name)
        if i is None:
            missing_labels.add(name); exp_bad += 1
            fails.append(f"{case['name']}: expected label not in ontology: {name}")
        elif i in reached: exp_ok += 1
        else:
            exp_bad += 1
            fails.append(f"{case['name']}: MISSING {name}")

    rej_ok = rej_bad = 0
    for name in case["reject"]:
        total += 1
        i = lookup(name)
        if i is None: continue          # absent label cannot leak
        if i in reached:
            rej_bad += 1
            fails.append(f"{case['name']}: LEAKED {name}")
        else: rej_ok += 1

    # agency branch must never appear
    leaked_agency = reached & (g.excluded | {AGENCY_ROOT})
    if leaked_agency:
        fails.append(f"{case['name']}: agency-branch classes leaked ({len(leaked_agency)})")

    if case.get("require_convergence"):
        total += 1
        conv = [n for n in nodes.values() if n["convergent"]]
        if not conv:
            fails.append(f"{case['name']}: no cross-root convergence found")

    print(f"{case['name'][:52]:<52} {len(nodes):>7,} {exp_ok}/{exp_ok+exp_bad:>6} {rej_ok}/{rej_ok+rej_bad:>6}")

print("-" * 82)
if missing_labels:
    print("\nlabels not found in ontology (test data issue, not traversal):")
    for m in sorted(missing_labels): print("   ", m)
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails: print("   -", f)
    sys.exit(1)
print(f"\nPASS - {total} assertions")

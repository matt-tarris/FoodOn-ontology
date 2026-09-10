#!/usr/bin/env python3
"""Score the allergen golden set, each relation type by its own criteria.

  containment       must be REACHED. If FoodOn has no class at all the case is
                    BLOCKED, not failed -- no traversal can reach what is absent,
                    and conflating the two hides where the real work is.
  synonym           must RESOLVE to a class inside the allergen's own closure
                    (or to the root). A traversal miss here is meaningless.
  provenance /
  cross_reactivity /
  disputed          must NOT be reached by ontology traversal. Reaching one would
                    be a false containment claim. They are satisfied instead by a
                    reviewed overrides.json entry, reported separately.

SUPERSEDES test/coverage.py, removed 2026-09-10. That script scored the same
supplied list as PRESENT / REACHED / ABSENT and said nothing about the relation, so
it counted `citric acid`, `xanthan gum` and the other 15 may_contain terms as misses
-- and reported 27/40 (68%) recall while this file reports 23/23 (100%). The
difference was never a regression: those terms SHOULD NOT be reached, because the
feedstock is a producer choice and the closure means containment. Scoring them as
failures penalised the correct behaviour, which is why the metric was retired rather
than reconciled.

The raw supplied list it read, test/allergen-derivatives.json, is kept as
provenance. Nothing reads it now: test/allergen-golden.json is what this file
scores, and build/make_allergen_golden.py carries the relation typing that turned
one into the other.
"""
import json, sys, collections
sys.path.insert(0, "build")
from traverse import Graph

g = Graph()
spec = json.load(open("test/allergen-golden.json"))
try:
    ov = json.load(open("config/overrides.json"))
    # only a SIGNED-OFF override counts as coverage. A proposal is not a decision.
    # `remove` overrides are keyed by query_root, not query_class, so guard both
    covered = {(o["query_class"].lower(), o["target_label"].lower())
               for o in ov.get("overrides", [])
               if o.get("query_class") and o.get("target_label") and o.get("reviewed_by")}
    proposed = sum(1 for o in ov.get("overrides", []) if not o.get("reviewed_by"))
except FileNotFoundError:
    ov, covered, proposed = {"overrides": []}, set(), 0

label_ix, syn_ix = {}, collections.defaultdict(list)
for i, v in g.N.items():
    if v.get("dep") or i in g.excluded: continue
    l = (v.get("l") or "").lower()
    if l: label_ix.setdefault(l, i)
    for s in v.get("syn", []): syn_ix[s.lower()].append(i)

def find(term):
    t = term.strip().lower()
    if t in label_ix: return [label_ix[t]]
    return syn_ix.get(t, [])

NOT_CONTAINMENT = {"provenance", "cross_reactivity", "disputed"}
tally = collections.Counter()
rows = []
failures = []

for block in spec["allergens"]:
    common = block["common"]
    roots = [i for r in block["roots"] for i in find(r)]
    reached = set(g.closure(roots)[0]) if roots else set()
    per = collections.Counter()
    for t in block["terms"]:
        term, rel = t["term"], t["relation"]
        ids = find(term)
        hit = bool(set(ids) & reached)
        if rel == "containment":
            if not ids:      status = "BLOCKED"
            elif hit:        status = "PASS"
            else:            status = "FAIL"
        elif rel == "synonym":
            if not ids:      status = "BLOCKED"
            elif hit or set(ids) & set(roots): status = "PASS"
            else:            status = "FAIL"
        else:
            if hit:
                status = "FAIL"          # false containment via structure
                failures.append(f"{common}/{term} ({rel}): reached by traversal, which asserts containment it should not")
            elif (common.lower(), term.lower()) in covered:
                status = "PASS"          # carried by a reviewed override
            else:
                status = "UNCOVERED"     # correctly not traversed, no override yet
        if status == "FAIL" and rel in ("containment", "synonym"):
            failures.append(f"{common}/{term} ({rel}): class exists but traversal did not reach it")
        per[status] += 1; tally[(rel, status)] += 1
    rows.append((common, len(block["terms"]), per))

print(f"{'allergen':<30} {'terms':>6} {'pass':>6} {'fail':>6} {'blocked':>8} {'uncov':>6}")
print("-" * 68)
for common, n, per in rows:
    print(f"{common:<30} {n:>6} {per['PASS']:>6} {per['FAIL']:>6} {per['BLOCKED']:>8} {per['UNCOVERED']:>6}")
print("-" * 68)

print(f"\n{'relation':<18} {'pass':>6} {'fail':>6} {'blocked':>8} {'uncovered':>10}   scored on")
print("-" * 78)
CRIT = {"containment": "must be reached", "synonym": "must resolve into closure",
        "provenance": "must NOT be reached; needs an override",
        "cross_reactivity": "must NOT be reached; needs an override",
        "disputed": "must NOT be reached; needs an override"}
for rel in ("containment", "synonym", "provenance", "cross_reactivity", "disputed"):
    p, f = tally[(rel, "PASS")], tally[(rel, "FAIL")]
    b, u = tally[(rel, "BLOCKED")], tally[(rel, "UNCOVERED")]
    print(f"{rel:<18} {p:>6} {f:>6} {b:>8} {u:>10}   {CRIT[rel]}")

cp, cf, cb = tally[("containment","PASS")], tally[("containment","FAIL")], tally[("containment","BLOCKED")]
print(f"\ntraversal recall on containment terms FoodOn actually has: "
      f"{cp}/{cp+cf} ({100*cp/max(1,cp+cf):.0f}%)")
print(f"containment terms absent from FoodOn (cannot be reached at all): {cb}")
if proposed:
    print(f"\n{proposed} overrides are PROPOSED but unsigned, so they do not yet count as "
          f"coverage. Review config/overrides.json to convert UNCOVERED to PASS.")
if failures:
    print(f"\n{len(failures)} FAILURES:")
    for x in failures: print("   -", x)
    sys.exit(1)
print("\nNo false-containment failures.")

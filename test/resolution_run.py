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

  # --- facet merge -----------------------------------------------------------
  # FoodOn splits one ingredient across a plant, a food, a `<X> food product`
  # grouping and a taxon. Those are facets, not competing senses, and scoring them
  # against each other left `tomato` 1.8 points inside the margin and therefore
  # unresolved. Each of these must now resolve AND reach real cuisine targets.
  ("tomato",      ["tomato juice food product", "tomato (whole or pieces)"], ["Maize plant"]),
  ("peach",       ["peach (canned)"],                                      ["Maize plant"]),
  ("onion",       ["onion powder", "onion (raw)", "onion soup food product"], ["Maize plant"]),
  ("rice",        ["rice flour", "rice bran"],                             ["wheat plant"]),
  ("lemon",       ["lemon peel"],                                          ["Maize plant"]),

  # --- pinned where FoodOn has no base class ---------------------------------
  # wine, beer and beef exist upstream only as preparation variants
  # (`wine (dealcoholized)`, `beef (ground)`), so no scoring rule can reach a usable
  # root. These are pinned in data/resolution-store.json. `beef` additionally carries
  # a `remove` override: its root pivots through `in taxon Bos taurus` and would
  # otherwise put cow milk and cheddar on a beef-avoider's list.
  ("wine",        ["Bordeaux wine", "Chardonnay wine", "fruit wine"],       ["Maize plant"]),
  ("beer",        ["ale", "porter", "india pale ale"],                      ["Maize plant"]),
  ("beef",        ["beef steak", "beef jerky", "beef broth", "beef liver",
                   "corned beef"],                                          ["cow milk", "cheddar cheese"]),

  # --- culinary vocabulary, pinned 2026-09-10 --------------------------------
  # Colloquial, regional and compound names FoodOn does not carry. Harvested from
  # a blind comparison against a query-time LLM: these are the terms it got right
  # and lexical matching could not. Pinned rather than inferred, because each is a
  # fixed fact about vocabulary -- mangetout does not stop meaning snow pea.
  # The rejects matter as much as the expects: two of these were deliberately
  # pinned NARROW, and these assertions are what stops a later "helpful" widening.
  ("mangetout",   ["snow pea pod (edible, fresh)", "sugar snap pea plant"], ["Maize plant"]),
  ("cilantro",    ["coriander leaf", "coriander seed", "curry powder"],
                  ["Maize plant", "parsley"]),
  ("creme fraiche", [],        ["coffee creamer", "whipped cream", "clotted cream"]),
  ("double cream",  [],        ["coffee creamer", "clotted cream"]),
  ("greek yoghurt", [],        ["frozen yogurt"]),
  ("chilli flakes", ["tabasco pepper plant", "thai pepper plant", "cayenne pepper"],
                  ["black pepper plant"]),
  ("smoked paprika", [],       ["Maize plant"]),
  ("san marzano tomatoes", ["tomato juice food product", "tomato (whole or pieces)"],
                  ["Maize plant"]),
  # shrimp, not crustacean: crab and lobster are a different question
  ("prawns",      ["whiteleg shrimp", "giant tiger prawn"],
                  ["Maize plant", "oyster", "blue crab"]),
]
MIN_CLOSURE = {"edamame": 1, "paprika": 1, "sulphites": 2,
               "creme fraiche": 1, "double cream": 1, "greek yoghurt": 1,
               "smoked paprika": 2}

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
# ---- facet-merge traps -------------------------------------------------------
# The merge takes the longest PREFIX of pairwise-compatible candidates. These three
# are the cases that must NOT be swallowed by it, and each is a different shape:
#
#   strawberry tree   Arbutus unedo. Its 2 classes are a SUBSET of `strawberry`'s 52,
#                     which is why subsumption was rejected as a compatibility test.
#   prawn             four different species, no shared organism at all.
#   coffee            Coffea arabica vs the genus Coffea -- a rank difference, not a
#                     facet difference.
#
# A future loosening of `_interchangeable` that merges any of these is a regression.
#
# Run against a STORE-FREE resolver. `prawn` is pinned to `shrimp` as of 2026-09-10,
# so the live resolver never reaches the merge for it -- and a trap that passes
# because the code path it guards was bypassed is a guard that has quietly stopped
# guarding. Pinning is a decision about one term; the merge behaviour underneath it
# still has to hold, and this is where that is asserted.
r_nopin = Resolver(graph=g, store=None)
TRAPS = [
  ("strawberry", "merges", ["strawberry", "strawberry plant"], ["strawberry tree"]),
  ("prawn",      "holds",  [], []),
  ("coffee",     "holds",  [], []),
]
for q, expect, must_merge, must_exclude in TRAPS:
    res = r_nopin.resolve(q)
    checks += 1
    roots = {g.label(i) for i in (res.get("roots") or [])}
    if expect == "holds":
        if res.get("status") != "ambiguous":
            fails.append(f"TRAP {q}: expected to stay ambiguous, got "
                         f"{res.get('status')} -> {sorted(roots)}")
        continue
    if res.get("status") != "resolved":
        fails.append(f"TRAP {q}: expected a facet merge, got {res.get('status')}")
        continue
    for m in must_merge:
        if m not in roots:
            fails.append(f"TRAP {q}: `{m}` should be one of the merged roots, got {sorted(roots)}")
    for x in must_exclude:
        if x in roots:
            fails.append(f"TRAP {q}: `{x}` is a DIFFERENT organism and must not be "
                         f"merged in; roots were {sorted(roots)}")

# RANK must never be the basis of a merge. This is the real reason subsumption is
# rejected as a compatibility test: a genus closure contains its species closure, so
# "one contains the other" would widen a query from a species to its genus -- the
# same thing config/repair-signoff.json declines by name for `avian animal`.
# (`strawberry` vs `strawberry tree` is NOT this trap: those closures are disjoint.)
RANK_PAIRS = [("ocimum", "ocimum basilicum"), ("coffea", "coffea arabica")]
for broad, narrow in RANK_PAIRS:
    a, b = r.label_ix.get(broad), r.label_ix.get(narrow)
    if not (a and b):
        continue
    checks += 1
    A, B = frozenset(g.closure([a])[0]), frozenset(g.closure([b])[0])
    if not (B < A):
        print(f"  note: {narrow} is no longer inside {broad}; this rank pin has "
              f"changed shape and should be rechecked")
    if r._interchangeable(a, b):
        fails.append(f"`{broad}` and `{narrow}` are reported interchangeable -- a rank "
                     f"difference is being treated as a facet, which widens a species "
                     f"query to its genus")

# and the disjoint case, which is what strawberry actually is
checks += 1
_sb, _st = r.label_ix.get("strawberry"), r.label_ix.get("strawberry tree")
if _sb and _st:
    A, B = frozenset(g.closure([_sb])[0]), frozenset(g.closure([_st])[0])
    if A & B:
        print(f"  note: strawberry and strawberry tree now share {len(A & B)} classes; "
              f"they were disjoint when this pin was written")
    if r._interchangeable(_sb, _st):
        fails.append("`strawberry` and `strawberry tree` (Arbutus unedo) are reported "
                     "interchangeable -- they are different organisms")

if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails: print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

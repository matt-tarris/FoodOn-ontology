#!/usr/bin/env python3
"""Repair pass for omitted `derives from` axioms (audit F6a).

FoodOn applies `<X> food product --derives from--> <X> plant` inconsistently: only
38% of `<X> food product` classes carry it. `hungarian wax pepper food product`
omits it while its sibling `hungarian wax pepper pickle food product` has it, which
is why paprika is structurally disconnected from nightshade.

This is a general repair keyed on FoodOn's own naming convention plus two
structural guards, NOT a per-ingredient list:

  guard 1 - organism-branch compatibility. Both sides must agree on which child of
            `organism material` they descend from. Rejects `elephant food product`
            (mammal material) -> `elephant fish` (fish material).
  guard 2 - uniqueness. More than one candidate source means the name is ambiguous;
            those go to review rather than being applied. Rejects `tea food product`,
            which matches both `tea plant` (Camellia) and `tea tree` (Melaleuca).

Output: data/repairs.json - every accepted and rejected candidate with its reason,
reviewable as a unit and re-derivable when FoodOn updates.
"""
import json, re, collections

ix = json.load(open("data/index.json"))
N, E = ix["nodes"], ix["edges"]
DERIVES = "http://purl.obolibrary.org/obo/RO_0001000"
lbl  = lambda i: N.get(i, {}).get("l", "")
live = lambda i: not N.get(i, {}).get("dep")

parents = collections.defaultdict(list)
src_of  = collections.defaultdict(set)
for e in E:
    if e["p"] == "isa":  parents[e["s"]].append(e["o"])
    if e["p"] == DERIVES: src_of[e["s"]].add(e["o"])

def ancestors(i, cap=4000):
    seen, st = set(), [i]
    while st and len(seen) < cap:
        x = st.pop()
        for p in parents.get(x, ()):
            if p not in seen:
                seen.add(p); st.append(p)
    return seen

# guard 1: organism-branch compatibility.
# Branch markers are every descendant of FoodOn's own `organism material` class --
# discovered, not enumerated. Two classes conflict when their most specific branch
# markers sit in unrelated subtrees (mammal material vs fish material), and agree
# when one subsumes the other (fish material vs animal material).
children = collections.defaultdict(list)
for e in E:
    if e["p"] == "isa":
        children[e["o"]].append(e["s"])

ORG_MATERIAL = next(i for i in N if lbl(i).lower() == "organism material" and live(i))
BRANCH = set()
_st = [ORG_MATERIAL]
while _st:
    x = _st.pop()
    for c in children.get(x, ()):
        if c not in BRANCH:
            BRANCH.add(c); _st.append(c)

# The direct children of `organism material` are FoodOn's own top-level partition
# (animal 9135, plant 8222, organism piece 2745, fungus 179, algae 85, ...). Compare
# at this level: finer comparison wrongly rejects `rye food product` -> `rye plant`,
# because product-side and source-side markers sit in parallel subtrees that never
# subsume each other, while still being the same organism.
KINGDOMS = {}
for _k in children.get(ORG_MATERIAL, ()):
    _seen, _st = set(), [_k]
    while _st:
        _y = _st.pop()
        for _c in children.get(_y, ()):
            if _c not in _seen:
                _seen.add(_c); _st.append(_c)
    KINGDOMS[_k] = _seen
# `organism piece` cross-cuts the others (a piece may be plant or animal), so it
# carries no kingdom evidence.
KINGDOMS = {k: v for k, v in KINGDOMS.items() if lbl(k).lower() != "organism piece"}

def branches(i):
    a = ancestors(i) | {i}
    return {k for k, members in KINGDOMS.items() if a & members}

def compatible(a, b):
    if not a or not b:
        return True                      # no evidence either way -- do not reject
    return bool(a & b)

bylabel = collections.defaultdict(list)
for i in N:
    if live(i) and lbl(i):
        bylabel[lbl(i).lower()].append(i)

FP = re.compile(r"^(.*) food product$")
# `fish` is deliberately absent: fish common names routinely *end* in it
# (elephant fish, swordfish, catfish), so `<X> fish` is ambiguous between a
# compositional source name and a single lexical species name. Every other suffix
# here is compositional in FoodOn's usage.
SOURCE_SUFFIXES = ["plant", "tree", "animal", "cultivar",
                   "plant variety", "bush", "vine", "shrub"]

accepted, rejected = [], []
for i in sorted(N, key=lbl):
    if not live(i) or i in src_of:
        continue
    m = FP.match(lbl(i).lower())
    if not m:
        continue
    stem = m.group(1)
    cands = [c for suf in SOURCE_SUFFIXES for c in bylabel.get(f"{stem} {suf}", [])]
    cands = sorted(set(cands), key=lbl)
    if not cands:
        continue

    pb = branches(i)
    ok = [c for c in cands if compatible(pb, branches(c))]
    dropped = [c for c in cands if c not in ok]
    for c in dropped:
        rejected.append({"product": i, "product_label": lbl(i),
                         "source": c, "source_label": lbl(c),
                         "reason": "organism-branch conflict",
                         "product_branches": sorted(lbl(x) for x in pb),
                         "source_branches": sorted(lbl(x) for x in branches(c))})
    if len(ok) == 1:
        accepted.append({"product": i, "product_label": lbl(i),
                         "source": ok[0], "source_label": lbl(ok[0]),
                         "rule": "label-convention <X> food product -> <X> <source>",
                         "guards_passed": ["organism-branch", "uniqueness"]})
    elif len(ok) > 1:
        for c in ok:
            rejected.append({"product": i, "product_label": lbl(i),
                             "source": c, "source_label": lbl(c),
                             "reason": "ambiguous - multiple candidate sources",
                             "alternatives": [lbl(x) for x in ok]})

json.dump({"version": "2026-09-08",
           "derived_from": "audit F6a; build/repair_derives.py",
           "ontology_version": ix["meta"]["version"],
           "accepted": accepted, "rejected": rejected},
          open("data/repairs.json", "w"), indent=2)

print(f"accepted repairs : {len(accepted)}")
print(f"rejected         : {len(rejected)}")
for r in rejected:
    print(f"   - {r['product_label']:<34} -> {r['source_label']:<28} [{r['reason']}]")
print(f"\npaprika's parent repaired: "
      f"{any('hungarian wax pepper food product' == a['product_label'] for a in accepted)}")

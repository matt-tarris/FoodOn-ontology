#!/usr/bin/env python3
"""Section 1 audit, part 3: label conventions.

Which label shapes act as derivation *sources*, which act as *products*, and how
consistently. This is what lets the repair pass be a general rule keyed on
structure+convention rather than a list of ingredients.
"""
import json, collections, re

ix = json.load(open("data/index.json"))
N, E = ix["nodes"], ix["edges"]
DERIVES = "http://purl.obolibrary.org/obo/RO_0001000"
IN_TAXON = "http://purl.obolibrary.org/obo/RO_0002162"
lbl = lambda i: N.get(i, {}).get("l", "")
live = lambda i: not N.get(i, {}).get("dep")

src_of = collections.defaultdict(set)   # product -> sources
for e in E:
    if e["p"] == DERIVES: src_of[e["s"]].add(e["o"])

sources = {o for s in src_of.values() for o in s}
products = set(src_of)

def tail(i, k=2):
    w = lbl(i).lower().split()
    return " ".join(w[-k:]) if len(w) >= k else " ".join(w)

print("=== label tails of derivation SOURCES (what a thing derives FROM) ===")
for t, c in collections.Counter(tail(i) for i in sources if lbl(i)).most_common(14):
    print(f"  {c:>5}  ...{t}")

print("\n=== label tails of derivation PRODUCTS (what HAS a derives-from) ===")
for t, c in collections.Counter(tail(i) for i in products if lbl(i)).most_common(14):
    print(f"  {c:>5}  ...{t}")

# how consistently does "<X> food product" carry a derives-from?
FP = re.compile(r"^(.*) food product$")
fp = {i: m.group(1) for i in N if live(i) and (m := FP.match(lbl(i).lower()))}
have = {i for i in fp if i in src_of}
print(f"\n=== '<X> food product' classes ===")
print(f"  total live            : {len(fp):,}")
print(f"  with a derives-from   : {len(have):,}  ({100*len(have)/len(fp):.0f}%)")
print(f"  WITHOUT               : {len(fp)-len(have):,}")

# of those without, how many have a same-<X> source-shaped sibling?
bylabel = collections.defaultdict(list)
for i in N:
    if live(i) and lbl(i): bylabel[lbl(i).lower()].append(i)
SRC_SUFFIXES = ["plant", "tree", "animal", "fish", "cultivar", "plant variety", "bush", "vine", "shrub"]
repairable = {}
for i, x in fp.items():
    if i in src_of: continue
    for suf in SRC_SUFFIXES:
        for cand in bylabel.get(f"{x} {suf}", []):
            repairable.setdefault(i, []).append(cand)
print(f"  of those, a '<X> <source>' class exists : {len(repairable):,}   <-- repair candidates")
print("\n  sample:")
for i, cands in list(sorted(repairable.items(), key=lambda kv: lbl(kv[0])))[:12]:
    print(f"    {lbl(i):<46} -> {lbl(cands[0])}")

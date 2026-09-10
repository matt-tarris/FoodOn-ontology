#!/usr/bin/env python3
"""Detect classes whose label says they belong somewhere their ancestry does not.

Found via `rye kernel`, which FoodOn parents under `sumac food product` (adjacent
IDs: sumac berry 00003733, rye kernel 00003734 -- almost certainly a data-entry
slip). The cost is a gluten FALSE NEGATIVE: a rye query never reaches rye kernel.

General rule, same shape as the derives-from repair: if a class's label leads with
a stem naming a known source, and no ancestor's label carries that stem, but a
`<stem> plant` / `<stem> food product` class exists elsewhere, the class is
probably mis-parented. Reported, never auto-applied -- re-parenting changes the
hierarchy itself, which is a heavier edit than adding a derivation edge.
"""
import json, collections, re, csv

ix = json.load(open("data/index.json")); N, E = ix["nodes"], ix["edges"]
lbl  = lambda i: N.get(i, {}).get("l", "") or ""
live = lambda i: not N.get(i, {}).get("dep")
parents = collections.defaultdict(list)
for e in E:
    if e["p"] == "isa": parents[e["s"]].append(e["o"])

def ancestors(i):
    seen, st = set(), [i]
    while st:
        x = st.pop()
        for p in parents.get(x, ()):
            if p not in seen: seen.add(p); st.append(p)
    return seen

# FoodOn carries parallel regulatory classification vocabularies (EFSA FoodEx2,
# US CFR, EC, CCPR) under a single root: `agency food product type`, 6,074 classes.
# These are classification facets, correctly parented inside their own code systems,
# so label-vs-ancestry disagreement there is expected rather than a defect. They are
# also excluded from derivation traversal entirely -- see audit F10.
AGENCY_ROOT = "http://purl.obolibrary.org/obo/FOODON_03400361"
_kids = collections.defaultdict(list)
for e in E:
    if e["p"] == "isa": _kids[e["o"]].append(e["s"])
AGENCY = set(); _st = [AGENCY_ROOT]
while _st:
    _x = _st.pop()
    for _c in _kids.get(_x, ()):
        if _c not in AGENCY: AGENCY.add(_c); _st.append(_c)

# stems that name a source, taken from FoodOn's own `<stem> plant` / `<stem> food
# product` classes rather than from any list of ingredients
STEMS = {}
for i in N:
    if not live(i): continue
    m = re.match(r"^(.*) (?:plant|tree|food product)$", lbl(i).lower())
    if m and len(m.group(1)) >= 3:
        STEMS.setdefault(m.group(1), []).append(i)

def words(s): return set(re.findall(r"[a-z]+", s.lower()))

# stems that name an actual SOURCE ORGANISM, not merely a food-product category.
# `sumac` qualifies (sumac plant exists); `nut`, `fish` and `spice` do not.
ORGANISM_STEMS = {}
for i in N:
    if not live(i): continue
    m = re.match(r"^(.*) (?:plant|tree)$", lbl(i).lower())
    if m and len(m.group(1)) >= 3:
        ORGANISM_STEMS.setdefault(m.group(1), []).append(i)

hits = []
for i in N:
    # Only FoodOn's own classes. Imported taxa (NCBITaxon, PO, CHEBI) are parented
    # by Latin rank name -- `Acacia` under `Acacieae` -- so label-vs-ancestry
    # disagreement is the norm there and carries no signal.
    if not live(i) or not lbl(i) or i in AGENCY: continue
    if N[i].get("ns") != "FOODON": continue
    L = lbl(i).lower()
    toks = re.findall(r"[a-z]+", L)
    if not toks: continue
    stem = toks[0]
    if stem not in STEMS: continue
    if any(i in STEMS[stem] for _ in (0,)): pass
    if i in STEMS.get(stem, []): continue          # the source class itself
    anc = ancestors(i)
    if any(stem in words(lbl(a)) for a in anc): continue   # ancestry agrees
    tgt = [t for t in STEMS[stem] if t != i and t not in AGENCY]
    if not tgt: continue

    # Sharpen: label-vs-ancestry disagreement is NORMAL in FoodOn, because classes
    # are legitimately parented by food type (`almond cheese` -> `nut cheese`),
    # preparation (`albacore (raw)` -> `fish meat (raw)`) or function (`allspice`
    # -> `spice food product`). What made rye kernel a real defect is narrower: its
    # parent names a DIFFERENT SPECIFIC ORGANISM. So require that both the class's
    # own stem and its parent's stem resolve to an actual source organism class
    # (`<stem> plant` / `<stem> tree`), and that the two differ.
    if not ORGANISM_STEMS.get(stem):
        continue
    conflicting = []
    for par in parents.get(i, []):
        ptoks = re.findall(r"[a-z]+", lbl(par).lower())
        if not ptoks: continue
        pstem = ptoks[0]
        if pstem != stem and ORGANISM_STEMS.get(pstem):
            conflicting.append((lbl(par), pstem))
    if not conflicting:
        continue
    hits.append({
        "class": i, "label": lbl(i),
        "current_parents": [lbl(p) for p in parents.get(i, [])],
        "stem": stem,
        "expected_branch": [lbl(t) for t in tgt][:3],
        "conflicting_parents": [c[0] for c in conflicting],
    })

hits.sort(key=lambda h: h["label"])
json.dump({"version": "2026-09-09", "ontology_version": ix["meta"]["version"],
           "note": "reported for review; re-parenting is never auto-applied",
           "candidates": hits}, open("data/misparented.json", "w"), indent=2)
print(f"mis-parenting candidates: {len(hits)}\n")
for h in hits[:40]:
    print(f"  {h['label']:<40} parents={h['current_parents']}  expected ~ {h['expected_branch'][:2]}")

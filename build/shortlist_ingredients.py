#!/usr/bin/env python3
"""Turn each queued ingredient term into a SHORTLIST OF FOODON CLASSES, with ids.

    python3 build/shortlist_ingredients.py

A proposal that names a term still leaves the reviewer trusting the resolver's choice
of class. A shortlist puts the actual classes on screen -- id, label, closure size --
so the final call is a human picking a node, not a human approving a string.

The model's job is NARROWING. It proposed a term; that term's resolved roots lead the
shortlist as the recommendation, and lexical neighbours follow so the reviewer can
overrule it without going to look anything up. The model never gets to be the only
option on the list, which is the point: in this project's own blind test, a model asked
to pick FoodOn classes directly invented `game meat food product` and resolved `white
fish` to all 3,173 fish.

CLOSURE SIZE IS ON EVERY ROW because it is the number that decides whether a class is
the right grain. FoodOn's own `tree nut` reaches 2 classes and looks perfect.
"""
import json, sys, collections

sys.path.insert(0, "build")
from resolve import Resolver
from ingest import MAP_FILE, strip_qualifiers

LIMIT = 6
r = Resolver()
g = r.g
spec = json.load(open(MAP_FILE))
queue = spec.get("requires_signoff", [])

cur = lambda i: i.rsplit("/", 1)[-1].replace("_", ":", 1)


# Namespaces a food can live in. PATO is the reason this list exists: it carries
# `red` and `white` as QUALITIES, and they were arriving as candidates for `red wine
# vinegar` and `white wine vinegar` -- a reviewer clicking one would map an ingredient
# to the colour of itself. BFO, PATO, OBI and the rest describe the world, not the menu.
FOOD_NS = {"FOODON", "NCBITaxon", "CHEBI", "UBERON", "PO", "GAZ", "Q"}


def usable(iri):
    ns = iri.rsplit("/", 1)[-1].split("_")[0]
    return ns in FOOD_NS


def entry(iri, why):
    return dict(iri=iri, label=g.label(iri), curie=cur(iri), why=why,
                closure=len(g.closure([iri])[0]),
                excluded=iri in g.excluded)


def shortlist(e):
    """Recommended first, then anything a reviewer might reasonably prefer."""
    out, seen = [], set()

    def push(iri, why):
        if iri in seen or iri not in g.N or g.N[iri].get("dep") or not usable(iri):
            return
        seen.add(iri)
        out.append(entry(iri, why))

    # 1. what the model proposed, as classes
    if e.get("proposed"):
        res = r.resolve(e["proposed"])
        for i in res.get("roots") or []:
            push(i, f"proposed: `{e['proposed']}`")
    # 2. the deterministic candidates the seeder found
    for c in e.get("candidates") or []:
        res = r.resolve(c["term"])
        for i in res.get("roots") or []:
            push(i, ("dropping `" + (c.get("dropped") or "") + "`") if c.get("risky")
                 else f"lexical: `{c['term']}`")
    # 3. lexical neighbours of the term itself, so the model is never the only option
    for term in (e["term"], strip_qualifiers(e["term"])):
        for h in r.resolve(term).get("candidates") or []:
            iri = h.get("iri") if isinstance(h, dict) else h
            if isinstance(iri, str):
                push(iri, "close lexical match")
    return out[:LIMIT]


n = 0
for e in queue:
    sl = shortlist(e)
    if sl:
        e["shortlist"] = sl
        n += 1
    else:
        e.pop("shortlist", None)
json.dump(spec, open(MAP_FILE, "w"), indent=2)

sizes = collections.Counter(len(e.get("shortlist", [])) for e in queue)
print(f"{n} of {len(queue)} queued terms now carry a shortlist")
print("shortlist length:", dict(sorted(sizes.items())))
one = [e for e in queue if len(e.get("shortlist", [])) == 1]
print(f"  exactly one candidate (a one-click approve): {len(one)}")
none = [e for e in queue if not e.get("shortlist")]
print(f"  no candidate at all (FoodOn has nothing):    {len(none)}")
print(f"\nuses covered by terms with a shortlist: "
      f"{sum(e['uses'] for e in queue if e.get('shortlist')):,} of "
      f"{sum(e['uses'] for e in queue):,}")

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
import json, re, sys, collections

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


# label index for word-subset search, built once
WORDS = {}
for _i, _v in g.N.items():
    _l = (_v.get("l") or "").lower()
    if _l and not _v.get("dep") and _i not in g.excluded and usable(_i):
        WORDS[_i] = set(re.findall(r"[a-z]+", _l))


def word_subset(term, limit=4):
    """Classes whose label contains every word of the term, in any order.

    Substring search misses what a cook actually writes. `rice vinegar` is not a
    substring of `rice wine vinegar`, so the shortlist for the 129-use term offered
    `vinegar` and `rice plant` and nothing else -- and the right class, FOODON:03307370,
    sitting directly under `wine vinegar`, was never shown. Matt found it by hand.

    Ranked by FEWEST EXTRA WORDS, so the most specific match that still contains
    everything asked for comes first.
    """
    want = set(re.findall(r"[a-z]+", term))
    if not want:
        return []
    hits = [(len(w - want), i) for i, w in WORDS.items() if want <= w]
    hits.sort()
    return [(i, n) for n, i in hits[:limit]]


def shortlist(e):
    """Most specific first, then anything a reviewer might reasonably prefer.

    A class whose label contains EVERY word of the term outranks the model's proposal,
    because the proposal got where it is by DISCARDING words. `rice vinegar` was
    proposed as `vinegar` -- correct but coarse -- while FOODON:03307370 `rice wine
    vinegar` sits under `wine vinegar` and says exactly what the recipe said. Ranking
    the proposal first put the right answer fourth, where Matt found it by hand and the
    shortlist had already failed at its job.
    """
    out, seen = [], set()

    def push(iri, why):
        # An excluded-branch class can NEVER match a query -- 6,087 EFSA and GS1
        # code-list classes sit outside the traversal by policy -- so offering one as a
        # mapping target would be offering a mapping that silently never fires.
        if (iri in seen or iri not in g.N or g.N[iri].get("dep")
                or not usable(iri) or iri in g.excluded):
            return
        seen.add(iri)
        out.append(entry(iri, why))

    # 1. classes whose label contains every word of the term, closest first. This is
    #    the most specific evidence available and it leads.
    for term in (strip_qualifiers(e["term"]), e["term"]):
        for i, extra in word_subset(term):
            if extra <= 1:
                push(i, f"names everything in `{term}`")
    # 1b. a SIGNED entry carries no proposal and no candidates -- only what it already
    #     maps to. Without this the correction view offered "FoodOn has no class for
    #     this" on 87 mappings that plainly have one.
    if e.get("maps_to_iri"):
        push(e["maps_to_iri"], "currently mapped here")
    elif e.get("maps_to"):
        for i in r.resolve(e["maps_to"]).get("roots") or []:
            push(i, "currently mapped here")
    # 2. what the model proposed, as classes
    if e.get("proposed"):
        res = r.resolve(e["proposed"])
        for i in res.get("roots") or []:
            push(i, f"proposed: `{e['proposed']}`")
    # 2b. looser word-subset matches
    for term in (strip_qualifiers(e["term"]), e["term"]):
        for i, extra in word_subset(term):
            push(i, f"names everything in `{term}`")
    # 3. the deterministic candidates the seeder found
    for c in e.get("candidates") or []:
        res = r.resolve(c["term"])
        for i in res.get("roots") or []:
            push(i, ("dropping `" + (c.get("dropped") or "") + "`") if c.get("risky")
                 else f"lexical: `{c['term']}`")
    # 4. lexical neighbours, so neither the model nor the existing mapping is the
    #    only option on screen
    for term in (e["term"], strip_qualifiers(e["term"])):
        for h in r.resolve(term).get("candidates") or []:
            iri = h.get("iri") if isinstance(h, dict) else h
            if isinstance(iri, str):
                push(iri, "close lexical match")
    return out[:LIMIT]


nq = ns = 0
for e in queue:
    sl = shortlist(e)
    if sl:
        sl[0]["recommended"] = True; e["shortlist"] = sl; nq += 1
    else:
        e.pop("shortlist", None)
for e in spec.get("mappings", []):
    sl = shortlist(e)
    if sl:
        sl[0]["recommended"] = True; e["shortlist"] = sl; ns += 1
    else:
        e.pop("shortlist", None)
n = nq
json.dump(spec, open(MAP_FILE, "w"), indent=2)

sizes = collections.Counter(len(e.get("shortlist", [])) for e in queue)
print(f"({ns} of {len(spec.get('mappings', []))} signed mappings also carry one, so a "
      f"correction can be made from the same screen)")
print(f"{n} of {len(queue)} queued terms now carry a shortlist")
print("shortlist length:", dict(sorted(sizes.items())))
one = [e for e in queue if len(e.get("shortlist", [])) == 1]
print(f"  exactly one candidate (a one-click approve): {len(one)}")
none = [e for e in queue if not e.get("shortlist")]
print(f"  no candidate at all (FoodOn has nothing):    {len(none)}")
print(f"\nuses covered by terms with a shortlist: "
      f"{sum(e['uses'] for e in queue if e.get('shortlist')):,} of "
      f"{sum(e['uses'] for e in queue):,}")

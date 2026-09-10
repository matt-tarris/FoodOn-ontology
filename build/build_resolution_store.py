#!/usr/bin/env python3
"""Offline resolution pass -> data/resolution-store.json (spec 2a).

Only terms the deterministic stage could not settle appear here: 20 of 30 test
queries resolve on lexical + structural evidence alone, and those are NOT pinned,
so they keep tracking the ontology instead of freezing an opinion about it.

Every entry is keyed by (input, ontology_version, resolver_version). A version bump
does not silently invalidate an entry; it marks it stale for re-validation, so the
golden set keeps meaning what it meant when written.

Multi-root is first class. "gluten" is not one class in FoodOn -- the honest
resolution is wheat + barley + rye + triticale, and a resolver that had to pick one
would be wrong four ways.
"""
import json, sys
sys.path.insert(0, "build")
from resolve import Resolver

r = Resolver(store=None)
g = r.g
L = lambda lab: r.label_ix[lab]

def E(query, labels, confidence, rationale, note=None, aliases=()):
    return {q: {"query": q, "status": "resolved", "method": "offline-review",
                "roots": [L(x) for x in labels], "root_labels": list(labels),
                "confidence": confidence, "rationale": rationale, "note": note,
                "reviewed_by": "Claude (offline pass)", "reviewed_date": "2026-09-09",
                "ontology_version": g.meta["version"], "resolver_version": "1.0.0"}
            for q in (query, *aliases)}

entries = {}
entries.update(E("nightshade", ["solanaceae plant"], "high",
  "No lexical route exists: no FoodOn label or synonym contains 'nightshade' except "
  "unrelated plants (malabar nightshade, black nightshade). Nightshade is the culinary "
  "name for Solanaceae. Root expansion pairs `solanaceae plant` with NCBITaxon "
  "`Solanaceae` automatically, so either resolves to the same 480-node graph.",
  aliases=("nightshades", "solanaceae")))

entries.update(E("soy", ["soybean plant"], "high",
  "'soy' and 'soya' appear on no FoodOn label or synonym. Glycine max is the source "
  "organism; `soybean plant` (closure 125) is the source-form class.",
  aliases=("soya", "soybean", "soja")))

entries.update(E("egg", ["egg or egg component", "chicken egg"], "high",
  "Lexically ambiguous between `chicken egg` (closure 291) and `egg food product` "
  "(72). Resolved to both `egg or egg component` (157, the component-level class "
  "covering yolk and white) and `chicken egg`, because avoidance of egg covers both "
  "the whole egg and its fractions, and neither class subsumes the other.",
  note="multi-root by design: the two classes cover different fractions of the same allergen"))

entries.update(E("tree nut", ["nut producing plant", "nut food product"], "high",
  "FoodOn's own `tree nut` class is a stub: its closure is 2 (itself and "
  "`almond kernel (raw)`), so the lexically perfect match is structurally useless. "
  "`nut producing plant` (385) reaches all eight major tree nuts - almond, cashew, "
  "walnut, hazelnut, pistachio, pecan, macadamia, brazil - and `nut food product` "
  "(538) adds the product side.",
  note="the clearest case for the store: lexical resolution succeeded and was wrong",
  aliases=("tree nuts", "treenut")))

entries.update(E("gluten",
  ["wheat plant", "barley plant", "rye plant", "triticale plant", "oat plant"], "high",
  "FoodOn's `gluten` class has a closure of 1. Gluten is not one organism: the "
  "avoidance-relevant answer is the gluten-containing grains. Wheat (624), barley "
  "(47), rye (26), triticale (6) and oat (40).",
  note="OATS ARE INCLUDED, by decision of Matt 2026-09-09: oats are treated as "
       "gluten-containing unless specifically labelled gluten-free. This is the "
       "stricter, recall-first reading and it is a policy choice, not a botanical "
       "claim - oats contain avenin rather than gluten, and the real risk is "
       "cross-contamination in milling and transport. "
       "THE GLUTEN-FREE-OAT EXCEPTION CANNOT BE EXPRESSED IN THIS GRAPH: FoodOn has "
       "no gluten-free oat class, and its `gluten free claim` class is an isolated "
       "labelling facet with nothing pointing at it. So certified gluten-free oats "
       "must be handled downstream at the product level, where the label is visible. "
       "The graph's claim is about oats as an ingredient, not about any given package.",
  aliases=("gluten-containing grains", "gluten containing grains")))

entries.update(E("molluscan shellfish", ["mollusc"], "high",
  "`mollusc` (closure 480) is the correct class. Note FoodOn keeps molluscs and "
  "crustaceans separate, matching EU labelling which treats them as distinct "
  "allergens; `shellfish species` (798) spans both and is the wrong grain if the "
  "user means molluscs specifically.",
  aliases=("mollusc", "molluscs", "mollusk", "shellfish (mollusc)")))

entries.update(E("paprika", ["paprika (ground)", "paprika puree"], "medium",
  "Both paprika forms FoodOn models, each a leaf (closure 1). Correct but small: "
  "paprika is an endpoint, so an avoidance query returns little. Its value in this "
  "project is as the target of a nightshade query, which now reaches it via the "
  "repaired `hungarian wax pepper food product -> hungarian wax pepper plant` edge."))

entries.update(E("edamame", ["edamame"], "high",
  "Genuine leaf, closure 1 - confirmed rather than corrected. Flagged for review "
  "only because low closure is indistinguishable from a stub category without "
  "human judgement.",
  note="a soy query reaches edamame; the reverse does not hold, by the no-ascent invariant"))

entries.update(E("sulphites", ["sulfites"], "medium",
  "FoodOn models sulphites only as ChEBI chemical classes: `sulfites` -> "
  "`sulfite salt` -> `sodium sulfite`, closure 2 as a root. There is no derivative "
  "structure to traverse because sulphites are added, not derived.",
  note="an honest low-yield resolution. The avoidance answer for sulphites is "
       "label-based, not ontology-based, and the UI should say so rather than "
       "implying the two-node graph is the whole picture.",
  aliases=("sulfites", "sulphite", "sulfite", "sulphur dioxide", "sulfur dioxide")))

entries.update(E("mammalian meat", ["mammal"], "high",
  "Alpha-gal syndrome is a reaction to galactose-alpha-1,3-galactose, present in "
  "non-primate mammalian tissue. `mammal` is the correct root; there is no "
  "alpha-gal class in FoodOn and there could not usefully be one, since the "
  "carbohydrate is a property of the tissue rather than a separate ingredient.",
  aliases=("alpha-gal", "alpha gal", "mammalian meat (alpha-gal)", "red meat")))

out = {"version": "1.0.0",
       "resolver_version": "1.0.0",
       "ontology_version": g.meta["version"],
       "note": "Only terms the deterministic stage could not settle. Terms absent here "
               "are resolved live by build/resolve.py on lexical + structural evidence.",
       "entries": entries}
json.dump(out, open("data/resolution-store.json", "w"), indent=2)
multi = sum(1 for e in entries.values() if len(e["roots"]) > 1)
print(f"{len(entries)} store entries ({len(set(tuple(e['root_labels']) for e in entries.values()))} distinct resolutions)")
print(f"multi-root entries: {multi}")
for q, e in sorted(entries.items()):
    print(f"   {q:<24} -> {', '.join(e['root_labels'])}")

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

def E(query, labels, confidence, rationale, note=None, aliases=(),
      by="Claude (offline pass)", date="2026-09-09"):
    """One decision, plus the surface forms that share it.

    `by` and `date` carry who signed the entry off and when. They default to the
    original offline pass; entries Matt reviewed individually say so, because the
    two are not the same kind of claim and the store is an audit record.
    """
    return {q: {"query": q, "status": "resolved", "method": "offline-review",
                "roots": [L(x) for x in labels], "root_labels": list(labels),
                "confidence": confidence, "rationale": rationale, "note": note,
                "reviewed_by": by, "reviewed_date": date,
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

entries.update(E("egg", ["egg or egg component", "chicken egg", "animal egg"], "high",
  "Lexically ambiguous between `chicken egg` (closure 291) and `egg food product` "
  "(72). Resolved to three classes that cover different fractions of the same "
  "allergen and none of which subsumes another: `egg or egg component` (yolk and "
  "white), `chicken egg`, and `animal egg`. The third was added 2026-09-10 after "
  "the unionOf extraction fix: `animal egg` had been reachable only through the "
  "inverted edge `animal egg is_a shelled egg`, and once that was corrected the "
  "query lost `quail egg`, `goose egg`, `ostrich egg` and `animal roe` -- a false "
  "negative on a FALCPA top-9 allergen. Egg allergy is to the egg proteins, which "
  "every bird egg carries, so the species-spanning class belongs in the roots. The "
  "12 UBERON embryology classes that also sit under `animal egg` are excluded by "
  "config/relation_policy.json rather than by narrowing this root.",
  note="multi-root by design: the two classes cover different fractions of the same allergen",
  by="Matt", date="2026-09-10"))

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

# ---------------------------------------------------------------------------
# Terms with no base class upstream. FoodOn models the preparation variants and
# not the thing itself, so no scoring rule could ever reach a usable root: the
# resolver was ranking `wine (dealcoholized)` against `wine (canned)` and calling
# the result ambiguous, which it was. A data gap, not a tuning failure.
# ---------------------------------------------------------------------------

entries.update(E("wine", ["wine or wine-like food product"], "high",
  "FoodOn has no class labelled `wine`, only preparation variants -- "
  "`wine (dealcoholized)`, `wine (canned)`, `wine (homemade)` -- so the lexical "
  "resolver ranked those and returned `ambiguous` with nothing usable. Pinned to "
  "`wine or wine-like food product` (106 classes) rather than `grape wine` (55): "
  "the broader class carries fruit wine as well as the grape varietals, and someone "
  "avoiding wine is avoiding all of it. Verified to cover Bordeaux, Burgundy, "
  "Chardonnay, Chianti and fruit wine.",
  note="no base class exists upstream; this is a data gap, not a scoring failure",
  by="Matt", date="2026-09-10"))

entries.update(E("beer", ["beer beverage"], "high",
  "Same shape as wine: no `beer` class, only variants like `beer (draft)` and "
  "`beer (freeze-concentrated)`. `beer beverage` is the general class, 17 classes, "
  "and covers ale, pale ale, India pale ale, porter, brown beer and barley malt "
  "beer. Gluten-relevant, since barley malt beer sits inside it.",
  note="no base class exists upstream; this is a data gap, not a scoring failure",
  by="Matt", date="2026-09-10"))

entries.update(E("beef", ["bovine meat food product"], "high",
  "No `beef` or `beef food product` class exists; the resolver was ranking "
  "`beef (ground)`, `beef (cooked)` and `beef (chopped)`. Pinned to `bovine meat "
  "food product`, which reaches beef steak, ground beef patty, beef jerky, beef "
  "broth, beef liver and corned beef. The meat-cut classes were considered instead "
  "-- `piece of beef` (320) and `butchery cut of beef` (286) are dairy-clean -- and "
  "rejected because they miss all of the processed beef: jerky, broth, patties and "
  "organs. Recall-first, with the dairy over-reach removed by a signed `remove` "
  "override rather than by narrowing the root.",
  note="this root pivots through `cow food product --in taxon--> Bos taurus` and so "
       "reaches cow milk and cheese; see the `remove` override in "
       "config/overrides.json, which takes the closure from 1,555 to 785 and dairy "
       "from 677 classes to 25",
  by="Matt", date="2026-09-10"))

# ---------------------------------------------------------------------------
# Culinary vocabulary. These nine came out of a blind comparison between a
# query-time LLM and the deterministic resolver over 40 diner phrasings: they are
# the terms the LLM got right and the resolver did not. Every one is a stable
# vocabulary fact -- mangetout does not stop meaning snow pea between queries --
# which is exactly the kind of thing that belongs pinned once rather than inferred
# on every request. The same comparison is why the LLM stays offline: its two
# worst answers were `gluten` (wheat only, missing four grains) and `white fish`
# (all 3,173 fish), both of which would have overridden a signed decision.
# ---------------------------------------------------------------------------

entries.update(E("mangetout", ["snow pea plant"], "high",
  "'mangetout' appears on no FoodOn label or synonym. It is the British and French "
  "culinary name for the snow pea -- the flat, immature edible pod of Lathyrus "
  "oleraceus (formerly Pisum sativum) var. macrocarpon. `snow pea plant` (closure "
  "11) is the source-form class, and its descent already contains `snow pea pod "
  "(edible, fresh)`, so pinning the plant covers the food form too.",
  note="the closure also carries `sugar snap pea plant` and `field pea`, which sit "
       "in the same FoodOn cultivar cluster. Broader than mangetout strictly is, but "
       "every member is the same species, so nothing false is claimed.",
  aliases=("mange tout", "mange-tout"), by="Matt", date="2026-09-10"))

entries.update(E("cilantro", ["coriander", "coriander plant"], "high",
  "The only pin here that overrides a resolution the deterministic stage already "
  "makes. `cilantro` reached `Coriandrum sativum` (closure 8) -- the organism, "
  "correct but thin. The query 'coriander' resolves to `coriander` + `coriander "
  "plant` (closure 14), which additionally carries the leaf forms (raw, dried, "
  "whole), `coriander food product`, `curry powder` and `pickling spice`. The "
  "8-node closure is a strict subset of the 14, verified, so this loses nothing. "
  "Cilantro and coriander are the same plant under two names and should return the "
  "same graph.",
  note="`coriander` itself is deliberately NOT pinned: it resolves correctly without "
       "help and should keep tracking the ontology.",
  by="Matt", date="2026-09-10"))

entries.update(E("creme fraiche", ["cream (cultured)"], "medium",
  "FoodOn models creme fraiche only as an EFSA FoodEx2 code-list entry, `27170 - "
  "creme fraiche and other mild variants of sour cream`, which sits in an excluded "
  "branch and cannot be a root. The nearest real class is `cream (cultured)`, which "
  "is what creme fraiche is: cream soured with a mesophilic culture. A leaf "
  "(closure 1), so the graph is small and honest rather than large and wrong.",
  note="the broad alternative is `cream food product` (closure 61 -- clotted cream, "
       "whipped cream, coffee creamer, ranch dressing). Rejected as over-inclusion: "
       "cream is not the allergen, milk is, and a diner with a dairy problem should "
       "say 'dairy' or 'milk', both of which already resolve.",
  aliases=("cr\u00e8me fra\u00eeche", "cr\u00e8me fraiche", "creme fra\u00eeche"),
  by="Matt", date="2026-09-10"))

entries.update(E("double cream", ["heavy cream"], "high",
  "'double cream' appears on no FoodOn label. `heavy cream` is the same product "
  "under the US name -- both are the >=36% butterfat pouring cream -- and it is a "
  "real FoodOn class that the query 'heavy cream' already resolves to. A leaf "
  "(closure 1).",
  note="same breadth trade-off as creme fraiche: `cream food product` (61) was "
       "available and rejected for the same reason.",
  by="Matt", date="2026-09-10"))

entries.update(E("greek yoghurt", ["greek yogurt"], "high",
  "A spelling gap, nothing more: FoodOn has `greek yogurt` and the query 'greek "
  "yogurt' resolves to it. The British spelling fails only because the compound has "
  "no match, even though 'yoghurt' alone already resolves through the GS1 and EFSA "
  "synonyms. A leaf (closure 1) -- greek yogurt is an endpoint in FoodOn, with "
  "nothing modelled as derived from it.",
  note="low-yield by nature. Someone avoiding greek yoghurt for a dairy reason wants "
       "'dairy' or 'milk'; this pin answers the literal question.",
  by="Matt", date="2026-09-10"))

entries.update(E("chilli flakes", ["chili pepper"], "high",
  "Two gaps at once: the British 'chilli' spelling and the '... flakes' form. "
  "FoodOn models no flake form of chili, so the pin goes to the ingredient itself. "
  "`chili pepper` (closure 160) is what the queries 'chili', 'chili pepper' and "
  "'chilli pepper' all already resolve to, so this makes the flake phrasing agree "
  "with them.",
  note="the closure is the Capsicum cultivar set, which includes sweet bell peppers. "
       "That is FoodOn's own structure, not a claim that bell pepper is a chilli.",
  aliases=("chili flakes",), by="Matt", date="2026-09-10"))

entries.update(E("smoked paprika", ["paprika (ground)", "paprika puree"], "medium",
  "FoodOn models no smoked, sweet or hot paprika -- only the two forms already "
  "pinned for the bare query 'paprika'. This pin makes the qualified phrasing agree "
  "with the unqualified one rather than returning nothing. Both roots are leaves "
  "(closure 2 together).",
  note="deliberately identical to the `paprika` pin. Its value in this project is as "
       "the TARGET of a nightshade or pepper query, which reaches it through the "
       "repaired `hungarian wax pepper food product -> hungarian wax pepper plant` "
       "edge, not as a root.",
  by="Matt", date="2026-09-10"))

entries.update(E("san marzano tomatoes",
  ["tomato plant", "tomato", "tomato food product"], "high",
  "San Marzano is a plum tomato cultivar FoodOn does not model, though it models "
  "many others (Beefsteak, Carbon, Damsel, Roma). The three roots are exactly what "
  "the query 'tomato' resolves to after the facet merge, closure 164. Adding "
  "`Solanum lycopersicum` as a fourth root was tested and changes nothing: root "
  "expansion pairs the plant with its NCBITaxon species automatically.",
  note="a cultivar-name pin. If FoodOn later adds a San Marzano class this entry "
       "becomes wrong in the direction of too broad, which is what "
       "build/check_upstream_fixes.py is for.",
  aliases=("san marzano tomato", "san marzano"), by="Matt", date="2026-09-10"))

entries.update(E("prawns", ["shrimp"], "high",
  "'prawn' and 'shrimp' are the same animals under British and American names. "
  "FoodOn commits to `shrimp` as the class name while scattering 'prawn' across "
  "species labels (`Indian prawn`, `western king prawn`, `caramote prawn`). The "
  "bare query came back ambiguous because those species labels compete with the "
  "EFSA code-list entries; `shrimp` (closure 214) is the grain that covers them "
  "all.",
  note="NOT pinned to `crustacean` (closure 731). A clinical crustacean allergy is "
       "usually broader than prawn -- crab and lobster too -- but that is a "
       "different question from the one the diner asked, and 'shellfish "
       "(crustacean)' already resolves for when they mean it.",
  aliases=("prawn",), by="Matt", date="2026-09-10"))

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

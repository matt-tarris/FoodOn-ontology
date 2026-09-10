#!/usr/bin/env python3
"""Generate test/allergen-golden.json from the supplied allergen derivative list,
restructured by RELATION TYPE.

The source list conflates four relations that need different machinery, and scoring
them together produces meaningless numbers -- a synonym can never be a traversal hit,
and a provenance term never *should* be:

  containment       real derivation. The only group traversal is judged on.
  synonym           the same substance under another name. A resolution-store
                    concern (spec 2a), not a traversal target.
  provenance        "usually made from, but not necessarily". Feedstock is a
                    manufacturer's choice, not a property of the substance, so no
                    ontology will ever assert it. Belongs in overrides.json carrying
                    a weaker claim: may contain, not contains.
  cross_reactivity  immunologically related, but the allergen is not present.
  disputed          circulates on avoidance lists without a containment basis.

For traversal, provenance / cross_reactivity / disputed are NEGATIVE tests: reaching
them through ontology structure alone would be a false containment claim.
"""
import json

C, S, P, X, D = "containment", "synonym", "provenance", "cross_reactivity", "disputed"

DATA = {
 "Corn": (["Maize plant"], [
   ("maltodextrin", P, "starch hydrolysate; corn, wheat, potato or tapioca depending on plant"),
   ("dextrose", P, "glucose; corn-derived in the US, other feedstocks elsewhere"),
   ("high fructose corn syrup", C, "corn named in the substance itself"),
   ("corn starch", C, "direct corn derivative"),
   ("modified food starch", P, "any starch source; unspecified by name"),
   ("citric acid", P, "Aspergillus niger fermentation on a sugar feedstock, often corn"),
   ("xanthan gum", P, "Xanthomonas fermentation, feedstock often corn glucose"),
   ("dextrin", P, "starch hydrolysate, feedstock varies"),
   ("cyclodextrin", P, "enzymatic conversion of starch, feedstock varies"),
   ("zein", C, "zein is the corn prolamin by definition"),
   ("ascorbic acid", P, "synthesised from glucose, feedstock often corn"),
   ("erythritol", P, "fermentation of corn or wheat starch hydrolysate"),
   ("sorbitol", P, "hydrogenated glucose, feedstock often corn"),
   ("calcium citrate", P, "citric acid salt, inherits the citric acid feedstock question"),
 ]),
 "Milk": (["dairy cow", "milk"], [
   ("casein", C, "the predominant milk protein"),
   ("caseinates", C, "casein salts"),
   ("sodium caseinate", C, "casein salt"),
   ("calcium caseinate", C, "casein salt"),
   ("potassium caseinate", C, "casein salt"),
   ("whey protein hydrolysate", C, "milk whey fraction"),
   ("whey protein concentrate", C, "milk whey fraction"),
   ("lactalbumin", C, "milk whey protein"),
   ("lactoglobulin", C, "milk whey protein"),
   ("nisin", P, "Lactococcus lactis bacteriocin, commonly cultured on a dairy medium"),
   ("lactic acid starter culture", P, "may be propagated on a dairy medium"),
   ("butterfat", C, "milk fat"),
   ("ghee", C, "clarified butterfat"),
 ]),
 "Egg": (["egg or egg component", "chicken"], [
   ("lysozyme", C, "food-grade lysozyme is hen egg white lysozyme"),
   ("E1105", S, "E-number for lysozyme; the same substance, not a second one"),
   ("egg albumen", C, "egg white"),
   ("ovalbumin", C, "principal egg white protein"),
   ("ovomucoid", C, "egg white protein"),
   ("ovotransferrin", C, "egg white protein"),
   ("dried egg white solids", C, "dehydrated egg white"),
   ("meringue powder", C, "dried egg white plus sugar"),
 ]),
 "Fish": (["fish species"], [
   ("isinglass", C, "collagen from fish swim bladders"),
   ("fish collagen", C, "named derivative"),
   ("fish gelatin", C, "hydrolysed fish collagen"),
   ("anchovy paste", C, "anchovy derivative"),
   ("anchovy extract", C, "anchovy derivative"),
   ("surimi", C, "washed fish mince"),
   ("fish sauce", C, "fermented fish"),
 ]),
 "Shellfish": (["shellfish species"], [
   ("chitosan", P, "deacetylated chitin; crustacean shells OR fungal mycelium"),
   ("crustacean chitin", C, "named crustacean derivative"),
   ("cuttlefish ink", C, "cephalopod; molluscan shellfish, distinct from crustacean"),
   ("squid ink", C, "cephalopod; molluscan shellfish, distinct from crustacean"),
   ("seafood bouillon base", C, "shellfish-containing stock base"),
   ("shrimp paste", C, "fermented shrimp"),
 ]),
 "Tree Nuts": (["nut producing plant"], [
   ("pink peppercorn", X, "Schinus in Anacardiaceae with cashew and pistachio; cross-reactive, contains no tree nut"),
   ("Schinus terebinthifolius", S, "the source species of pink peppercorn, not a separate item"),
   ("mahlab", X, "Prunus mahaleb kernel; a stone-fruit kernel, cross-reactive rather than a tree nut"),
   ("mahlepi", S, "alternate spelling of mahlab"),
   ("marzipan", C, "almond paste and sugar"),
   ("gianduja", C, "hazelnut and chocolate"),
   ("praline", C, "nut and caramelised sugar"),
   ("nut meal", C, "ground nut"),
   ("almond paste", C, "ground almond"),
 ]),
 "Peanut": (["peanut plant"], [
   ("arachis oil", S, "Arachis hypogaea oil; another name for peanut oil"),
   ("peanut flour", C, "milled peanut"),
   ("peanut meal", C, "milled peanut"),
   ("mandelonas", C, "peanuts flavoured and sold as almonds"),
   ("beer nuts", C, "coated peanuts"),
 ]),
 "Wheat": (["wheat plant"], [
   ("wheat glucose syrup", C, "wheat starch hydrolysate"),
   ("wheat maltodextrin", C, "wheat starch hydrolysate"),
   ("hydrolyzed wheat protein", C, "named wheat derivative"),
   ("seitan", C, "wheat gluten"),
   ("triticale", C, "wheat x rye hybrid; belongs under rye as well as wheat"),
   ("spelt", C, "Triticum spelta"),
   ("farro", S, "culinary name covering emmer, spelt and einkorn"),
   ("semolina", C, "coarse durum wheat milling fraction"),
   ("bulgur", C, "parboiled cracked wheat"),
   ("kamut", C, "Triticum turanicum, trademarked as Kamut"),
   ("modified wheat starch", C, "wheat starch derivative"),
 ]),
 "Mammalian Meat (Alpha-Gal)": (["mammal"], [
   ("bovine gelatin", C, "hydrolysed bovine collagen"),
   ("porcine gelatin", C, "hydrolysed porcine collagen"),
   ("animal rennet", C, "enzyme from ruminant abomasum"),
   ("carrageenan", D, "red seaweed polysaccharide, contains no mammalian material or alpha-gal; appears on alpha-gal lists via a contested GI-symptom hypothesis"),
   ("bovine tallow", C, "rendered bovine fat"),
   ("lard", C, "rendered porcine fat"),
 ]),
 "Sesame": (["sesame plant"], [
   ("benne", S, "another name for sesame"),
   ("benne seed", S, "another name for sesame seed"),
   ("gingelly oil", S, "another name for sesame oil"),
   ("tahini", C, "ground hulled sesame"),
   ("til", S, "another name for sesame"),
   ("teel", S, "another name for sesame"),
   ("gomasio", C, "sesame and salt condiment"),
 ]),
 "Mustard": (["mustard plant"], [
   ("mustard flour", C, "milled mustard seed"),
   ("mustard meal", C, "milled mustard seed"),
   ("mustard seed oleoresin", C, "mustard seed extract"),
   ("Brassica alba", S, "synonym of Sinapis alba, white mustard"),
   ("Brassica juncea", C, "brown mustard; a sibling source species within the class query"),
   ("Sinapis alba", S, "white mustard; the accepted name for Brassica alba"),
 ]),
 "Soy": (["soybean plant"], [
   ("textured vegetable protein", P, "usually soy, but the name does not commit to a source"),
   ("textured soy flour", C, "named soy derivative"),
   ("hydrolyzed plant protein", P, "soy, wheat or corn depending on producer"),
   ("hydrolyzed vegetable protein", P, "soy, wheat or corn depending on producer"),
   ("soy lecithin", C, "soybean phospholipid fraction"),
   ("edamame", C, "immature soybean"),
   ("shoyu", C, "fermented soy sauce"),
   ("tamari", C, "fermented soy sauce, little or no wheat"),
   ("miso", C, "fermented soybean paste"),
   ("natto", C, "fermented soybean"),
   ("tempeh", C, "fermented soybean cake"),
 ]),
}

out = {
  "version": "2026-09-09",
  "source": "supplied allergen derivative list, 2026-09-09",
  "generated_by": "build/make_allergen_golden.py",
  "relation_types": {
    "containment":      "real derivation. Traversal MUST reach it.",
    "synonym":          "same substance, another name. Resolution-store concern (2a), not a traversal target.",
    "provenance":       "usually made from, but not necessarily. Never assertable by an ontology; overrides.json, weaker claim.",
    "cross_reactivity": "immunologically related; the allergen is NOT present. Traversal must NOT assert containment.",
    "disputed":         "on avoidance lists without a containment basis."
  },
  "allergens": [
    {"common": k, "roots": v[0],
     "terms": [{"term": t, "relation": r, "note": n} for t, r, n in v[1]]}
    for k, v in DATA.items()
  ],
}
json.dump(out, open("test/allergen-golden.json", "w"), indent=2)
import collections
c = collections.Counter(t["relation"] for a in out["allergens"] for t in a["terms"])
print(f"{sum(c.values())} terms across {len(out['allergens'])} allergens")
for k, v in c.most_common(): print(f"   {k:<18} {v}")

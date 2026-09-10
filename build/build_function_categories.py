#!/usr/bin/env python3
"""Map FoodOn's US CFR rollup vocabulary onto readable grouping categories.

Two tiers, because the source vocabulary has two axes in it:

  ingredient_function  the six categories from the supplied taxonomy. These describe
                       what an ingredient DOES (emulsify, thicken, sweeten). Only
                       about ten CFR groups are of this kind, but they are the ones
                       an allergen-avoider cares about most.
  product_type         everything else. `cake`, `soup, thin`, `natural cheese` are
                       finished foods, not roles. Mapping them into a functional
                       category would be a category error, but they group a large
                       graph usefully, so they get their own tier.

Coverage was the reason for this design: the supplied derivative lists alone tag 77
of 39,894 classes and zero nodes on four of seven test queries, because they name
precisely the processed ingredients FoodOn models worst. The CFR vocabulary reaches
2,342 classes.

LOAD BEARING despite no textual reference anywhere in the project: this is the
only way to regenerate config/function-categories.json, which build/traverse.py
reads at load time. Run it after a FoodOn release changes the CFR vocabulary.
"""
import json, sys, collections, re
sys.path.insert(0, "build")
from resolve import Resolver

CATEGORIES = {
  # --- the six supplied categories -------------------------------------------
  "emulsifiers_binders":      ("Emulsifiers & Binders", "ingredient_function"),
  "thickeners_gelling":       ("Thickeners, Stabilizers & Gelling Agents", "ingredient_function"),
  "sweeteners_bulking":       ("Sweeteners & Bulking Syrups", "ingredient_function"),
  "preservatives_acidulants": ("Preservatives, Acidulants & Fermentation Aids", "ingredient_function"),
  "clarifying_agents":        ("Clarifying Agents", "ingredient_function"),
  "flavor_enhancers":         ("Flavor Enhancers, Bases & Seasonings", "ingredient_function"),
  # --- product-type tier, for the rest of the CFR vocabulary ------------------
  "bakery":      ("Bakery & Grain Products", "product_type"),
  "confection":  ("Confectionery & Chocolate", "product_type"),
  "dairy":       ("Dairy & Cheese", "product_type"),
  "beverage":    ("Beverages", "product_type"),
  "alcohol":     ("Alcoholic Beverages", "product_type"),
  "meat_seafood":("Meat, Poultry & Seafood", "product_type"),
  "sauce_soup":  ("Sauces, Soups & Dressings", "product_type"),
  "fruit_veg":   ("Fruit & Vegetable Products", "product_type"),
  "dessert":     ("Desserts & Frozen", "product_type"),
  "prepared":    ("Prepared & Composite Foods", "product_type"),
  "analog":      ("Substitute & Analog Products", "product_type"),
  "eggs":        ("Eggs & Egg Products", "product_type"),
  "fats_oils":   ("Fats & Oils", "product_type"),
}

# Ordered rules over the CFR group label. First match wins, so the functional
# categories are tested before the product-type ones.
RULES = [
  # ingredient function
  (r"sweetener",                                   "sweeteners_bulking"),
  (r"^flavoring|flavoring or seasoning|spice or herb", "flavor_enhancers"),
  (r"food additive|color additive",                "preservatives_acidulants"),
  (r"vinegar",                                     "preservatives_acidulants"),
  (r"starch product|pudding, starch",              "thickeners_gelling"),
  (r"gelatin dessert",                             "thickeners_gelling"),
  # analogs first: `cheese product analog` is a substitute, not cheese
  (r"analog",                                      "analog"),
  # product type
  (r"^egg or egg|^prepared egg",                   "eggs"),
  (r"margarine|^fat|oil$",                         "fats_oils"),
  (r"cheese|milk|cream|butter product|cultured milk|yogurt|custard", "dairy"),
  (r"candy|confection|chocolate|cacao|fudge|brittle|fondant|chewing gum|caramel|glaze|icing", "confection"),
  (r"cake|cookie|cracker|doughnut|pastry|pie|bread|bakery|pancake|waffle|sweet roll|pizza|macaroni|noodle|breakfast cereal|grain", "bakery"),
  (r"ice cream|sherbet|frozen|dessert|water ice|mellorine", "dessert"),
  (r"wine|beer|malt beverage|spirits|liqueur|alcohol", "alcohol"),
  (r"beverage|soft drink|juice|nectar|steeped",    "beverage"),
  (r"meat|poultry|seafood|sausage|reptile",        "meat_seafood"),
  (r"soup|sauce|gravy|dressing|condiment|relish|salad|topping", "sauce_soup"),
  (r"fruit|vegetable|jelly|jam|preserve|pickle|seed or seed|nut or nut", "fruit_veg"),
  (r"prepared|meal|sandwich|stew|hash|snack|salt|formulation|supplemental|dietary|decoration|refined|dish", "prepared"),
]

r = Resolver(); g = r.g
groups = collections.Counter()
for _n, lst in g.rollup.items():
    for grp in lst:
        groups[g.label(grp)] += 1

mapping, unmapped = {}, []
for label, n in sorted(groups.items()):
    low = label.lower()
    hit = next((cat for pat, cat in RULES if re.search(pat, low)), None)
    if hit: mapping[label] = hit
    else: unmapped.append(label)

out = {
  "version": "2026-09-09",
  "status": "DRAFT - requires sign-off",
  "source": "supplied six-category culinary-function taxonomy, extended with a "
            "product-type tier for the CFR groups that are finished foods rather "
            "than ingredient roles",
  "categories": {k: {"label": v[0], "kind": v[1]} for k, v in CATEGORIES.items()},
  "mapping": mapping,
  "unmapped": unmapped,
}
json.dump(out, open("config/function-categories.json", "w"), indent=2)

by_cat = collections.Counter()
for lab, cat in mapping.items(): by_cat[cat] += groups[lab]
print(f"{len(groups)} CFR groups -> {len(mapping)} mapped, {len(unmapped)} unmapped\n")
print(f"{'category':<46} {'kind':<20} {'classes':>8}")
print("-" * 78)
for k, (lab, kind) in CATEGORIES.items():
    if by_cat[k]: print(f"{lab:<46} {kind:<20} {by_cat[k]:>8}")
if unmapped: print("\nunmapped:", ", ".join(unmapped))

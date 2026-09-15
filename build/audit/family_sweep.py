#!/usr/bin/env python3
"""Does any ingredient land in an avoidance family it does not belong to, or miss one it does?

    python3 build/audit/family_sweep.py path/to/recipes.json

Two sweeps, and the second is the one that matters.

  LANDS IN      the term names nothing about this family, yet the mapping reaches it.
                Found `pepper -> Capsicum`, which put black pepper in the nightshade
                family and cost a nightshade-avoiding diner 28% of the menu; and
                `panko -> breadcrumbs -> POULTRY`, which turned out to be an extraction
                bug -- a union nested inside an intersection made a chicken dish the
                parent of every baked food.

  MISSES        the term names the family and the mapping does not reach it. This is
                the dangerous direction: a false positive costs a diner choice, a false
                negative costs them a reaction. It found a gluten query rejecting 312 of
                5,000 recipes while missing 988 that named a grain, because `flour`,
                `bread`, `breadcrumbs` and `cracker` pointed at FoodOn's generic classes
                -- which carry no grain, correctly, since bread can be made from any.

Both sweeps produce noise: `sweet potato` is not a nightshade and `coconut milk` is not
dairy, whatever the words suggest. The output is a list to read, not a list to apply.
"""
import json, sys, ast, re, collections, os

os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, "build")
from resolve import Resolver
from ingest import Ingestor, normalise, strip_qualifiers

corpus = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
TOP = int(sys.argv[2]) if len(sys.argv) > 2 else 2000

FAMILIES = ["nightshade", "dairy", "gluten", "tree nut", "peanut", "shellfish", "mollusc",
            "egg", "soy", "allium", "fish", "sesame", "mustard", "celery", "red meat",
            "poultry", "alpha-gal", "citrus", "corn"]
# words a diner would take as naming the family. Deliberately generous: a false flag
# costs a glance and a missing one costs the whole point of the sweep.
CUE = {
 "dairy": "cheese milk cream butter yogurt yoghurt ricotta mozzarella parmesan mascarpone ghee buttermilk kefir",
 "egg": "egg mayonnaise aioli meringue custard",
 "gluten": "flour bread pasta noodle panko crumb cracker pastry wheat barley rye couscous farro semolina spelt bulgur",
 "tree nut": "almond walnut pecan hazelnut pistachio cashew macadamia",
 "peanut": "peanut", "soy": "soy tofu miso tempeh edamame tamari",
 "fish": "anchovy anchovies salmon tuna cod trout bonito sardine",
 "shellfish": "shrimp prawn crab lobster",
 "mollusc": "clam mussel oyster squid octopus scallop",
 "sesame": "sesame tahini",
 "nightshade": "tomato potato chile chili paprika eggplant aubergine",
 "allium": "onion garlic shallot leek chive scallion",
 "citrus": "lemon lime orange grapefruit citrus",
}
# words that LOOK like a cue and are not the food: the reason the sweep needs reading
EXEMPT = {"sweet potato", "coconut milk", "almond milk", "almond butter", "peanut butter",
          "butternut", "cream tartar", "buckwheat", "rice flour", "rice noodle",
          "chickpea flour", "coconut", "eggplant", "black pepper", "white pepper",
          "peppercorn", "sichuan pepper", "milk chocolate", "cocoa butter", "shea butter"}

r = Resolver(); g = r.g
clos = {}
for f in FAMILIES:
    res = r.resolve(f)
    if res["status"] == "resolved":
        clos[f] = set(g.closure(res["roots"])[0])

I = Ingestor()
recs = json.load(open(corpus))
uses, first = collections.Counter(), {}
for rec in recs:
    for ing in rec.get("ingredients") or []:
        v = ing.get("name")
        p = ast.literal_eval(v) if isinstance(v, str) and v.startswith("[") else [v]
        for l in p:
            t = strip_qualifiers(normalise(str(l)))
            if t:
                uses[t] += 1
                first.setdefault(t, str(l).strip())

STEM = lambda w: w[:-1] if len(w) > 3 and w.endswith("s") else w
lands, misses = [], []
for t, n in uses.most_common(TOP):
    gl = I.line(first[t])
    if gl["status"] != "resolved":
        continue
    if any(e in t for e in EXEMPT):
        continue
    tw = {STEM(w) for w in re.findall(r"[a-z]+", t)}
    lw = {STEM(w) for w in re.findall(r"[a-z]+", " ".join(gl["root_labels"]).lower())}
    label = gl["root_labels"][0] if gl["root_labels"] else "?"
    for fam, c in clos.items():
        inside = any(i in c for i in gl["roots"])
        fw = {STEM(w) for w in re.findall(r"[a-z]+", fam)}
        if inside and not (tw & fw or tw & lw):
            lands.append((n, t, label, fam))
        if not inside and fam in CUE:
            if any(re.search(r"\b" + c + r"\w*", t) for c in CUE[fam].split()):
                misses.append((n, t, label, fam))

def show(rows, title, note):
    rows.sort(reverse=True)
    print(f"\n{title}  ({len(rows)})")
    print(f"  {note}")
    print(f"  {'uses':>5}  {'ingredient term':<26} {'mapped to':<26} {'family':<12}")
    print("  " + "-" * 74)
    for n, t, lab, fam in rows[:25]:
        print(f"  {n:>5}  {t[:25]:<26} {lab[:25]:<26} {fam:<12}")

print(f"{len(clos)} families over {len(uses):,} distinct terms from "
      f"{os.path.basename(corpus)}")
show(lands, "LANDS IN a family its name does not suggest",
     "false positives: a diner loses food they could eat")
show(misses, "MISSES a family its name does suggest",
     "false negatives: a diner is served food they cannot eat")

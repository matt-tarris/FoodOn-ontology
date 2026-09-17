#!/usr/bin/env python3
"""The oracle must not overstate what it found.

validate_corpus compares our avoidance verdict against a corpus that labels its own
allergens, and the whole value of that depends on one rule: a disagreement counts as a
traversal defect ONLY when every ingredient in the item resolved. If one did not, the
miss is explained by the coverage gap already documented in the README, and calling it
a traversal failure would invent a bug we do not have -- while calling it nothing would
hide the gap.

So this suite pins the classification, and pins it on a fixture written here rather
than on fetched data. Open Food Facts is ODbL, and a share-alike obligation on a corpus
committed to a repository with no licence chosen is not a thing to acquire by accident.
The two live sources are exercised by running the harness, not by the test suite.
"""
import sys, os
sys.path.insert(0, "build")
sys.path.insert(0, os.path.join("build"))
from validate_corpus import verdict, split_label, ALLERGENS
from resolve import Resolver

fails, checks = [], 0


def ck(cond, msg):
    global checks
    checks += 1
    if not cond:
        fails.append(msg)


# ---- the classification rule -------------------------------------------------
# A toy closure: three allergens, each a set of one fake IRI. The rule under test is
# about completeness and set intersection, not about the ontology.
CLO = {"en:milk": {"IRI:milk"}, "en:gluten": {"IRI:wheat"}, "en:peanuts": {"IRI:peanut"}}

v = verdict({"IRI:milk"}, True, {"en:milk"}, CLO)
ck(v["en:milk"] == "agree", "declared and reached should be agree")
ck("en:gluten" not in v, "an allergen neither declared nor reached should not be scored")

v = verdict(set(), True, {"en:milk"}, CLO)
ck(v["en:milk"] == "miss_real",
   "declared, not reached, everything resolved -> a real miss")

v = verdict(set(), False, {"en:milk"}, CLO)
ck(v["en:milk"] == "miss_explained",
   "declared, not reached, something unresolved -> explained, NOT a defect")

# the distinction that matters most: the same evidence, one bit apart
ck(verdict(set(), True, {"en:milk"}, CLO)["en:milk"]
   != verdict(set(), False, {"en:milk"}, CLO)["en:milk"],
   "completeness must change the verdict; without it every coverage gap reads as a bug")

v = verdict({"IRI:peanut"}, True, set(), CLO)
ck(v["en:peanuts"] == "over", "reached but not declared -> over, a lead not a defect")

v = verdict({"IRI:milk", "IRI:wheat"}, True, {"en:milk"}, CLO)
ck(v["en:milk"] == "agree" and v["en:gluten"] == "over",
   "each allergen is scored independently within one item")

# an incomplete item that we DO reach is still an agreement: the unresolved line cannot
# retract an allergen we positively found
ck(verdict({"IRI:milk"}, False, {"en:milk"}, CLO)["en:milk"] == "agree",
   "an unresolved line must not downgrade a positive finding")

# ---- label splitting ---------------------------------------------------------
parts = split_label("INGREDIENTS: CHOCOLATE (SUGAR, COCOA BUTTER, MILK), SALT")
low = [p.lower() for p in parts]
ck("milk" in low, "a sub-ingredient in brackets must be split out on its own -- the "
                  "parent name is exactly what hides it")
ck("chocolate" in low, "the parent ingredient must survive the split")
ck(not any("ingredients" in p for p in low), "the INGREDIENTS: header is not an item")

parts = split_label("Water, Sugar. Contains: Milk")
ck("milk" in [p.lower() for p in parts], "a Contains: clause carries real allergens")

ck(split_label("") == [], "an empty label yields nothing, not one empty item")
ck(all(1 < len(p) <= 60 for p in split_label("a, bb, " + "x" * 80)),
   "single characters and runaway fragments are not ingredient names")

# ---- the allergen terms still resolve ----------------------------------------
# The oracle silently degrades if a term stops resolving: every item would score as
# agreement-by-absence. The harness reports that, and this fails on it.
R = Resolver()
for tag, term in ALLERGENS.items():
    r = R.resolve(term)
    ck(r.get("status") == "resolved" and r.get("roots"),
       f"oracle allergen {tag} -> '{term}' no longer resolves; the comparison for it "
       f"would be silently vacuous")

# and the closures must be non-trivial -- a term that resolves to itself alone would
# also score as agreement-by-absence for everything derived from it
G = R.g
thin = []
for tag, term in ALLERGENS.items():
    r = R.resolve(term)
    if r.get("status") == "resolved" and r.get("roots"):
        n = len(G.closure(r["roots"])[0])
        if n < 5:
            thin.append(f"{tag} ({term}) reaches only {n}")
checks += 1
if thin:
    print(f"  note: thin closures, the oracle can say little about these: {'; '.join(thin)}")

# ---- end to end, through the real graph --------------------------------------
import ingest
I = ingest.Ingestor()
milk = set(G.closure(R.resolve("milk")["roots"])[0])
iris = set()
for line in split_label("INGREDIENTS: WHEAT FLOUR, BUTTER, SUGAR"):
    res = I.line(line)
    if res["status"] == "resolved":
        iris.update(res.get("roots") or ())
ck(bool(iris & milk),
   "butter on a real label must reach milk through the real graph, or the oracle is "
   "measuring nothing")

if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

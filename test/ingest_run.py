#!/usr/bin/env python3
"""Ingestion must abstain rather than guess.

The pipeline exists to turn a cookbook line into a FoodOn class, and the single most
important thing about it is what it does when it cannot. An unresolved ingredient
quarantines a recipe; a wrongly resolved one PASSES it onto a plate. So the assertions
here are mostly about refusal.

The head-noun stage that used to take this from 64% to 90% is the thing being kept out:
it reached that number by dropping the modifier carrying the food -- `chili oil` -> oil,
`goat cheese` -> cheese -- across 1,921 ingredient uses.
"""
import json, sys, os
sys.path.insert(0, "build")
from ingest import Ingestor, normalise, strip_qualifiers, load_map, MAP_FILE

fails, checks = [], 0
I = Ingestor()

# ---- normalisation ----------------------------------------------------------
NORM = [
    ("2¾ tsp. kosher salt, divided, plus more", "kosher salt"),
    ("6 Tbsp. unsalted butter, melted, plus 3 Tbsp. room temperature", "unsalted butter"),
    ("1 (3½–4-lb.) whole chicken", "chicken"),
    ("Freshly ground black pepper", "black pepper"),
    # normalise handles quantity, unit and PREPARATION. Grade words -- `creamy`,
    # `good-quality` -- are QUALIFIERS and belong to the second stage, so they survive
    # this one. Two stages because the first is safe everywhere and the second is a
    # judgement about what FoodOn chooses to label.
    ("1/3 cup (3 ounces) creamy peanut butter, such as Skippy", "creamy peanut butter"),
]
TOGETHER = [
    ("1/3 cup creamy peanut butter", "peanut butter"),
    ("⅓ loaf good-quality sturdy white bread", "loaf sturdy white bread"),
]
for raw, want in NORM:
    checks += 1
    got = normalise(raw)
    if got != want:
        fails.append(f"normalise({raw[:34]!r}) = {got!r}, expected {want!r}")
for raw, want in TOGETHER:
    checks += 1
    got = strip_qualifiers(normalise(raw))
    if got != want:
        fails.append(f"normalise+strip({raw[:30]!r}) = {got!r}, expected {want!r}")

checks += 1
if strip_qualifiers("fine flaky sea salt") != "salt":
    fails.append("strip_qualifiers did not repeat until stable on `fine flaky sea salt`")

# ---- it must resolve the easy things ----------------------------------------
for raw, want_status in [("2 tablespoons olive oil", "resolved"),
                         ("1 tsp kosher salt", "resolved"),
                         ("4 Tbsp unsalted butter", "resolved"),
                         ("1 cup all-purpose flour", "resolved")]:
    checks += 1
    g = I.line(raw)
    if g["status"] != want_status:
        fails.append(f"{raw!r} -> {g['status']} via {g['stage']}, expected {want_status}")

# ---- and REFUSE the dangerous ones ------------------------------------------
# each of these has a head noun that resolves; taking it would drop the food
for raw, must_not in [("1 tablespoon chili oil", "oil"),
                      ("2 oz goat cheese", "cheese"),
                      ("1 tsp ancho chile powder", "powder"),
                      ("2 Tbsp fresh squeezed lemon juice", "juice"),
                      ("1/4 cup unseasoned rice vinegar", "vinegar")]:
    checks += 1
    g = I.line(raw)
    if g["status"] == "resolved" and g["term"] == must_not:
        fails.append(f"{raw!r} collapsed to `{must_not}` -- the modifier carried the food")

# peanut butter must never become butter: it is the difference between a peanut
# allergy being caught and being served
checks += 1
g = I.line("1/2 cup creamy peanut butter")
if g["status"] == "resolved" and "butter" in g["root_labels"] and "peanut" not in str(g["root_labels"]):
    fails.append("peanut butter resolved to butter")

# ---- a proposal is not a decision -------------------------------------------
spec = json.load(open(MAP_FILE))
checks += 1
live = load_map()
unsigned = [m for m in spec.get("mappings", []) if not m.get("signed_off_by")]
if any(m["term"] in live for m in unsigned):
    fails.append("an unsigned mapping is being applied by the pipeline")
checks += 1
if any(q.get("signed_off_by") for q in spec.get("requires_signoff", [])):
    fails.append("a signed entry is sitting in the review queue")
checks += 1
for q in spec.get("requires_signoff", []):
    if not q.get("term") or q.get("uses") is None:
        fails.append(f"queue entry missing term or uses: {q}"); break

# a signed mapping must take effect, and must be findable
checks += 1
probe = Ingestor(mapping={"red pepper flakes": {"term": "red pepper flakes",
                                                "maps_to": "chili pepper",
                                                "signed_off_by": "test"}})
g = probe.line("Pinch of crushed red pepper flakes")
if g["status"] != "resolved" or g["stage"] != "signed map":
    fails.append(f"a signed mapping did not apply: {g['status']} via {g['stage']}")

# ---- a recipe is only as good as its worst ingredient ------------------------
checks += 1
rec = I.recipe(["2 tablespoons olive oil", "1 tablespoon chili oil"])
if rec["usable"]:
    fails.append("a recipe with an unresolved ingredient was reported usable")

print(f"map: {len(spec.get('mappings', []))} signed, "
      f"{len(spec.get('requires_signoff', []))} queued "
      f"({spec.get('deterministic_share')}% of the seed corpus already deterministic)")
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails: print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

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

# hyphenated compounds, both directions. A preparation word on either side takes the
# WHOLE compound: stripping only the matching half left `oil-packed anchovies` as
# `oil anchovies` and `fire-roasted tomatoes` as `fire tomatoes`. But a hyphenated
# FOOD NAME has to survive, which is why the rule tests the parts and the stop-word
# pass excludes hyphens -- `half-and-half` was becoming `half -half`.
for raw, want in [("2 oil-packed anchovies", "anchovies"),
                  ("14 oz fire-roasted tomatoes", "tomatoes"),
                  ("2 cups ice-cold water", "water"),
                  ("1 lb freeze-dried strawberries", "strawberries"),
                  ("1 cup half-and-half", "half-and-half"),
                  ("1/4 cup bread-and-butter pickles", "bread-and-butter pickles")]:
    checks += 1
    got = strip_qualifiers(normalise(raw))
    if got != want:
        fails.append(f"hyphen handling: {raw!r} -> {got!r}, expected {want!r}")
checks += 1
if "-" in strip_qualifiers(normalise("2 Tbsp. good-quality olive oil")).split()[0]:
    fails.append("a hyphenated qualifier left its hyphen behind")

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

# ---- a re-seed must not discard what was decided -----------------------------
# The corpus and the normaliser both move, so the queue has to be re-seeded: terms
# appear, and terms stop existing -- `superfine` and `nuoc nam` were queued before the
# parenthetical and hyphen fixes and no line produces either now. But a re-seed that
# threw away the decisions layered on top would cost more than it cleaned.
spec_now = json.load(open(MAP_FILE))
checks += 1
decided = ({m["term"] for m in spec_now.get("mappings", [])}
           | {d["term"] for d in spec_now.get("declined", [])})
requeued = [q["term"] for q in spec_now.get("requires_signoff", []) if q["term"] in decided]
if requeued:
    fails.append(f"{len(requeued)} decided terms are back in the review queue, "
                 f"e.g. {requeued[:3]} -- a re-seed has discarded a decision")

# ---- batch review ------------------------------------------------------------
# Approving re-checks the target. A proposal was validated when it was made, and the
# ontology it was validated against is the one thing this project expects to be
# swapped -- signing off a mapping that no longer resolves would put a dead entry in
# the ingestion path, where it fails silently and quietly stops protecting anyone.
import shutil, tempfile
sys.path.insert(0, "build")
import audit_model as A

work = tempfile.mkdtemp()
copy = os.path.join(work, "ingredient-map.json")
shutil.copy(A.INGREDIENT_MAP, copy)
orig = A.INGREDIENT_MAP
A.INGREDIENT_MAP = copy
try:
    before = A.ingredients()
    checks += 1
    if before["queue"] != sorted(before["queue"], key=lambda e: -e["uses"]):
        fails.append("the review queue is not ordered by use; a reviewer working "
                     "top-down would not be buying the most coverage per decision")

    target = next(e["term"] for e in before["queue"] if e.get("proposed"))
    out = A.review_ingredients([target], "approve", who="test")
    checks += 1
    if target not in out["done"]:
        fails.append(f"approving `{target}` did not take: {out['skipped']}")
    after = A.ingredients()
    checks += 1
    if after["queued_total"] != before["queued_total"] - 1:
        fails.append("an approved term stayed in the queue")
    checks += 1
    if not any(m["term"] == target and m.get("signed_off_by") for m in after["signed"]):
        fails.append("an approved term did not arrive in `mappings` with a signature")

    # A CHOSEN CLASS BEATS THE PROPOSAL, and survives into ingestion as the id.
    # Storing the label and re-resolving it would put the resolver's scoring back in
    # the path, so a reviewer's override could silently land somewhere else later.
    pick = next((e for e in after["queue"] if len(e.get("shortlist") or []) > 1), None)
    if pick:
        alt = pick["shortlist"][1]["iri"]          # deliberately NOT the recommendation
        checks += 1
        A.review_ingredients([pick["term"]], "approve", who="test",
                             choices={pick["term"]: alt})
        m = next((x for x in A.ingredients()["signed"] if x["term"] == pick["term"]), None)
        if not m or m.get("maps_to_iri") != alt:
            fails.append(f"the chosen class was not stored for `{pick['term']}`")
        else:
            probe = Ingestor(mapping={pick["term"]: m})
            got = probe.line(pick["term"])
            checks += 1
            if got["roots"] != [alt]:
                fails.append(f"ingest did not use the chosen id: {got['roots']}")

    # CORRECTING an already-signed mapping. One signed in good faith and later found
    # coarse -- `apple cider vinegar` to `cider vinegar` where `apple vinegar food
    # product` was the better class -- must be fixable here, not by hand-editing the
    # file this interface exists to replace.
    sig = A.ingredients()["signed"]
    if sig:
        m0 = sig[0]
        alt = next((c["iri"] for c in (m0.get("shortlist") or [])
                    if c["iri"] != m0.get("maps_to_iri")), None)
        if alt:
            checks += 1
            A.review_ingredients([m0["term"]], "approve", who="test",
                                 choices={m0["term"]: alt})
            now = next(x for x in A.ingredients()["signed"] if x["term"] == m0["term"])
            if now.get("maps_to_iri") != alt:
                fails.append("correcting a signed mapping did not take")
            elif not now.get("corrected_from"):
                fails.append("a correction did not record what it replaced")
            checks += 1
            if len(A.ingredients()["signed"]) != len(sig):
                fails.append("correcting a mapping duplicated or dropped it")

    # an excluded-branch class can never match a query, so it must be refused
    checks += 1
    exq = next((e for e in A.ingredients()["queue"] if e.get("shortlist")), None)
    if exq:
        excluded_iri = next((i for i in A.Graph().excluded), None)
        out_x = A.review_ingredients([exq["term"]], "approve", who="test",
                                     choices={exq["term"]: excluded_iri})
        if out_x["done"]:
            fails.append("approved a mapping to an excluded-branch class, which can "
                         "never match a query")

    # A shortlist must never offer a class outside a food namespace. Four signed
    # mappings landed on GAZ `Chile` -- the COUNTRY -- because the label matched, and
    # an ingredient mapped to a country never matches anything while reading as done.
    checks += 1
    bad_ns = [(e["term"], c["curie"]) for e in A.ingredients()["queue"]
              for c in (e.get("shortlist") or [])
              if c["curie"].split(":")[0] not in
                 {"FOODON", "NCBITaxon", "CHEBI", "UBERON", "PO"}]
    if bad_ns:
        fails.append(f"shortlists offer classes outside a food namespace: {bad_ns[:3]}")

    # A term the resolver settles WRONGLY has no entry anywhere: the queue holds only
    # what it cannot settle. `pepper` resolves cleanly to Capsicum while all 110 of its
    # lines in the corpus read "freshly ground pepper", so an override needs a way in.
    checks += 1
    fresh = "a term the queue has never heard of"
    out_new = A.review_ingredients([fresh], "approve", who="test",
                                   choices={fresh: "http://purl.obolibrary.org/obo/FOODON_00001650"})
    if fresh not in out_new["done"]:
        fails.append(f"could not create an override for an unqueued term: {out_new['skipped']}")
    else:
        m_new = next(x for x in A.ingredients()["signed"] if x["term"] == fresh)
        checks += 1
        if not m_new.get("overrides_resolver"):
            fails.append("an override of the resolver was not recorded as one")
    # ...but not without naming a class
    checks += 1
    out_bad = A.review_ingredients(["another unheard-of term"], "approve", who="test")
    if out_bad["done"]:
        fails.append("created a mapping for an unqueued term with nothing to map it to")

    # an id that is not a class in this release must be refused
    checks += 1
    nope = A.review_ingredients([after["queue"][0]["term"]], "approve", who="test",
                                choices={after["queue"][0]["term"]:
                                         "http://purl.obolibrary.org/obo/FOODON_99999999"})
    if nope["done"] or not nope["skipped"]:
        fails.append("approved a mapping to a class this release does not have")

    # a target that does not resolve must be skipped, not written
    checks += 1
    t2 = next(e["term"] for e in after["queue"] if e.get("proposed"))
    out2 = A.review_ingredients([t2], "approve", who="test", target="unobtainium puree")
    if out2["done"] or not out2["skipped"]:
        fails.append("approved a mapping whose target does not resolve")

    checks += 1
    out3 = A.review_ingredients([], "approve", who="test")
except A.EditError:
    pass
except Exception as e:
    fails.append(f"batch review raised {type(e).__name__}: {e}")
else:
    fails.append("an empty selection was accepted")
finally:
    A.INGREDIENT_MAP = orig
    shutil.rmtree(work)

print(f"map: {len(spec.get('mappings', []))} signed, "
      f"{len(spec.get('requires_signoff', []))} queued "
      f"({spec.get('deterministic_share')}% of the seed corpus already deterministic)")
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails: print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

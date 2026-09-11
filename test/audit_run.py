#!/usr/bin/env python3
"""The audit view must not lie about what the local layer does.

Three things worth asserting, and the first is the one that caught a real defect:

  ATTRIBUTION  the two `remove` overrides are the largest edits in the whole layer --
               beef loses 770 classes, tree nut loses 91 -- and an early version of
               this view showed `beef  -770` beside "no local decision touches this
               ingredient". The cause was `remove` entries spelling the field
               `query_root` while `add` entries spelled it `query_roots`. An audit that
               silently omits the biggest decision is worse than no audit.

  ARITHMETIC   ours == vendor - removed + added, per ingredient. The bar is drawn from
               these and drew 102% before the identity was checked.

  GUARDS       every write path refuses what it should, including id 0, which is a
               legitimate override index and was rejected as "required" by a truth test.
"""
import json, sys, os, tempfile, shutil, copy

sys.path.insert(0, "build")
import audit_model as A

fails, checks = [], 0
d = A.build()
by = {c["name"]: c for c in d["cards"]}

# ---- attribution ------------------------------------------------------------
for name, claim in (("beef", "not_avoidance_relevant"), ("tree nut", "not_avoidance_relevant")):
    checks += 1
    c = by.get(name)
    if not c:
        fails.append(f"no dossier for `{name}`"); continue
    if not c["removed"]:
        fails.append(f"{name}: expected a suppression, found none"); continue
    got = [x for x in c["decisions"] if x["claim"] == claim]
    if not got:
        fails.append(f"{name} suppresses {c['removed']} classes but no `{claim}` decision "
                     f"is attributed to it -- the audit would show an unexplained edit")

# every card's decisions must name a file that exists
for c in d["cards"]:
    for x in c["decisions"]:
        checks += 1
        if not os.path.exists(x["file"]):
            fails.append(f"{c['name']}: decision cites a missing file {x['file']}")

# ---- arithmetic -------------------------------------------------------------
for c in d["cards"]:
    checks += 1
    if c["ours"] != c["vendor"] - c["removed"] + c["added"]:
        fails.append(f"{c['name']}: {c['vendor']} - {c['removed']} + {c['added']} "
                     f"!= {c['ours']}; the bar is drawn from these")

# Every pinned term must be reachable, as a dossier name OR as an alias on one:
# `paprika` and `smoked paprika` are separate decisions with identical roots, so they
# are one dossier. Asserting a card per pin would demand the view split a resolution
# that is genuinely single.
checks += 1
pins = {p["query"] for p in json.load(open(A.PINS))["pins"]}
shown = {c["name"] for c in d["cards"]} | {a for c in d["cards"] for a in c["aliases"]}
missing = pins - shown
if missing:
    fails.append(f"pinned but unreachable in the audit: {sorted(missing)}")

# ---- write guards -----------------------------------------------------------
work = tempfile.mkdtemp()
for f in (A.OVERRIDES, A.PINS, A.TAXON, A.MINED_SIGNOFF):
    shutil.copy(f, os.path.join(work, os.path.basename(f)))
orig = {k: getattr(A, k) for k in ("OVERRIDES", "PINS", "TAXON", "MINED_SIGNOFF")}
for k, v in orig.items():
    setattr(A, k, os.path.join(work, os.path.basename(v)))

def refuses(action, payload, because):
    global checks
    checks += 1
    try:
        A.apply_edit(action, payload)
        fails.append(f"{action} accepted what it should refuse: {because}")
    except A.EditError:
        pass
    except Exception as e:
        fails.append(f"{action} raised {type(e).__name__} instead of EditError: {e}")

refuses("edit_override", {"id": 0, "fields": {"claim": "probably_fine"}}, "undeclared claim")
refuses("edit_override", {"id": 0, "fields": {"target_class": "http://x"}}, "repointing a claim")
refuses("edit_override", {"id": 99999, "fields": {"reason": "x"}}, "no such override")
refuses("add_override", {"target_class": "http://purl.obolibrary.org/obo/CHEBI_30769",
                         "claim": "contains", "reason": "x"}, "no query root")
refuses("add_override", {"target_class": "http://purl.obolibrary.org/obo/NOPE_1",
                         "claim": "contains", "reason": "x",
                         "query_roots": ["http://purl.obolibrary.org/obo/NCBITaxon_4070"]},
        "target is not a FoodOn class")
refuses("edit_pin", {"query": "gluten", "fields": {"root_labels": ["unobtainium plant"]}},
        "root label FoodOn does not have")
refuses("edit_pin", {"query": "not a pinned term", "fields": {"note": "x"}}, "no such pin")
refuses("signoff", {"kind": "mined", "id": "x"}, "no rationale")
refuses("nonsense", {}, "unknown action")

# id 0 is a real override, and a truth test used to reject it
checks += 1
try:
    A.apply_edit("edit_override", {"id": 0, "fields": {"review_note": "ok"}})
except A.EditError as e:
    fails.append(f"edit_override refused override 0, which exists: {e}")

for k, v in orig.items():
    setattr(A, k, v)
shutil.rmtree(work)

# ---- the statement layer -----------------------------------------------------
# A predicate must land somewhere real, and must be honest about whether it enters the
# closure -- that flag is what the UI uses to tell a reviewer whether a mistake here
# reaches a diner.
for name, p in A.PREDICATES.items():
    checks += 1
    if not os.path.exists(p["lands"]):
        fails.append(f"predicate `{name}` lands in {p['lands']}, which does not exist")
    checks += 1
    if p["enters"] and p["claim"] not in ("contains", "is a", "in taxon"):
        fails.append(f"predicate `{name}` claims to enter the closure as `{p['claim']}`, "
                     f"which build/traverse.py does not traverse")
    checks += 1
    if not p["enters"] and p["claim"] in ("contains", "is a", "in taxon"):
        fails.append(f"predicate `{name}` is marked reported-only but its claim "
                     f"`{p['claim']}` does enter the closure")

# the preview must count a suppression's REMOVALS. It reported "no closure changes"
# for the only decisions that take food off an avoidance list until this was asserted.
_ex = lambda lab: next(i for i, v in A.Graph().N.items() if (v.get("l") or "").lower() == lab)
checks += 1
try:
    pv = A.preview(dict(predicate="not relevant for", subject=_ex("almond"),
                        object=_ex("nut producing plant")))
    if not any(c["lost"] for c in pv["changes"]):
        fails.append("preview of a suppression counted no removals")
except Exception as e:
    fails.append(f"preview of a suppression raised {type(e).__name__}: {e}")

# rank guard on the taxon predicate: a genus here widens every query beneath it
checks += 1
try:
    A.preview(dict(predicate="in taxon", subject=_ex("lemon plant"),
                   object=_ex("citrus")if False else "http://purl.obolibrary.org/obo/NCBITaxon_2706"))
    fails.append("preview accepted a genus as an `in taxon` object")
except A.EditError:
    pass

checks += 1
if not A.lookup("sesame plant"):
    fails.append("lookup found nothing for an exact class label")

print(f"{len(d['cards'])} ingredient dossiers, "
      f"{sum(len(c['decisions']) for c in d['cards'])} decisions attributed, "
      f"{len(d['rest'])} not tied to one ingredient")
add = sum(c["added"] for c in d["cards"]); rem = sum(c["removed"] for c in d["cards"])
print(f"the local layer adds {add} classes and suppresses {rem}")
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f_ in fails: print("   -", f_)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

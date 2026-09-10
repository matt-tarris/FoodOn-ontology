#!/usr/bin/env python3
"""Draft config/overrides.json from the relation-typed allergen golden set.

Everything here is a PROPOSAL. Per spec section 3 no entry governs traversal until a
human signs it off, because a wrong entry has direct safety consequences.

Three sources feed it:
  1. provenance / cross_reactivity / disputed terms, which the ontology can never
     assert and which traversal correctly refuses to reach
  2. containment terms FoodOn models but leaves unconnected (audit: processed
     ingredients parented by function with no source)
  3. the two mis-parenting defects from audit F11
"""
import json, sys, collections
sys.path.insert(0, "build")
from traverse import Graph
from resolve import Resolver

R = Resolver()
g = R.g
spec = json.load(open("test/allergen-golden.json"))
label_ix = {}
for i, v in g.N.items():
    if v.get("dep") or i in g.excluded: continue
    l = (v.get("l") or "").lower()
    if l: label_ix.setdefault(l, i)

CLAIM = {
  "provenance":       ("may_contain",  "medium"),
  "cross_reactivity": ("cross_reactive", "medium"),
  "disputed":         ("disputed",     "low"),
}
SRC = {
  "provenance":       "manufacturing feedstock varies by producer; not a property of the substance",
  "cross_reactivity": "clinical cross-reactivity literature; the allergen protein is not present",
  "disputed":         "appears on avoidance lists without an established containment basis",
}

_par = collections.defaultdict(list)
for _e in json.load(open("data/index.json"))["edges"]:
    if _e["p"] == "isa":
        _par[_e["s"]].append(_e["o"])
def _parents_of(i): return _par.get(i, [])

def roots_for(name):
    """An override attaches to the query's RESOLVED ROOTS. Keying it on the label
    string leaves it inert: `self.derive["Corn"]` is a key the traversal never
    visits."""
    res = g and None
    rr = R.resolve(name)
    return (rr.get("roots") or [], rr.get("root_labels") or [])

entries = []
for block in spec["allergens"]:
    common = block["common"]
    roots = [i for r in block["roots"] if (i := label_ix.get(r.lower()))]
    reached = set(g.closure(roots)[0]) if roots else set()
    for t in block["terms"]:
        rel, term = t["relation"], t["term"]
        tid = label_ix.get(term.lower())
        if rel in CLAIM:
            claim, conf = CLAIM[rel]
            qr, ql = roots_for(common)
            entries.append({
              "type": "add", "claim": claim, "status": "PROPOSED",
              "query_class": common, "query_roots": qr, "query_root_labels": ql,
              "target_label": term,
              "target_class": tid, "in_foodon": bool(tid),
              "confidence": conf, "reason": t["note"], "source": SRC[rel],
              "reviewed_by": None, "reviewed_date": None,
            })
        elif rel == "containment" and tid and tid not in reached:
            parents = [g.label(o) for (o, r_, _p, _c) in [] ] or []
            cur = ", ".join(sorted({g.label(pp) for pp in _parents_of(tid)})) or "unknown"
            qr, ql = roots_for(common)
            entries.append({
              "type": "add", "claim": "contains", "status": "PROPOSED",
              "query_class": common, "query_roots": qr, "query_root_labels": ql,
              "target_label": term,
              "target_class": tid, "in_foodon": True, "confidence": "high",
              "reason": f"{t['note']}. FoodOn models this class but parents it by function "
                        f"({cur}) and asserts no source.",
              "source": "audit: processed ingredients are parented by function with no derives-from",
              "reviewed_by": None, "reviewed_date": None,
            })

# audit F11 mis-parenting defects
for lbl_, parent, why in [
  ("rye kernel", "sumac food product",
   "FoodOn parents rye kernel under sumac food product (IDs 00003734 vs sumac berry 00003733, an adjacent-ID slip). A rye query misses rye kernel and its raw/cooked/dried forms - a gluten false negative."),
  ("hickory nut", "mustard spinach food product",
   "FoodOn parents hickory nut under mustard spinach food product. hickory tree has a closure of 1, and pecan sits under hickory nut, so both are orphaned - a tree-nut false negative."),
]:
    qr, ql = roots_for(lbl_.split()[0])
    entries.append({
      "type": "add", "claim": "contains", "status": "PROPOSED",
      "query_class": lbl_.split()[0], "query_roots": qr, "query_root_labels": ql,
      "target_label": lbl_,
      "target_class": label_ix.get(lbl_), "in_foodon": True, "confidence": "high",
      "reason": why, "source": "audit F11, build/detect_misparent.py",
      "reviewed_by": None, "reviewed_date": None,
    })

# PRESERVE SIGN-OFF. This script regenerates proposals from the golden set; it must
# never discard a human decision. Any existing entry with reviewed_by set is carried
# through untouched, and a regenerated proposal for the same pair is dropped in its
# favour.
try:
    prev = json.load(open("config/overrides.json"))["overrides"]
except (FileNotFoundError, json.JSONDecodeError):
    prev = []
# declined entries are decisions too: they must survive regeneration, or the next
# run silently re-proposes something already ruled out
kept = [o for o in prev if o.get("reviewed_by")
        or o.get("status") in ("HELD", "ANNOTATION")]
# Key on the PAIR only, never on type: a declined entry has its type rewritten, and
# keying on type let the next run re-propose something already ruled out.
signed_keys = {((o.get("query_class") or o.get("query_root_label") or "").lower(),
                (o.get("target_label") or "").lower()) for o in kept}
entries = [e for e in entries
           if ((e.get("query_class") or "").lower(),
               (e.get("target_label") or "").lower()) not in signed_keys]
entries = kept + entries
print(f"carried forward {len(kept)} signed entries")

# Top-level metadata is CARRIED FORWARD, not restamped. This script drafts
# proposals; it does not own the file's review state. Rewriting `version` and
# `status` would relabel a fully reviewed file as DRAFT, and `entry_types` -- the
# vocabulary documenting add / remove / declined / superseded -- was being dropped
# entirely, because it was added to the governed file after this generator was
# written and the output dict below never knew about it.
prev_meta = {}
try:
    prev_meta = json.load(open("config/overrides.json"))
except (FileNotFoundError, json.JSONDecodeError):
    pass
unreviewed = [e for e in entries if not e.get("reviewed_by")]

out = {
  "version": prev_meta.get("version", "2026-09-09"),
  "status": (prev_meta.get("status") if not unreviewed else
             "DRAFT - no entry governs traversal until reviewed_by is set "
             "(spec section 3)"),
  "ontology_version": g.meta["version"],
  "claim_types": {
    "contains":       "the target genuinely contains or derives from the query. FoodOn simply fails to connect them.",
    "may_contain":    "commonly but not necessarily derived from the query; feedstock is a producer choice.",
    "cross_reactive": "immunologically related; the allergen protein is NOT present.",
    "disputed":       "appears on avoidance lists without an established containment basis.",
  },
  "overrides": entries,
}
# anything the governed file has that this generator does not know about survives
for k, v in prev_meta.items():
    out.setdefault(k, v)
json.dump(out, open("config/overrides.json", "w"), indent=2)
c = collections.Counter(e["claim"] for e in entries)
n_abs = sum(1 for e in entries if e.get("in_foodon") is False)
unrooted = [e for e in entries if e.get("type") == "add" and not e.get("query_roots")]
print(f"{len(entries)} proposed overrides")
if unrooted:
    print(f"  !! {len(unrooted)} have NO resolvable query root and would be inert:")
    for e in unrooted: print(f"     {e['query_class']} -> {e['target_label']}")
for k, v in c.most_common(): print(f"   {k:<16} {v}")
print(f"\n{n_abs} target terms have no FoodOn class -- these cannot be wired as edges;")
print("they need a class created, or the entry becomes a label-level annotation only.")

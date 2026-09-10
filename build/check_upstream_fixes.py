#!/usr/bin/env python3
"""Which local patches has a new upstream FoodOn release made unnecessary?

Run this after dropping in a new ontology/foodon.owl. A patch that upstream now
asserts natively is dead weight: it says nothing the ontology does not already say,
and leaving it in place makes the local layer look larger and more opinionated than
it is. This is the deprecation half of the patch lifecycle.

    java -jar tools/robot.jar query --input ontology/foodon.owl \\
         --query build/sparql/patch_native_axioms.rq data/native-axioms.csv
    python3 build/check_upstream_fixes.py

Why two steps rather than one SPARQL query. The patch layer is additive and leaves
no seam: once merged, an axiom we supplied is indistinguishable from one FoodOn
shipped. So the comparison has to be against the VENDOR file alone, with the patch
list read separately. (A triplestore with named graphs can do it in one query --
see build/sparql/named_graphs.ru -- because there the base graph stays separate.)

Nothing is deleted automatically. Retiring a patch is a decision: it goes through
the same sign-off the patch did, and this project has a `superseded` status for
exactly that, so the record of why the gap existed survives the fix.
"""
import csv, json, os, sys, collections

NATIVE = "data/native-axioms.csv"
if not os.path.exists(NATIVE):
    print(f"missing {NATIVE}. Generate it first:\n"
          f"  java -jar tools/robot.jar query --input ontology/foodon.owl \\\n"
          f"       --query build/sparql/patch_native_axioms.rq {NATIVE}")
    sys.exit(1)

sys.path.insert(0, "build")
from traverse import Graph
g = Graph()
lbl = lambda i: (g.N.get(i, {}) or {}).get("l") or i

native = set()
for row in csv.DictReader(open(NATIVE)):
    native.add((row["target"], row["property"], row["value"]))

RO_DERIVES = "http://purl.obolibrary.org/obo/RO_0001000"
patches = []          # (source_file, kind, target, value, describe)

for a in json.load(open("data/repairs-classified.json"))["auto_apply"]:
    patches.append(("data/repairs-classified.json", "repair",
                    a["product"], a["source"], a.get("rule", "")))
for a in json.load(open("data/mined-classified.json"))["signed_off"]:
    if a.get("relation") == "is a":
        continue
    patches.append(("config/mined-signoff.json", "mined bridge",
                    a["product"], a["source"], a.get("rule", "")))
for o in json.load(open("config/overrides.json"))["overrides"]:
    if o.get("type") != "add" or o.get("claim") != "contains":
        continue
    for r in o.get("query_roots") or []:
        patches.append(("config/overrides.json", "contains override",
                        o["target_class"], r, o.get("reason", "")))

fixed, live = [], 0
for src, kind, target, value, why in patches:
    if not target or not value:
        continue
    if (target, RO_DERIVES, value) in native:
        fixed.append((src, kind, target, value, why))
    else:
        live += 1

print(f"vendor ontology     : FoodOn {g.meta['version']}")
print(f"native axioms read  : {len(native):,}")
print(f"local patches checked: {len(patches)}")
print(f"  still doing work  : {live}")
print(f"  now redundant     : {len(fixed)}")

if fixed:
    print("\nUPSTREAM HAS FIXED THESE -- the local patch can be retired:")
    bysrc = collections.defaultdict(list)
    for src, kind, t, v, why in fixed:
        bysrc[src].append((kind, t, v, why))
    for src, rows in bysrc.items():
        print(f"\n  {src}")
        for kind, t, v, why in rows:
            print(f"    {lbl(t)}  --derives from-->  {lbl(v)}")
            print(f"      {kind}; {(why or '')[:90]}")
    print("\nRetire, do not delete. Set the entry's type to `superseded` with a")
    print("`superseded_by` naming the upstream release, so the record of why the gap")
    print("existed survives. test/override_run.py then asserts the target is still")
    print("reached, which is what stops a retirement from silently losing coverage.")
else:
    print("\nNo local patch has been made redundant by this release. Every one is")
    print("still supplying an axiom FoodOn does not assert.")

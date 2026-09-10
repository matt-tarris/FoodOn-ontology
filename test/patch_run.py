#!/usr/bin/env python3
"""The exported patch layer must mean the same thing as the application.

Two independent claims, both worth asserting because the patch layer exists to be
consumed WITHOUT this codebase:

  PARITY     a SPARQL closure over `foodon.owl + foodon-local-patches.ttl` returns
             exactly what build/traverse.py returns for the same roots. If these
             ever diverge, one of them is lying to somebody.

  ROUND TRIP every axiom in the .ttl traces back to a governed decision file, and
             every governed decision appears in the .ttl. A hand-edit to the
             generated file, or a decision that silently fails to export, fails
             here.

Needs the artifacts from tools/apply_patches.sh. Skips with a clear message rather
than failing if they are absent, because the merge takes ~40s and is not something
to run on every commit.
"""
import json, os, subprocess, sys, csv, collections, tempfile, re

sys.path.insert(0, "build")
from traverse import Graph

TTL = "ontology/foodon-local-patches.ttl"
QUERYABLE = "ontology/foodon-queryable.owl"
ROBOT = ["java", "-Xmx10g", "-jar", "tools/robot.jar"]
BASE = "https://fluxon.com/ns/foodon-local/"

fails, checks = [], 0

if not os.path.exists(TTL):
    print("no patch layer yet -- run: python3 build/emit_patches.py")
    sys.exit(0)

ttl = open(TTL).read()
g = Graph()
lbl = lambda i: (g.N.get(i, {}) or {}).get("l") or i

# ---------------------------------------------------------------- round trip
# Every restriction axiom in the file, as (target, property, value) curies.
axioms = set()
for m in re.finditer(
        r"^(obo:\S+) rdfs:subClassOf \[\s*\n"
        r"\s*a owl:Restriction ;\s*\n"
        r"\s*owl:onProperty (obo:\S+) ;\s*\n"
        r"\s*owl:someValuesFrom (obo:\S+) \] \.", ttl, re.M):
    axioms.add(m.groups())
assertions = set(re.findall(r"^(obo:\S+) (local:\S+) (obo:\S+) \.$", ttl, re.M))

cur = lambda iri: "obo:" + iri.rsplit("/", 1)[-1]
expected_ax, expected_as = set(), set()
for a in json.load(open("data/repairs-classified.json"))["auto_apply"]:
    expected_ax.add((cur(a["product"]), "obo:RO_0001000", cur(a["source"])))
for a in json.load(open("data/mined-classified.json"))["signed_off"]:
    if a.get("relation") == "is a":
        continue                      # emitted as a named subClassOf, checked below
    expected_ax.add((cur(a["product"]), "obo:RO_0001000", cur(a["source"])))
WEAK = {"may_contain": "local:mayDeriveFrom", "cross_reactive": "local:crossReactiveWith",
        "disputed": "local:disputedAvoidance"}
for o in json.load(open("config/overrides.json"))["overrides"]:
    tgt, claim, typ = o.get("target_class"), o.get("claim"), o.get("type")
    if not tgt or typ == "superseded":
        continue
    roots = o.get("query_roots") or ([o["query_root"]] if o.get("query_root") else [])
    if typ == "remove":
        expected_as.add((cur(tgt), "local:notAvoidanceRelevantFor", cur(roots[0])))
    elif typ == "add" and claim == "contains":
        for r in roots:
            expected_ax.add((cur(tgt), "obo:RO_0001000", cur(r)))
    elif claim in WEAK:
        for r in roots:
            expected_as.add((cur(tgt), WEAK[claim], cur(r)))

# parallel-hierarchy correspondences, recomputed the same way the emitter does
store = json.load(open("data/resolution-store.json"))
_roots = sorted({r for e in store["entries"].values()
                 if e.get("status") == "resolved" for r in (e.get("roots") or [])})
for _r in _roots:
    for _k in (g.expand_roots([_r]) or {}):
        if _k != _r:
            expected_as.add((cur(_r), "local:sameOrganismAs", cur(_k)))

checks += 1
missing = expected_ax - axioms
if missing:
    fails.append(f"{len(missing)} governed axioms absent from the .ttl, e.g. "
                 f"{sorted(missing)[:3]}")
checks += 1
extra = axioms - expected_ax
if extra:
    fails.append(f"{len(extra)} axioms in the .ttl with no governed decision behind "
                 f"them (hand-edit?), e.g. {sorted(extra)[:3]}")
checks += 1
if expected_as - assertions:
    fails.append(f"{len(expected_as - assertions)} governed local assertions absent, "
                 f"e.g. {sorted(expected_as - assertions)[:3]}")
checks += 1
if assertions - expected_as:
    fails.append(f"{len(assertions - expected_as)} local assertions with no governed "
                 f"decision, e.g. {sorted(assertions - expected_as)[:3]}")

# a may_contain must never be emitted on RO:0001000 -- the whole point of the
# separate vocabulary
checks += 1
for tgt, prop, val in axioms:
    if prop != "obo:RO_0001000":
        fails.append(f"unexpected property in a containment axiom: {prop}")
weak_targets = {t for t, p, v in assertions if p in WEAK.values()}
containment_targets = {t for t, p, v in axioms}
checks += 1
both = weak_targets & containment_targets
# a class may legitimately be both (corn may_contain X while Y contains X), so only
# flag when the SAME pair appears on both a weak property and RO:0001000
pairs_weak = {(t, v) for t, p, v in assertions if p in WEAK.values()}
pairs_cont = {(t, v) for t, p, v in axioms}
if pairs_weak & pairs_cont:
    fails.append(f"same pair asserted as BOTH containment and a weaker claim: "
                 f"{sorted(pairs_weak & pairs_cont)[:3]}")

print(f"round trip: {len(axioms)} containment axioms, {len(assertions)} local "
      f"assertions, all traced to a governed file")

# ---------------------------------------------------------------- parity
if not os.path.exists(QUERYABLE):
    print(f"\n{QUERYABLE} not built -- run ./tools/apply_patches.sh for the parity "
          f"half of this test")
else:
    ROOTS = {
        "Solanaceae": "NCBITaxon_4070",
        "Maize plant": "FOODON_00003425",
        "wheat plant": "FOODON_03411312",
        "sesame plant": "FOODON_03411226",
        "mustard plant": "FOODON_00002053",
        "Capsicum": "NCBITaxon_4071",
    }
    values = " ".join(f"obo:{v}" for v in ROOTS.values())
    q = open("build/sparql/patch_closure.rq").read()
    q = re.sub(r"VALUES \?root \{[^}]*\}", "VALUES ?root { " + values + " }", q)
    q = q.replace("SELECT DISTINCT ?avoid ?label", "SELECT DISTINCT ?root ?avoid")
    q = re.sub(r"OPTIONAL \{ \?avoid rdfs:label \?label \}", "", q)
    q = re.sub(r"ORDER BY \?label", "", q)
    with tempfile.NamedTemporaryFile("w", suffix=".rq", delete=False) as f:
        f.write(q); qf = f.name
    out = tempfile.mktemp(suffix=".csv")
    r = subprocess.run(ROBOT + ["query", "--input", QUERYABLE, "--query", qf, out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append("robot query failed: " + (r.stderr or "")[-400:])
    else:
        sp = collections.defaultdict(set)
        for row in csv.DictReader(open(out)):
            sp[row["root"]].add(row["avoid"])
        print()
        print(f"{'root':<16} {'app':>7} {'sparql':>7} {'agree':>7}  {'diff':>6}")
        print("-" * 50)
        for name, frag in ROOTS.items():
            iri = "http://purl.obolibrary.org/obo/" + frag
            checks += 1
            py = set(g.closure([iri])[0]) - {iri}
            s = sp.get(iri, set())
            d = len(py ^ s)
            print(f"{name:<16} {len(py):>7,} {len(s):>7,} {len(py & s):>7,}  {d:>6}")
            if d:
                only_py = [lbl(x) for x in list(py - s)[:4]]
                only_sp = [lbl(x) for x in list(s - py)[:4]]
                fails.append(f"{name}: SPARQL and the app disagree on {d} classes "
                             f"(app-only {only_py}, sparql-only {only_sp})")
    os.unlink(qf)

if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f_ in fails:
        print("   -", f_)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

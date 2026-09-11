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
# supplied `in taxon` links, on the ontology's own property rather than a local one
for b in json.load(open("config/taxon-bridges.json"))["signed_off"]:
    if b.get("taxon") and b.get("signed_off_by"):
        expected_ax.add((cur(b["class"]), "obo:RO_0002162", cur(b["taxon"])))
WEAK = {"may_contain": "local:mayDeriveFrom", "cross_reactive": "local:crossReactiveWith",
        "disputed": "local:disputedAvoidance",
        "shared_compound": "local:sharesCompoundWith"}
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

# parallel-hierarchy correspondences, recomputed the same way the emitter does.
# Compared as UNORDERED pairs. Two facets of one ingredient often expand to each
# other -- `tomato` finds `tomato plant` and `tomato plant` finds `tomato` -- and
# the emitter writes such a pair once. That is not a gap: the property is declared
# symmetric, and because `robot query` does no reasoning, build/sparql/
# patch_closure.rq walks it in both directions explicitly. Demanding both triples
# here would fail the emitter for output the consumer reads correctly.
store = json.load(open("data/resolution-store.json"))
_roots = sorted({r for e in store["entries"].values()
                 if e.get("status") == "resolved" for r in (e.get("roots") or [])})
expected_same = set()
for _r in _roots:
    for _k in (g.expand_roots([_r]) or {}):
        if _k != _r:
            expected_same.add(frozenset((cur(_r), cur(_k))))
ttl_same = {frozenset((t, v)) for t, p, v in assertions if p == "local:sameOrganismAs"}
assertions = {(t, p, v) for t, p, v in assertions if p != "local:sameOrganismAs"}

checks += 1
if expected_same - ttl_same:
    fails.append(f"{len(expected_same - ttl_same)} organism correspondences absent "
                 f"from the .ttl, e.g. {[sorted(x) for x in list(expected_same - ttl_same)[:3]]}")
checks += 1
if ttl_same - expected_same:
    fails.append(f"{len(ttl_same - expected_same)} organism correspondences in the "
                 f".ttl with no governed root behind them, e.g. "
                 f"{[sorted(x) for x in list(ttl_same - expected_same)[:3]]}")

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
    if prop not in ("obo:RO_0001000", "obo:RO_0002162"):
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

# ---------------------------------------------------------- known limitation
# Parity holds for a root the emitter has written correspondences for, and the
# emitter writes them only for roots in data/resolution-store.json. Any OTHER root
# that `expand_roots` would pair -- `citrus fruit` pairs with `citrus fruit food
# product` by label convention, worth 50 classes -- has no local:sameOrganismAs
# triple, so a SPARQL consumer under-reports it while the app does not.
#
# Reported rather than failed: closing it means running expand_roots over all 39,894
# classes at emit time (~5 min, ~4,400 extra triples) or materialising the pairing in
# SPARQL, and which of those is right is a decision, not a bug fix. Printed every run
# so it cannot quietly become permanent.
_pinned = set(_roots)
_unpinned_pairs = 0
for _probe in ["FOODON_00003324"]:          # citrus fruit, the case that exposed this
    _i = "http://purl.obolibrary.org/obo/" + _probe
    if _i in _pinned: continue
    _unpinned_pairs += sum(1 for _x in (g.expand_roots([_i]) or {}) if _x != _i)
_nested = sum(1 for _e in json.load(open("data/index.json"))["edges"]
              if _e.get("k") in ("rel_nest", "isa_union"))
if _unpinned_pairs or _nested:
    print(f"\nTWO KNOWN PARITY HOLES, both pre-existing and both invisible until a "
          f"seventh root was tried:")
    print(f"  unpinned correspondences  {_unpinned_pairs} on the probed root (citrus "
          f"fruit, worth 50 classes).")
    print(f"                            Closing it means expand_roots over all "
          f"{len(g.N):,} classes at emit time (~5 min, ~4,400 triples) or "
          f"materialising the pairing in SPARQL.")
    print(f"  nested-filler subsumption {_nested} edges the index extracts from union "
          f"and restriction fillers")
    print(f"                            that a plain rdfs:subClassOf path cannot see. "
          f"Costs a citrus query one class, `imitation orange juice drink`.")
    print(f"  Which fix is right is a decision, not a bug fix. Printed every run so it "
          f"cannot quietly become permanent.")

print(f"round trip: {len(axioms)} containment axioms, {len(assertions)} local "
      f"assertions, {len(ttl_same)} organism correspondences, all traced to a "
      f"governed file")

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
        # carries the five supplied `in taxon` links. Whole-root parity is NOT claimed
        # for citrus -- it trips both pre-existing holes reported above -- but the
        # bridges themselves are asserted below, because an axiom the consumer cannot
        # act on is not a patch, it is a comment.
        "Citrus": "NCBITaxon_2706",
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
        _cit = sp.get("http://purl.obolibrary.org/obo/NCBITaxon_2706", set())
        _bridges = json.load(open("config/taxon-bridges.json"))["signed_off"]
        for _b in _bridges:
            checks += 1
            if _b["class"] not in _cit:
                fails.append(f"taxon bridge not honoured by SPARQL: a Citrus query does "
                             f"not reach `{_b['class_label']}` through its supplied "
                             f"`in taxon {_b['taxon_label']}`")
        _zan = {"FOODON_03412295": "prickly ash plant",
                "FOODON_03412306": "japan pepper plant",
                "FOODON_03310095": "sansho (food product)",
                "FOODON_03415174": "uzazi fruit"}
        for _f, _l in _zan.items():
            checks += 1
            if "http://purl.obolibrary.org/obo/" + _f in _cit:
                fails.append(f"SPARQL reaches `{_l}` from Citrus -- Zanthoxylum is in "
                             f"the citrus FAMILY and is not citrus; the per-class "
                             f"bridges exist precisely to keep it out")
        print()
        print(f"taxon bridges honoured in SPARQL: {len(_bridges)}/{len(_bridges)}, "
              f"Zanthoxylum still excluded: {len(_zan)}/{len(_zan)}")
        print()
        print(f"{'root':<16} {'app':>7} {'sparql':>7} {'agree':>7}  {'diff':>6}")
        print("-" * 50)
        for name, frag in ROOTS.items():
            if frag == "NCBITaxon_2706":
                continue          # bridges asserted above; whole-root parity not claimed
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

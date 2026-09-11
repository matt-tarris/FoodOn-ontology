#!/usr/bin/env python3
"""How far does SPARQL/app parity actually hold?

test/patch_run.py asserts parity on eight roots, chosen because each exercises a
mechanism: the species pivot, a union filler, a supplied `in taxon` link, an UNPINNED
root, a class defined inside a class expression. Eight roots is enough to catch a
regression in those and too few to describe the whole surface -- twice now, adding one
more root has revealed a hole that the eight could not see.

This sweeps every root in data/resolution-store.json instead, and prints what does not
agree. It is a diagnostic, not a test: it runs a ROBOT query over the 46 MB queryable
graph and is not something to put in a commit loop.

    ./tools/apply_patches.sh          # the queryable graph must be current
    python3 build/audit/parity_sweep.py
"""
import sys, json, re, csv, subprocess, tempfile, collections, os

os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, "build")
from traverse import Graph

QUERYABLE = "ontology/foodon-queryable.owl"
if not os.path.exists(QUERYABLE):
    sys.exit(f"missing {QUERYABLE} -- run ./tools/apply_patches.sh first")

g = Graph()
lbl = lambda i: (g.N.get(i, {}) or {}).get("l") or i

roots = {}
for q, e in json.load(open("data/resolution-store.json"))["entries"].items():
    if e.get("status") != "resolved":
        continue
    for r in e.get("roots") or []:
        roots.setdefault(r, lbl(r))
for frag in ("FOODON_00003425", "FOODON_03411312", "NCBITaxon_4070",
             "FOODON_00003324", "NCBITaxon_2706", "FOODON_03411226", "FOODON_00002053"):
    i = "http://purl.obolibrary.org/obo/" + frag
    roots.setdefault(i, lbl(i))
sel = sorted(roots)

q = open("build/sparql/patch_closure.rq").read()
q = re.sub(r"VALUES \?root \{[^}]*\}",
           "VALUES ?root { " + " ".join("obo:" + r.rsplit("/", 1)[-1] for r in sel) + " }", q)
q = q.replace("SELECT DISTINCT ?avoid ?label", "SELECT DISTINCT ?root ?avoid")
q = re.sub(r"OPTIONAL \{ \?avoid rdfs:label \?label \}", "", q)
q = re.sub(r"ORDER BY \?label", "", q)
with tempfile.NamedTemporaryFile("w", suffix=".rq", delete=False) as f:
    f.write(q); qf = f.name
out = tempfile.mktemp(suffix=".csv")
r = subprocess.run(["java", "-Xmx10g", "-jar", "tools/robot.jar", "query",
                    "--input", QUERYABLE, "--query", qf, out],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit("robot query failed:\n" + (r.stderr or "")[-800:])

sp = collections.defaultdict(set)
for row in csv.DictReader(open(out)):
    sp[row["root"]].add(row["avoid"])

print(f"{'root':<34} {'app':>7} {'sparql':>7} {'diff':>6}  direction")
print("-" * 78)
agree = 0
for i in sel:
    py = set(g.closure([i])[0]) - {i}
    s = sp.get(i, set())
    d = len(py ^ s)
    if not d:
        agree += 1
        continue
    way = ("SPARQL under-reports" if (py - s) and not (s - py) else
           "SPARQL over-reports" if (s - py) and not (py - s) else "both")
    print(f"{lbl(i)[:33]:<34} {len(py):>7,} {len(s):>7,} {d:>6}  {way}")
    for x in list(py - s)[:3]:
        print(f"      app only    {lbl(x)}")
    for x in list(s - py)[:3]:
        print(f"      sparql only {lbl(x)}")
print()
print(f"{agree}/{len(sel)} roots at exact parity")
os.unlink(qf)

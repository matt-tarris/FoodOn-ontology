#!/usr/bin/env python3
"""Every governed decision file, checked against the ontology it claims to describe.

The interface validates what it writes. The FILES do not, and both silent mis-writes
in this layer arrived by a script editing JSON directly:

  FOODON:00001040 is `chicken meat food product`, not `mammalian meat food product`
  FOODON:03411318 is `cacao plant`, not `rye plant`

Both are real classes, so nothing objected. The first went unnoticed until a closure
was measured; a red-meat query kept all 828 of its dairy classes in the meantime.

THE CHECK THAT CATCHES THAT ONE is the label/IRI pair: almost every IRI in these files
sits beside a human-readable label, written by the same hand at the same moment, and
when the two disagree the label says what was MEANT and the IRI says what was WRITTEN.
Comparing them costs nothing and would have caught both within seconds.
"""
import json, os, sys, collections

sys.path.insert(0, "build")
from traverse import Graph

g = Graph()
label = lambda i: (g.N.get(i, {}) or {}).get("l")
fails, checks, notes = [], 0, []

# field -> the field holding the label that was meant. Written as pairs because that
# is how they were authored, and the pairing is the only evidence of intent available.
PAIRED = {
    "target_class": "target_label", "class": "class_label", "taxon": "taxon_label",
    "maps_to_iri": "maps_to", "property": "label",
    "query_roots": "query_root_labels", "roots": "root_labels",
    "product": "product_label", "source": "source_label",
}
FILES = ["config/overrides.json", "config/taxon-bridges.json", "config/ingredient-map.json",
         "config/relation_policy.json", "data/mined-classified.json",
         "data/repairs-classified.json", "data/resolution-store.json"]

ONT = "http://purl.obolibrary.org/obo/"


def every_dict(o, where=""):
    if isinstance(o, dict):
        yield where, o
        for k, v in o.items():
            yield from every_dict(v, f"{where}.{k}")
    elif isinstance(o, list):
        for n, x in enumerate(o):
            yield from every_dict(x, f"{where}[{n}]")


for path in FILES:
    if not os.path.exists(path):
        continue
    doc = json.load(open(path))
    for where, d in every_dict(doc):
        for f_iri, f_lab in PAIRED.items():
            if f_iri not in d:
                continue
            iris = d[f_iri] if isinstance(d[f_iri], list) else [d[f_iri]]
            labs = d.get(f_lab)
            labs = labs if isinstance(labs, list) else ([labs] if labs else [])
            for n, iri in enumerate(iris):
                if not isinstance(iri, str) or not iri.startswith(ONT):
                    continue
                checks += 1
                real = label(iri)
                if real is None:
                    fails.append(f"{path}{where}.{f_iri}: {iri} is not a class in "
                                 f"FoodOn {g.meta['version']}")
                    continue
                if g.N[iri].get("dep"):
                    fails.append(f"{path}{where}.{f_iri}: `{real}` is deprecated upstream")
                    continue
                # the pair. This is the check that catches a real-but-wrong IRI.
                if n < len(labs) and labs[n]:
                    checks += 1
                    if str(labs[n]).strip().lower() != real.strip().lower():
                        fails.append(
                            f"{path}{where}: `{f_lab}` says \"{labs[n]}\" but `{f_iri}` "
                            f"points at \"{real}\" -- the label says what was meant and "
                            f"the IRI says what was written")

# ---- vocabularies are closed -------------------------------------------------
ov = json.load(open("config/overrides.json"))
declared_claims = set(ov.get("claim_types") or {}) | {"not_avoidance_relevant"}
declared_types = set(ov.get("entry_types") or {})
for o in ov["overrides"]:
    checks += 1
    if o.get("claim") and o["claim"] not in declared_claims:
        fails.append(f"config/overrides.json: claim `{o['claim']}` is not declared")
    checks += 1
    if o.get("type") and o["type"] not in declared_types:
        fails.append(f"config/overrides.json: entry type `{o['type']}` is not declared")

# ---- a mapping target must be able to match --------------------------------
# 6,087 code-list classes sit outside the traversal by policy. A mapping to one of them
# never fires, and reads as done.
for m in json.load(open("config/ingredient-map.json")).get("mappings", []):
    iri = m.get("maps_to_iri")
    if not iri:
        continue
    checks += 1
    if iri in g.excluded:
        fails.append(f"config/ingredient-map.json: `{m['term']}` maps to "
                     f"`{label(iri)}`, which is in an excluded branch and can never "
                     f"match a query")

# ---- signed means signed ------------------------------------------------------
for path, key, who in [("config/taxon-bridges.json", "signed_off", "signed_off_by"),
                       ("data/mined-classified.json", "signed_off", "signed_off_by")]:
    for e in json.load(open(path)).get(key, []):
        checks += 1
        if not e.get(who):
            fails.append(f"{path}: an entry in `{key}` carries no {who}")

# ---- pins resolve -------------------------------------------------------------
from resolve import Resolver
ix = Resolver(graph=g, store=None).label_ix
for p in json.load(open("config/resolution-pins.json"))["pins"]:
    for lab in p["root_labels"]:
        checks += 1
        if lab.lower() not in ix:
            fails.append(f"config/resolution-pins.json: `{p['query']}` pins to "
                         f"`{lab}`, which FoodOn no longer has")

print(f"{checks:,} assertions over {len(FILES)} decision files, "
      f"FoodOn {g.meta['version']}")
for n in notes:
    print("   note:", n)
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("\nPASS - every IRI names a live class, and every label agrees with its IRI")

#!/usr/bin/env python3
"""Build the normalized typed multigraph every downstream stage runs against.

  data/structure.csv          -> is_a backbone + restriction edges  (build/extract_edges.py logic)
  data/foodon-asserted.obo.json -> labels, synonyms, definitions, deprecation
  -> data/index.json

Edge shape: {s, p, o, k} where k is the edge kind:
    isa      named subclass, incl. genus terms inside logical definitions
    rel      property restriction asserted directly on the class
    rel_nest property restriction nested inside another restriction's filler
             (weaker claim - kept for recall, tagged for a lower confidence tier)
"""
import csv, json, collections

OWL="http://www.w3.org/2002/07/owl#"; RDF="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS="http://www.w3.org/2000/01/rdf-schema#"
SUBCLASS, EQUIV = RDFS+"subClassOf", OWL+"equivalentClass"
INTER, UNION, COMPL = OWL+"intersectionOf", OWL+"unionOf", OWL+"complementOf"
FIRST, REST, NIL = RDF+"first", RDF+"rest", RDF+"nil"
ONPROP = OWL+"onProperty"
FILLERS = {OWL+"someValuesFrom":"some", OWL+"allValuesFrom":"only",
           OWL+"onClass":"card", OWL+"hasValue":"value"}
DESCEND = {INTER, UNION, COMPL, FIRST, REST}
# Which way a named class inside a class expression actually points. Getting this
# wrong inverts the hierarchy, and it did:
#
#   X = A and B   (equiv/intersectionOf)  ->  X subClassOf A, X subClassOf B.
#                                             A and B are PARENTS of X.       5,254
#   X = A or B    (equiv/unionOf)         ->  A subClassOf X, B subClassOf X.
#                                             A and B are CHILDREN of X.         50
#   X = A and (B or C)  (union in inter)  ->  X subClassOf (B or C) and nothing
#                                             about B subClassOf X. Neither.
#   X <= A or B   (sub/unionOf)           ->  says every X is an A or a B, and
#                                             NOTHING about X subClassOf A.       13
#   X <= A and B  (sub/intersectionOf)    ->  A and B are parents.                 8
#
# Reading union operands as parents produced 50 mutual `is_a` pairs -- a mutual
# subclass IS an equivalence, so `nut food product`, `plant seed or nut food product`
# and `plant seed food product` collapsed into one class and a TREE NUT query
# descended into every plant seed: rice, soy, buckwheat and quinoa all came back.
# Same defect for `bell pepper plant` vs its colour variants and `black pepper plant`
# vs `black or white pepper plant`.

triples = collections.defaultdict(list)
for row in csv.DictReader(open("data/structure.csv", newline="", encoding="utf-8")):
    triples[row["s"]].append((row["p"], row["o"]))
po = lambda n: triples.get(n, ())
named = lambda n: not n.startswith("_:")

def walk(top):
    """Yield ('isa', named, nested, via) and ('rel', prop, rtype, filler, nested).

    `via` records the connective the named class was reached through -- "union",
    "inter" or None -- because that decides which way the subsumption points. It is
    sticky: once inside a union, a nested intersection is still under that union.
    """
    out, stack, seen = [], [(top, False, None)], set()
    while stack:
        node, nest, via = stack.pop()
        if (node, nest, via) in seen: continue
        seen.add((node, nest, via))
        if named(node):
            out.append(("isa", node, nest, via)); continue
        props = [o for p, o in po(node) if p == ONPROP]
        if props:
            for p, o in po(node):
                if p in FILLERS:
                    if named(o): out.append(("rel", props[0], FILLERS[p], o, nest))
                    else: stack.append((o, True, via))
            continue
        for p, o in po(node):
            if p not in DESCEND or o == NIL: continue
            # A union INSIDE an intersection is not a top-level union. FoodOn writes
            # `Buffalo wing = prepared chicken wing and (food (baked) or food
            # (deep-fried))`, which entails `Buffalo wing subClassOf (baked or fried)`
            # and NOTHING about `food (baked) subClassOf Buffalo wing`. Treating the
            # operands as children made every baked food a descendant of a chicken
            # dish, so a poultry or egg query swallowed the entire baked-goods tree.
            # Inside an intersection it reads like `X <= A or B`: recall-first, X is
            # under one of them, emitted on the weaker `isa_union` kind.
            if p == UNION:    stack.append((o, nest, "inter_union"
                                            if via == "inter" else "union"))
            elif p == COMPL:  stack.append((o, nest, "compl"))
            elif p == INTER:  stack.append((o, nest, via or "inter"))
            else:             stack.append((o, nest, via))     # rdf:first / rdf:rest
    return out

edges, seen_e = [], set()
def add(s, p, o, k):
    key = (s, p, o, k)
    if key not in seen_e:
        seen_e.add(key); edges.append({"s": s, "p": p, "o": o, "k": k})

for cls in [s for s in triples if named(s)]:
    for pred, obj in po(cls):
        if pred not in (SUBCLASS, EQUIV): continue
        if named(obj):
            add(cls, "isa", obj, "isa"); continue
        for item in walk(obj):
            if item[0] == "isa":
                _, other, nest, via = item
                if via == "compl":
                    continue          # a negation names no parent and no child
                if nest:
                    # Reached from inside a RESTRICTION FILLER, not from a
                    # subsumption operand, so the union direction rule below does not
                    # apply: `blood meal = derives from some (Bos taurus or swine)`
                    # makes neither a parent nor a child of blood meal. Kept on the
                    # weaker `rel_nest` kind exactly as before.
                    add(cls, "isa", other, "rel_nest")
                    continue
                if via == "inter_union":
                    # X = A and (B or C): X is under B or C, we cannot say which
                    add(cls, "isa", other, "isa_union")
                    continue
                if via == "union":
                    if pred == EQUIV:
                        # X = A or B: the operands are SUBCLASSES of X. Emitting the
                        # reverse is what inverted the hierarchy.
                        add(other, "isa", cls, "isa")
                    else:
                        # X <= A or B: no named subsumption follows. Kept as its own
                        # weaker kind rather than dropped, because recall-first still
                        # wants `chia seed (whole or pieces)` reachable from chia --
                        # every X IS one of the operands, we just cannot say which.
                        add(cls, "isa", other, "isa_union")
                    continue
                add(cls, "isa", other, "isa")
            else:
                _, prop, rtype, filler, nest = item
                add(cls, prop, filler, "rel_nest" if nest else "rel")

# ---- metadata from obographs -------------------------------------------------
g = json.load(open("data/foodon-asserted.obo.json"))["graphs"][0]
nodes = {}
for n in g.get("nodes", []):
    meta = n.get("meta", {})
    syns = [s["val"] for s in meta.get("synonyms", []) if s.get("val")]
    d = meta.get("definition", {}).get("val")
    repl = [x["val"] for x in meta.get("basicPropertyValues", [])
            if x.get("pred", "").endswith("IAO_0100001")]
    e = {}
    if n.get("lbl"): e["l"] = n["lbl"]
    if syns: e["syn"] = syns
    if d: e["def"] = d
    if meta.get("deprecated"): e["dep"] = 1
    if repl: e["repl"] = repl[0]
    nodes[n["id"]] = e

for e in edges:
    for x in (e["s"], e["o"]):
        nodes.setdefault(x, {})
    nodes.setdefault(e["p"], {})

def ns(iri):
    t = iri.rsplit("/", 1)[-1]
    return t.split("_", 1)[0] if "_" in t else (t.split(":", 1)[0] if ":" in t else "?")
for i, e in nodes.items():
    e["ns"] = ns(i)

out = {
    "meta": {
        "ontology": "FoodOn",
        "version": "2025-12-30",
        "source_sha256": open("ontology/foodon.owl.sha256").read().split()[0],
        "built_by": "build/build_index.py",
    },
    "nodes": nodes,
    "edges": edges,
}
json.dump(out, open("data/index.json", "w"), separators=(",", ":"))

kinds = collections.Counter(e["k"] for e in edges)
preds = collections.Counter(e["p"] for e in edges if e["k"] != "isa")
lbl = lambda i: nodes.get(i, {}).get("l", i)
print(f"nodes {len(nodes):,}   edges {len(edges):,}   {dict(kinds)}")
print(f"deprecated {sum(1 for v in nodes.values() if v.get('dep')):,}")
print("\ntop relations:")
for p, c in preds.most_common(10):
    print(f"  {c:>6}  {lbl(p)}")

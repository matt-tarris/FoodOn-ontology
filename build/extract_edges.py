#!/usr/bin/env python3
"""Reconstruct every property restriction owned by a named class.

Input : data/structure.csv  (flat structural triples, see build/sparql/structure.rq)
Output: data/restrictions.csv

Why not obographs: it silently drops ~1,440 restrictions, including 449
`derives from` (audit F2). Why not SPARQL property paths: the fully general query
is quadratic on this ontology and does not terminate in reasonable time. This walk
is linear, explicit, and cycle-safe.

`nested` marks a restriction found inside another restriction's filler rather than
asserted directly on the class. That is a weaker claim -- `A subClassOf (has_part
some (B and derives_from some C))` does not assert that A derives from C -- so it is
kept but tagged, for a lower confidence tier downstream rather than silent loss.
"""
import csv, sys, collections

OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"

SUBCLASS, EQUIV = RDFS + "subClassOf", OWL + "equivalentClass"
INTER, UNION, COMPL = OWL + "intersectionOf", OWL + "unionOf", OWL + "complementOf"
FIRST, REST, NIL = RDF + "first", RDF + "rest", RDF + "nil"
ONPROP = OWL + "onProperty"
FILLERS = {OWL + "someValuesFrom": "some", OWL + "allValuesFrom": "only",
           OWL + "onClass": "card", OWL + "hasValue": "value"}

# structural edges we descend through without leaving the same class expression
DESCEND = {INTER, UNION, COMPL, FIRST, REST}

triples = collections.defaultdict(list)
with open("data/structure.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        triples[row["s"]].append((row["p"], row["o"]))

def po(node):
    return triples.get(node, ())

def is_named(n):
    return not n.startswith("_:")

def collect(top, out, nested, seen):
    """Walk one class expression, emitting (prop, rtype, filler, nested)."""
    stack = [(top, nested)]
    while stack:
        node, nest = stack.pop()
        key = (node, nest)
        if key in seen:
            continue
        seen.add(key)

        props = [o for p, o in po(node) if p == ONPROP]
        if props:
            for p, o in po(node):
                if p in FILLERS:
                    if is_named(o):
                        out.append((props[0], FILLERS[p], o, nest))
                    else:
                        # filler is itself an expression -- anything inside it is
                        # nested, not asserted of this class
                        stack.append((o, True))
            continue

        for p, o in po(node):
            if p in DESCEND and o != NIL:
                stack.append((o, nest))

rows = []
named_subjects = {s for s in triples if is_named(s)}
for cls in named_subjects:
    for p, o in po(cls):
        if p not in (SUBCLASS, EQUIV):
            continue
        axiom = "subClassOf" if p == SUBCLASS else "equivalentClass"
        found = []
        collect(o, found, False, set())
        for prop, rtype, filler, nest in found:
            rows.append((cls, axiom, prop, rtype, filler, "true" if nest else "false"))

rows = sorted(set(rows))
with open("data/restrictions.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["cls", "axiom", "prop", "rtype", "filler", "nested"])
    w.writerows(rows)

direct = sum(1 for r in rows if r[5] == "false")
print(f"restrictions attributed : {len(rows):,}  (direct {direct:,} / nested {len(rows)-direct:,})")

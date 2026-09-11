#!/usr/bin/env python3
"""Avoidance traversal over FoodOn.

Given one or more resolved root classes, return every class that should be treated
as "contains this", with the path evidence for each.

THE INVARIANT (spec section 2)
------------------------------
The traversal never moves toward a more general class. It is enforced structurally,
not by a check: the adjacency map is built once, and it only ever contains edges
pointing in the avoidance-propagating direction. There is no code path that ascends,
so no configuration mistake can create one.

  - rdfs:subClassOf is indexed parent -> child only. Child -> parent is never added.
  - every other relation is indexed in the single direction declared by
    config/relation_policy.json. "both" is not an accepted value.

Consequence: corn cannot reach wheat. Reaching wheat would require climbing from
`field corn plant` to a shared ancestor (`starch-producing plant`, or Poaceae) and
descending again, and the upward half of that walk does not exist in the graph.

TWO PHASES (spec section 4)
---------------------------
A class-level query ("allium") needs taxonomic descent to its members before
derivative traversal makes sense. A single uniform walk either stops at the member
list or tangles the two. So:

  phase 1  taxonomic: descend is_a from the roots, collecting member organisms/taxa
  phase 2  derivative: from every node phase 1 reached, follow propagating relations
                       and descend is_a again from whatever they reach

For a leaf query ("edamame") phase 1 is a no-op and phase 2 does the work, so the
same code path serves both without branching on query kind.
"""
import json, collections

AGENCY_ROOT = "http://purl.obolibrary.org/obo/FOODON_03400361"
ISA = "isa"


class Graph:
    def __init__(self, index="data/index.json", repairs="data/repairs-classified.json",
                 policy="config/relation_policy.json", overrides="config/overrides.json",
                 mined="data/mined-classified.json",
                 taxon_bridges="config/taxon-bridges.json"):
        ix = json.load(open(index))
        self.N = ix["nodes"]
        self.meta = ix["meta"]
        pol = json.load(open(policy))
        self.policy = pol

        self.prop_dir = {r["property"]: r["direction"] for r in pol["propagating_relations"]}
        self.prop_conf = {r["property"]: r["confidence"] for r in pol["propagating_relations"]}
        self.rel_label = {r["property"]: r["label"] for r in
                          pol["propagating_relations"] + pol["non_propagating_relations"]}

        edges = list(ix["edges"])
        self.repair_conf = {}
        if repairs:
            for a in json.load(open(repairs))["auto_apply"]:
                key = (a["product"], a["source"])
                self.repair_conf[key] = a.get("confidence", "high")
                edges.append({"s": a["product"], "o": a["source"],
                              "p": "http://purl.obolibrary.org/obo/RO_0001000", "k": "repair"})

        # Bridges from build/classify_mined.py: FoodOn's own prose, or a naming
        # pattern the label-convention rule cannot see. ONLY the `signed_off` list is
        # read — a candidate awaiting review is not an axiom, and reading the queue
        # would make the review meaningless. Kept as its own provenance rather than
        # folded into `repair` because the evidence differs in kind: a repair follows
        # from FoodOn's structure under automatic guards, a mined bridge follows from
        # an English sentence that a person then signed.
        self.mined_conf = {}
        self.mined = []
        try:
            for a in json.load(open(mined))["signed_off"]:
                key = (a["product"], a["source"])
                self.mined_conf[key] = a.get("confidence", "medium")
                self.mined.append(a)
                edges.append({"s": a["product"], "o": a["source"], "k": "mined",
                              "p": ISA if a.get("relation") == "is a"
                                   else "http://purl.obolibrary.org/obo/RO_0001000"})
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            pass
        # Missing `in taxon` links on plant classes. A third kind of gap, and it needs
        # its own file because it is neither a naming convention nor a sentence in a
        # definition: FoodOn asserts `<X> plant in_taxon <species>` for some members of
        # a genus and omits it for others, and the omission is invisible until a query
        # comes up short. The citrus case is 17 plant classes hanging off `citrus
        # family` -- which is Rutaceae, above the genus, and so unreachable without
        # ascending -- of which six carry the link and eleven do not.
        #
        # Emitted as the ontology's OWN property, RO:0002162, rather than as a local
        # one. That is the whole point: a consumer with the merged graph gets these
        # through the same path it already walks for `grapefruit plant`, and the
        # SPARQL materialiser needs no new branch. ONLY `signed_off` is read.
        self.taxon_bridges = []
        try:
            for b in json.load(open(taxon_bridges))["signed_off"]:
                if not b.get("taxon") or not b.get("signed_off_by"):
                    continue
                self.taxon_bridges.append(b)
                edges.append({"s": b["class"], "o": b["taxon"], "k": "taxon",
                              "p": "http://purl.obolibrary.org/obo/RO_0002162"})
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            pass

        if isinstance(overrides, str):
            try: self.overrides = json.load(open(overrides))
            except (FileNotFoundError, json.JSONDecodeError): self.overrides = {"overrides": []}
        else:
            self.overrides = overrides or {"overrides": []}

        # excluded branch: computed from asserted is_a before anything else
        kids = collections.defaultdict(list)
        for e in edges:
            if e["p"] == ISA:
                kids[e["o"]].append(e["s"])
        # Excluded branches come from config/relation_policy.json, not from a constant
        # here. The agency root used to be hardcoded while the policy file listed it
        # as documentation, so the file described a rule the code did not read -- and
        # a second branch could not be added without editing code. AGENCY_ROOT stays
        # as a module constant because test/run.py asserts on it directly.
        roots_x = [b["class"] for b in pol.get("excluded_branches", [])] or [AGENCY_ROOT]
        self.excluded = set()
        for r0 in roots_x:
            st = [r0]
            while st:
                x = st.pop()
                for c in kids.get(x, ()):
                    if c not in self.excluded:
                        self.excluded.add(c); st.append(c)
            self.excluded.add(r0)

        # Terminal namespaces: reachable, but never expanded from. Keeps a ChEBI
        # class that is a genuine label item (sucrose, maltodextrin) in the graph
        # while stopping descent into molecular structure below it.
        self.terminal_ns = {t["namespace"] for t in pol.get("terminal_namespaces", [])}

        # ---- adjacency, built in the avoidance direction ONLY -------------------
        self.children = collections.defaultdict(list)   # phase 1 + descent
        self.derive = collections.defaultdict(list)     # phase 2
        self.taxon_of = collections.defaultdict(list)   # root expansion only
        for e in edges:
            s, o, p = e["s"], e["o"], e["p"]
            if s in self.excluded or o in self.excluded:
                continue
            if p == ISA:
                # parent -> child. The reverse is deliberately never indexed.
                # An is_a supplied by a signed mined bridge keeps its own provenance;
                # hardcoding "ontology" here would have passed it off as FoodOn's.
                k = e.get("k")
                self.children[o].append((s, ISA, k or "ontology",
                                         self.mined_conf.get((s, o), "high")
                                         if k == "mined" else "high"))
                continue
            d = self.prop_dir.get(p)
            if d is None:
                continue                                 # non-propagating
            prov = e.get("k") or "ontology"
            conf = (self.repair_conf.get((s, o), "high") if prov == "repair"
                    else self.mined_conf.get((s, o), "medium") if prov == "mined"
                    else self.prop_conf.get(p, "medium"))
            if p.endswith("RO_0002162"):
                # kept separately: used only to pivot a ROOT to its own species
                # taxon, never as a general traversal direction
                self.taxon_of[s].append((o, p, prov, conf))
            if d == "inverse":
                self.derive[o].append((s, p, prov, conf))
            elif d == "forward":
                self.derive[s].append((o, p, prov, conf))
            else:
                raise ValueError(f"direction {d!r} for {p}: only inverse/forward are safe")

        # section 6 rollup: `member of` is non-propagating but its US CFR targets are
        # ready-made culinary-function groupings (nutritive sweetener, milled grain or
        # starch product, ...). Carried as a view-layer tag; the graph keeps full fidelity.
        # readable grouping vocabulary over the raw CFR labels (audit: the CFR
        # groups are 170 uneven categories mixing ingredient function with product
        # type; config/function-categories.json folds them into 17 readable ones)
        try:
            fc = json.load(open("config/function-categories.json"))
            self.fn_map = fc["mapping"]
            self.fn_cat = fc["categories"]
        except (FileNotFoundError, json.JSONDecodeError):
            self.fn_map, self.fn_cat = {}, {}

        MEMBER_OF = "http://purl.obolibrary.org/obo/RO_0002350"
        self.rollup = collections.defaultdict(list)
        for e in edges:
            if e["p"] == MEMBER_OF and e["s"] not in self.excluded:
                self.rollup[e["s"]].append(e["o"])

        # `remove` overrides: an edge or subtree that is ontologically real but not
        # avoidance-relevant for a particular query. Keyed by query root so it
        # suppresses only where it applies, never globally.
        self.suppress = collections.defaultdict(set)
        for ov in self.overrides.get("overrides", []):
            if ov.get("type") == "remove" and ov.get("reviewed_by"):
                if ov.get("query_root") and ov.get("target_class"):
                    self.suppress[ov["query_root"]].add(ov["target_class"])

        # `add` overrides hang off the query's RESOLVED ROOTS. An earlier version
        # indexed them on the query label ("Corn"), a key the traversal never visits,
        # so every add override was silently inert. test/override_run.py now asserts
        # that a reviewed override actually shows up in the graph.
        #
        # ONLY `contains` ENTERS THE CLOSURE. The closure means one thing — treat this
        # as containing the query — and the other three claim types are, by their own
        # definitions in config/overrides.json, not that:
        #
        #   may_contain     "feedstock is a producer choice". Corn-derived citric acid
        #                   is corn-derived at SOME producers. Asserting containment
        #                   tells a corn-avoider that citric acid contains corn, which
        #                   is not a fact about the substance.
        #   cross_reactive  "the allergen protein is NOT present." Containment here is
        #                   wrong in the dangerous direction: it excludes safe food.
        #   disputed        "no established containment basis."
        #   shared_compound the same molecule reached by two routes. Citric acid is
        #                   what citrus is named for and is the usual trigger in
        #                   citrus INTOLERANCE, but commercial citric acid is
        #                   Aspergillus niger fermentation -- so `contains` would be
        #                   false, and the ten imitation-citrus beverages in its
        #                   closure are formulated with it precisely to contain no
        #                   citrus. Reported, so an intolerance is supported without
        #                   asserting a derivation that is not there.
        #
        # Every one of them was previously injected exactly like `contains`, which is
        # what test/allergen_run.py was failing on: 11 terms reached by traversal that
        # only a weaker claim supports. They are not dropped — they are collected here
        # and reported alongside the graph, with the claim and the reason attached, so
        # the weaker basis stays visible instead of being laundered into an edge.
        self.override_edges = []
        self.weak_claims = collections.defaultdict(list)
        for ov in self.overrides.get("overrides", []):
            if ov.get("type") != "add" or not ov.get("reviewed_by"):
                continue
            if ov.get("annotation_only"):
                continue          # no FoodOn class to point at; surfaced as text
            tgt = ov.get("target_class")
            if not tgt or tgt not in self.N:
                continue          # nothing in FoodOn to point at
            if ov.get("claim") != "contains":
                for root in ov.get("query_roots") or []:
                    self.weak_claims[root].append(ov)
                continue
            for root in ov.get("query_roots") or []:
                self.derive[root].append(
                    (tgt, "override", "override", ov.get("confidence", "medium")))
                self.override_edges.append((root, tgt, ov.get("claim")))

    # ---------------------------------------------------------------------
    def expand_roots(self, roots):
        """Add classes denoting the SAME organism in a parallel hierarchy.

        FoodOn splits one organism across hierarchies that share no terms: the
        nightshade case needs both NCBITaxon `Solanaceae` and FoodOn `solanaceae
        plant`; allium needs both NCBITaxon `allium` and FoodOn `allium species`
        (audit F4). Hardcoding the pair per query is the special-casing the spec
        forbids, so the correspondence is derived two ways:

          taxon pivot      root --in taxon--> T, where T is SPECIES RANK. Species
                           rank is required: pivoting to a genus or family would
                           silently widen the query to a broader organism, which is
                           generalisation by another name. `peanut plant` -> Arachis
                           hypogaea is lateral; a pivot to Poaceae would not be.
          label convention FoodOn names its own copy of a taxon `<taxon> species`
                           / `<taxon> plant`. Same convention the repair pass uses.

        Both moves are lateral - same organism, different hierarchy - so neither
        weakens the no-ascent invariant.
        """
        import re
        BINOMIAL = re.compile(r"^[A-Z][a-z]+(?: x)? [a-z][a-z-]+")
        by_label = {}
        for i, v in self.N.items():
            l = (v.get("l") or "").lower()
            if l and not v.get("dep") and i not in self.excluded:
                by_label.setdefault(l, i)

        added = {}
        for r in roots:
            for nxt, rel, _p, _c in self.taxon_of.get(r, ()):
                if BINOMIAL.match(self.label(nxt)):
                    added.setdefault(nxt, ("taxon pivot", r))
            base = self.label(r).lower()
            # add the suffix: NCBITaxon `Solanaceae` -> FoodOn `solanaceae plant`
            for suffix in ("species", "plant", "food product"):
                cand = by_label.get(f"{base} {suffix}")
                if cand and cand not in roots:
                    added.setdefault(cand, ("label convention", r))
            # and strip it, so the correspondence works from either side:
            # FoodOn `solanaceae plant` -> NCBITaxon `Solanaceae`
            for suffix in (" species", " plant", " food product"):
                if base.endswith(suffix):
                    cand = by_label.get(base[: -len(suffix)])
                    if cand and cand not in roots:
                        added.setdefault(cand, ("label convention (stripped)", r))
        return added

    def edges_for_scoring(self):
        """IRIs that act as a derivation source, for resolver scoring."""
        DERIVES = "http://purl.obolibrary.org/obo/RO_0001000"
        IN_TAXON = "http://purl.obolibrary.org/obo/RO_0002162"
        for tgt, lst in self.derive.items():
            for _s, p, _pr, _c in lst:
                if p in (DERIVES, IN_TAXON):
                    yield tgt

    def is_terminal(self, i, roots=()):
        """Terminal namespaces stop traversal from EXPANDING through a node it
        reached. A root is different: the user asked for it explicitly, so a query
        for `sulfites` must still descend to sulfite salt and sodium sulfite. The
        boundary exists to stop a food query sliding into molecular structure, not
        to make chemistry unqueryable."""
        if i in roots: return False
        return self.N.get(i, {}).get("ns") in self.terminal_ns

    def label(self, i): return self.N.get(i, {}).get("l", "") or ""
    def deprecated(self, i): return bool(self.N.get(i, {}).get("dep"))

    # -------------------------------------------------------------------------
    def closure(self, roots, max_depth=12, max_derive=12, _no_suppress=False):
        """Return (nodes, edges). Nodes merge across paths and across roots.

        The two budgets are RUNAWAY GUARDS, not policy. Every query saturates well
        inside them -- `peppers` at 8, `shellfish` and `tree nut` at 10, everything
        else at 6 -- and the whole set runs in 0.01-0.03s, so the cap costs nothing
        and only exists so a future cyclic release cannot spin.

        They were 6, and that was cutting real answers off silently. `pepper` is a
        shallow grouping over a deep taxonomy, so at 6 it lost jalapeno, pimiento,
        guajillo, pasilla, anaheim, cubanelle and 13 more actual peppers, and
        `tree nut` lost 671 classes. Depth in FoodOn's taxonomy is an artefact of how
        finely a branch happens to be subdivided; it is not a statement about
        relevance, and truncating on it hands back a shorter answer with nothing on
        screen to say it was shortened.
        """
        roots = [r for r in roots if r not in self.excluded]
        # Subtrees suppressed for THIS query, per reviewed `remove` overrides.
        # Suppressing the target NODE is not enough: peanut products reach a tree-nut
        # query through `nut food product` without passing through `peanut plant` at
        # all. What must be removed is everything that IS peanut -- which is exactly
        # the target's own avoidance closure, computed the same way any query is.
        suppressed = set()
        if not _no_suppress:
            for r in roots:
                for tgt in self.suppress.get(r, ()):
                    sub, _ = self.closure([tgt], max_depth=max_depth,
                                          max_derive=max_derive, _no_suppress=True)
                    suppressed |= set(sub)
            suppressed -= set(roots)
        self.last_suppressed = suppressed
        expanded = self.expand_roots(roots)
        roots = list(roots) + [r for r in expanded if r not in roots]
        self.last_expansion = {self.label(k): v[0] for k, v in expanded.items()}
        self.last_roots = list(roots)
        nodes = {}
        out_edges = {}
        for r in roots:
            nodes[r] = {"iri": r, "label": self.label(r), "depth": 0, "roots": {r},
                        "phase": "root", "confidence": "high"}

        def note(src, dst, rel, prov, conf, phase, depth, root):
            if dst in suppressed: return
            key = (src, dst, rel, prov)
            if key not in out_edges:
                out_edges[key] = {"source": src, "target": dst, "relation": rel,
                                  "relation_label": (self.rel_label.get(rel)
                                                     or ("is a" if rel == ISA else rel)),
                                  "provenance": prov, "confidence": conf}
            n = nodes.get(dst)
            if n is None:
                nodes[dst] = {"iri": dst, "label": self.label(dst), "depth": depth,
                              "roots": {root}, "phase": phase, "confidence": conf}
            else:
                n["depth"] = min(n["depth"], depth)
                n["roots"].add(root)

        # ---- phase 1: taxonomic descent ----------------------------------------
        # The species-rank taxon pivot applies to every member reached here, not just
        # to the roots: `white mustard plant --in taxon--> Sinapis alba` is the same
        # organism named in the other hierarchy, exactly as at the root. Still
        # rank-guarded, so it can never widen to a genus or family.
        import re as _re
        _BINOMIAL = _re.compile(r"^[A-Z][a-z]+(?: x)? [a-z][a-z-]+")

        members = collections.defaultdict(set)   # node -> roots that reached it
        for r in roots:
            seen = {r}
            frontier = [(r, 0)]
            members[r].add(r)
            while frontier:
                x, d = frontier.pop()
                if d >= max_depth or self.is_terminal(x, roots): continue
                for c, rel, prov, conf in self.children.get(x, ()):
                    if c in seen or c in suppressed: continue
                    seen.add(c)
                    note(x, c, rel, prov, conf, "taxonomic", d + 1, r)
                    members[c].add(r)
                    frontier.append((c, d + 1))
                for t, rel, prov, conf in self.taxon_of.get(x, ()):
                    if t in seen or not _BINOMIAL.match(self.label(t)): continue
                    seen.add(t)
                    note(x, t, rel, prov, conf, "taxonomic", d + 1, r)
                    members[t].add(r)
                    frontier.append((t, d + 1))

        # ---- phase 2: derivative traversal from every phase-1 node -------------
        # The budget is counted from the phase-1 node, NOT from the query root, and
        # it is a separate budget from `max_depth`. Sharing one was a silent
        # false-negative generator: `hungarian wax pepper plant` sits at depth 6
        # under `pepper`, so a shared budget of 6 was already spent by the time the
        # taxonomy got there and its food products were never looked at. A `pepper`
        # query returned 147 classes and no paprika while the NARROWER `Capsicum`
        # returned 177 and found it -- a broader query seeing less than a narrower
        # one, with nothing on screen to say so. How deep an organism happens to sit
        # in FoodOn's taxonomy is not a statement about its derivatives.
        for start, srcroots in list(members.items()):
            base = nodes.get(start, {}).get("depth", 0)
            for root in srcroots:
                seen = {start}
                frontier = [(start, 0)]          # hops taken WITHIN this phase
                while frontier:
                    x, k = frontier.pop()
                    if k >= max_derive or self.is_terminal(x, roots): continue
                    for nxt, rel, prov, conf in self.derive.get(x, ()):
                        if nxt in seen or nxt in suppressed: continue
                        seen.add(nxt)
                        note(x, nxt, rel, prov, conf, "derivative", base + k + 1, root)
                        frontier.append((nxt, k + 1))
                        # descend is_a from anything a relation reached
                        sub = [(nxt, k + 1)]
                        while sub:
                            y, ky = sub.pop()
                            if ky >= max_derive or self.is_terminal(y, roots): continue
                            for c, r2, p2, c2 in self.children.get(y, ()):
                                if c in seen or c in suppressed: continue
                                seen.add(c)
                                note(y, c, r2, p2, conf, "derivative", base + ky + 1, root)
                                sub.append((c, ky + 1))
                                frontier.append((c, ky + 1))

        for n in nodes.values():
            n["roots"] = sorted(n["roots"])
            n["convergent"] = len(n["roots"]) > 1
        return nodes, list(out_edges.values())

    def to_json_graph(self, query, roots, nodes, edges):
        """Spec section 4 output. Full fidelity: rollup is a tag, never a filter."""
        def curie(i):
            t = i.rsplit("/", 1)[-1]
            return t.replace("_", ":", 1) if "_" in t else t
        # section 5 wants multi-path convergence visually distinct, which needs
        # in-degree and the variety of relations arriving, not just cross-root reach
        indeg = collections.Counter(e["target"] for e in edges)
        inrels = collections.defaultdict(set)
        for e in edges:
            inrels[e["target"]].add(e["relation_label"])

        out_nodes = []
        for iri, n in sorted(nodes.items(), key=lambda kv: kv[1]["label"]):
            groups = [{"iri": g, "label": self.label(g)} for g in self.rollup.get(iri, [])]
            cat = next((self.fn_map.get(x["label"]) for x in groups
                        if self.fn_map.get(x["label"])), None)
            out_nodes.append({
                "iri": iri, "curie": curie(iri), "label": n["label"],
                "depth": n["depth"], "phase": n["phase"],
                "confidence": n["confidence"],
                "is_root": iri in roots,
                "roots": [self.label(r) for r in n["roots"]],
                "convergent": n["convergent"],
                "in_degree": indeg.get(iri, 0),
                "incoming_relations": sorted(inrels.get(iri, ())),
                "multi_path": indeg.get(iri, 0) > 1,
                "rollup_groups": groups,
                "function_category": (
                    {"key": cat, **self.fn_cat[cat]} if cat and cat in self.fn_cat else None),
                "definition": self.N.get(iri, {}).get("def"),
                "synonyms": self.N.get(iri, {}).get("syn", []),
            })
        return {
            "query": query,
            "ontology_version": self.meta["version"],
            "relation_policy_version": self.policy["version"],
            "roots": [{"iri": r, "curie": curie(r), "label": self.label(r)} for r in roots],
            "root_expansion": getattr(self, "last_expansion", {}),
            "counts": {
                "nodes": len(out_nodes), "edges": len(edges),
                "convergent_across_roots": sum(1 for n in out_nodes if n["convergent"]),
                "multi_path": sum(1 for n in out_nodes if n["multi_path"]),
                "by_provenance": dict(collections.Counter(e["provenance"] for e in edges)),
                "by_confidence": dict(collections.Counter(e["confidence"] for e in edges)),
            },
            "nodes": out_nodes,
            "edges": sorted(edges, key=lambda e: (e["source"], e["target"])),
        }

    def resolve_label(self, text):
        t = text.strip().lower()
        return [i for i, v in self.N.items()
                if (v.get("l") or "").lower() == t and not v.get("dep") and i not in self.excluded]


if __name__ == "__main__":
    import sys
    g = Graph()
    q = sys.argv[1:] or ["Maize plant"]
    roots = [i for t in q for i in g.resolve_label(t)]
    if not roots:
        print(f"no exact label match for {q}"); raise SystemExit(1)
    nodes, edges = g.closure(roots)
    roots = list(roots) + [i for i in g.resolve_label("") if False]
    allroots = [r for r in nodes if nodes[r]["depth"] == 0]
    graph = g.to_json_graph(" ".join(q), allroots, nodes, edges)
    import os, re as _re
    slug = _re.sub(r"[^a-z0-9]+", "-", " ".join(q).lower()).strip("-")
    path = f"data/graph-{slug}.json"
    json.dump(graph, open(path, "w"), indent=2)
    c = graph["counts"]
    print(f"query  : {graph['query']}")
    print(f"roots  : {[r['label'] for r in graph['roots']]}   expansion: {graph['root_expansion']}")
    print(f"nodes  : {c['nodes']:,}   edges: {c['edges']:,}   "
          f"cross-root: {c['convergent_across_roots']}   multi-path: {c['multi_path']}")
    print(f"provenance: {c['by_provenance']}   confidence: {c['by_confidence']}")
    rolled = sum(1 for n in graph["nodes"] if n["rollup_groups"])
    print(f"nodes with a rollup group: {rolled}")
    print(f"-> {path}")

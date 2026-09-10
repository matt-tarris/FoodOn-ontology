#!/usr/bin/env python3
"""Free-text -> FoodOn class resolution.

Design follows what the ontology actually turned out to be like, not a generic
entity-linking recipe:

STAGE 1  lexical candidate generation over labels and synonyms, including FoodOn's
         own source-form conventions (`<q> plant`, `<q> species`) and its
         preparation-state parentheses (`paprika (ground)`).

STAGE 2  STRUCTURAL scoring. This is the part specific to this project. A query root
         is only useful if it can actually seed a traversal, so candidates are scored
         on whether they are a derivation SOURCE and whether they yield a non-trivial
         closure -- not on string similarity alone. That is what separates
         `fish species` from `Chondrichthyes`, which is a lexical synonym of "fish"
         and also badly wrong (cartilaginous fish only).

STAGE 3  offline LLM adjudication, for terms stage 1-2 cannot resolve. Nothing calls
         an LLM at query time: decisions are frozen into data/resolution-store.json
         and reused, per spec 2a.

Three outcomes, all first class. `absent` matters because 61% of the real allergen
vocabulary has no FoodOn class at all -- silently resolving those to something
approximate is the worst available behaviour for a safety tool.
"""
import json, re, sys, collections, math

sys.path.insert(0, "build")
from traverse import Graph

PREP = re.compile(r"\s*\(([^)]*)\)\s*$")

class Resolver:
    def __init__(self, graph=None, store="data/resolution-store.json"):
        self.g = graph or Graph()
        g = self.g
        self.store_path = store
        try:
            self.store = json.load(open(store)) if store else {"entries": {}}
        except (FileNotFoundError, json.JSONDecodeError):
            self.store = {"version": "1", "entries": {}}

        self._clo_cache, self._twin_cache = {}, {}
        self.label_ix = {}
        self.syn_ix = collections.defaultdict(list)
        self.bare_ix = collections.defaultdict(list)   # label minus "(...)" suffix
        for i, v in g.N.items():
            if v.get("dep") or i in g.excluded: continue
            l = (v.get("l") or "").lower()
            if not l: continue
            self.label_ix.setdefault(l, i)
            bare = PREP.sub("", l)
            if bare != l: self.bare_ix[bare].append(i)
            for s in v.get("syn", []):
                self.syn_ix[s.lower().strip()].append(i)

        # structural signals
        self.is_source = collections.Counter()
        for e in g.edges_for_scoring():
            self.is_source[e] += 1

    # ---- scoring ------------------------------------------------------------
    def closure_size(self, iri, cap=4000):
        try:
            return len(self.g.closure([iri], max_depth=4)[0])
        except Exception:
            return 0

    def candidates(self, query):
        q = query.strip().lower()
        q = re.sub(r"\s+", " ", q)
        out = {}
        def add(iri, why, base):
            if iri is None: return
            prev = out.get(iri)
            if prev is None or base > prev[1]:
                out[iri] = (why, base)

        if q in self.label_ix: add(self.label_ix[q], "exact label", 100)
        # FoodOn's canonical source forms
        for suf, pts in (("plant", 92), ("species", 90), ("tree", 88),
                         ("animal", 88), ("food product", 70)):
            k = f"{q} {suf}"
            if k in self.label_ix: add(self.label_ix[k], f"source form '{suf}'", pts)
        for i in self.syn_ix.get(q, []): add(i, "synonym", 62)
        for i in self.bare_ix.get(q, []): add(i, "preparation variant", 45)
        # singular/plural
        for alt in ({q[:-1]} if q.endswith("s") else {q + "s"}):
            if alt in self.label_ix: add(self.label_ix[alt], "plural form", 84)
            for i in self.syn_ix.get(alt, []): add(i, "synonym (plural)", 58)
        return out

    def score(self, query):
        cands = self.candidates(query)
        scored = []
        for iri, (why, base) in cands.items():
            n = self.closure_size(iri)
            src = self.is_source.get(iri, 0)
            s = base
            s += min(30, 10 * math.log10(n + 1))       # viability: can it seed a walk
            s += min(14, 2 * math.log10(src + 1) * 7)  # is it a derivation source
            if PREP.search(self.g.label(iri).lower()): s -= 18   # prefer the base form
            scored.append({"iri": iri, "label": self.g.label(iri), "why": why,
                           "closure": n, "source_edges": src, "score": round(s, 1)})
        scored.sort(key=lambda c: -c["score"])
        return scored

    # A resolution can be lexically unambiguous and still useless: FoodOn's
    # `tree nut` class contains only itself and `almond kernel (raw)`, so resolving
    # "tree nut" to it succeeds and returns nothing. There is no structural rule
    # separating a stub category from a genuine leaf -- `edamame` is legitimately
    # closure 1 -- so this is flagged for the offline pass rather than guessed at.
    VIABILITY_FLOOR = 3

    def head_alternatives(self, query, best_closure):
        """Larger classes sharing the query's head noun. Advisory only: they are
        NOT auto-selected, because `black pepper` -> `pepper` would be wrong."""
        toks = query.strip().lower().split()
        if len(toks) < 2: return []
        head = toks[-1]
        alts = []
        for lab, i in self.label_ix.items():
            if lab == query.strip().lower(): continue
            if head in lab.split():
                n = self.closure_size(i)
                if n > max(20, best_closure * 10):
                    alts.append({"iri": i, "label": self.g.label(i), "closure": n})
        alts.sort(key=lambda a: -a["closure"])
        return alts[:5]

    # ---- facet merge --------------------------------------------------------
    # A cuisine query names an INGREDIENT, and FoodOn splits every ingredient across
    # up to four classes: the plant, the food, the `<X> food product` grouping and
    # the NCBITaxon taxon. `tomato plant` / `tomato` / `tomato food product` /
    # `Solanum lycopersicum` are not competing SENSES, they are facets of one thing --
    # and they returned the identical 164-class closure. Scored against each other
    # they sat 1.8 points apart, under the margin, so the query came back `ambiguous`
    # and the user got nothing. The resolver was asking "which one?" where the answer
    # is "those are the same thing".
    #
    # Genuine ambiguity is a different shape: `strawberry` vs `strawberry tree`
    # (Arbutus unedo), `bean` across Phaseolus / Vicia / Glycine, `prawn` across four
    # species. Those must still be held for sign-off.
    #
    # Two tests decide it, and the first is not a heuristic:
    #
    #   identical closures    a proof that the choice cannot change the answer. If two
    #                         candidate roots reach the same set, picking either or
    #                         both is the same query.
    #   parallel hierarchy    expand_roots links them -- the species-rank taxon pivot
    #                         or FoodOn's own label convention, already trusted
    #                         elsewhere for exactly this (audit F4).
    #
    # SUBSUMPTION IS DELIBERATELY NOT ACCEPTED, and the reason is worth stating
    # because it is the obvious third test. Measured across 30 cuisine terms, "one
    # closure contains the other" would merge 70 candidate pairs -- and almost all of
    # them differ by taxonomic RANK, not by facet: `Ocimum` (16) contains
    # `Ocimum basilicum` (11), `pepper` (176) contains `bell pepper` (45), `Coffea`
    # (6) contains `Coffea arabica` (2). Accepting it silently widens a query from a
    # species to its genus, which is exactly the shape config/repair-signoff.json
    # declines by name: `avian food product -> avian animal` was rejected as
    # "class-rank (Aves): 319-node source subtree would link all avian food to all
    # birds". A resolver may not do quietly what the repair pass refuses to do
    # explicitly.
    #
    # Note it is NOT rejected because of `strawberry tree`. That closure is
    # {Arbutus unedo, strawberry tree} and is entirely DISJOINT from `strawberry`, so
    # subsumption would never have merged it. The trap it guards is the rank one.
    #
    # Only the longest PREFIX of pairwise-compatible candidates merges, which is what
    # keeps the traps out: `strawberry` merges 2 and leaves `strawberry tree` behind.
    def _closure_of(self, iri):
        if iri not in self._clo_cache:
            self._clo_cache[iri] = frozenset(self.g.closure([iri])[0])
        return self._clo_cache[iri]

    def _twins_of(self, iri):
        if iri not in self._twin_cache:
            self._twin_cache[iri] = {iri} | set(self.g.expand_roots([iri]) or {})
        return self._twin_cache[iri]

    def _interchangeable(self, a, b):
        if self._closure_of(a) == self._closure_of(b):
            return "identical closures"
        if b in self._twins_of(a) or a in self._twins_of(b):
            return "parallel hierarchy"
        return None

    def facet_merge(self, cands, limit=4):
        """Longest prefix of candidates that all denote the same ingredient."""
        iris = [c["iri"] for c in cands[:limit]]
        if len(iris) < 2:
            return [], []
        bases, k = set(), 1
        while k < len(iris):
            why = [self._interchangeable(iris[j], iris[k]) for j in range(k)]
            if not all(why):
                break
            bases.update(why); k += 1
        return (iris[:k], sorted(bases)) if k >= 2 else ([], [])

    def resolve(self, query, margin=8.0):
        key = query.strip().lower()
        pinned = self.store.get("entries", {}).get(key)
        if pinned:
            ov = self.g.meta["version"]
            if pinned.get("ontology_version") != ov:
                pinned = dict(pinned, status="stale", stale_reason=
                              f"resolved against FoodOn {pinned.get('ontology_version')}, now {ov}")
            return pinned
        c = self.score(query)
        if not c:
            return {"query": query, "status": "absent", "roots": [],
                    "note": "no FoodOn class matches this term lexically"}
        if len(c) == 1 or c[0]["score"] - c[1]["score"] >= margin:
            low = c[0]["closure"] <= self.VIABILITY_FLOOR
            out = {"query": query, "status": "resolved", "method": "lexical+structural",
                   "roots": [c[0]["iri"]], "root_labels": [c[0]["label"]],
                   "confidence": "high" if c[0]["score"] >= 100 else "medium",
                   "viability": "low" if low else "ok",
                   "candidates": c[:4]}
            if low:
                out["review_recommended"] = True
                alts = self.head_alternatives(query, c[0]["closure"])
                out["reason"] = (f"resolves to a class with a closure of {c[0]['closure']}. "
                                 "This is correct for a genuine leaf ingredient and wrong for a "
                                 "stub category; the two are not structurally distinguishable.")
                if alts: out["larger_nearby"] = alts
            return out
        merged, basis = self.facet_merge(c)
        if merged:
            byiri = {x["iri"]: x for x in c}
            left = [x["label"] for x in c[:4] if x["iri"] not in set(merged)]
            out = {"query": query, "status": "resolved", "method": "facet-merge",
                   "roots": merged,
                   "root_labels": [byiri[i]["label"] for i in merged],
                   # `identical closures` is a proof; a merge resting only on the
                   # parallel-hierarchy link is one inference removed from that
                   "confidence": "high" if basis == ["identical closures"] else "medium",
                   "viability": "ok",
                   "merge_basis": basis,
                   "candidates": c[:4],
                   "note": ("the top candidates are facets of one ingredient, not "
                            "competing senses (" + ", ".join(basis) + "), so all of "
                            "them are roots")}
            if left:
                out["not_merged"] = left
                out["note"] += ("; held out of the merge: " + ", ".join(left))
            return out
        return {"query": query, "status": "ambiguous", "roots": [],
                "candidates": c[:4],
                "note": "lexical and structural evidence do not separate the top "
                        "candidates, and they are not facets of one ingredient"}

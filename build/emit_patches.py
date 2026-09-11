#!/usr/bin/env python3
"""Emit ontology/foodon-local-patches.ttl from the governed decision files.

WHY THIS IS GENERATED AND NOT HAND-EDITED
-----------------------------------------
Every axiom in the output already has a decision behind it: a rule with structural
guards (build/repair_derives.py), a sign-off keyed to one class's own prose
(config/mined-signoff.json), or a reviewed claim with a claim type
(config/overrides.json). Those files are the review surface and the tests run
against them. This step publishes them as a standards-compliant OWL patch layer so
that a fresh `foodon.owl` plus one `robot merge` reproduces the relationships this
project has established, with no application code in the loop.

The output is designed to be READ. Every axiom carries:
  - a Turtle comment block naming the rule, the guards, the evidence and the
    reviewer, so a human can audit it against OBO practice without a tool
  - a machine-readable `local:Patch` provenance record, so the same audit can be
    done in SPARQL and so the upstream-fix detector can find superseded patches

WHAT CAN AND CANNOT BE AN AXIOM
-------------------------------
`derives from` and `is a` assertions are axioms and are emitted as such. Three
kinds of local knowledge are NOT containment and must never be emitted as
RO:0001000, because a downstream consumer would then treat them as containment:

  may_contain      feedstock is a producer choice (corn-derived citric acid)
  cross_reactive   immunologically related; the allergen protein is NOT present
  disputed         on avoidance lists with no established containment basis

They get their own declared object properties under the local namespace, each with
an rdfs:comment stating plainly that it is not containment.

One thing genuinely cannot be expressed: OWL is monotonic, so a patch layer cannot
RETRACT an upstream axiom. `peanut plant is_a nut producing plant` is asserted by
FoodOn and no import removes it. That decision is emitted as
`local:notAvoidanceRelevantFor`, an assertion a traversal can honour, rather than
pretending the axiom is gone.
"""
import json, hashlib, collections, datetime, sys

# The namespace the local vocabulary and patch records live under. Change this if
# the patch layer will be published somewhere else; nothing else depends on it.
BASE = "https://fluxon.com/ns/foodon-local/"
OUT = "ontology/foodon-local-patches.ttl"
FOODON_IRI = "http://purl.obolibrary.org/obo/foodon.owl"
OBO = "http://purl.obolibrary.org/obo/"
RO_DERIVES = OBO + "RO_0001000"
RO_IN_TAXON = OBO + "RO_0002162"
TODAY = "2026-09-10"

ix = json.load(open("data/index.json"))
N = ix["nodes"]
ONT_VERSION = ix["meta"]["version"]
lbl = lambda i: (N.get(i, {}) or {}).get("l") or ""


def curie(iri):
    """Prefixed name where a prefix is declared, else a full IRI.

    The local namespace has to be handled too, or the weak-claim assertions come
    out as `<https://.../mayDeriveFrom>` while everything around them is prefixed --
    valid Turtle, but it reads badly in a file whose whole purpose is to be audited.
    """
    if iri.startswith(OBO):
        return "obo:" + iri.rsplit("/", 1)[-1]
    if iri.startswith(BASE):
        return "local:" + iri[len(BASE):]
    return "<" + iri + ">"


def tl(s):
    """A Turtle string literal, escaped."""
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "").replace("\t", " ")
    return '"' + s + '"'


def pid(*parts):
    """Stable patch id, so regenerating does not churn the identifiers."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return "local:patch-" + h


def wrap(text, width=74, indent="#   "):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(indent + cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur: lines.append(indent + cur)
    return "\n".join(lines)


patches = []          # (section, target, prop, value, kind, meta)


def add(section, target, prop, value, kind, **meta):
    patches.append((section, target, prop, value, kind, meta))


# ---- 1. label-convention repairs ---------------------------------------------
for a in json.load(open("data/repairs-classified.json"))["auto_apply"]:
    add("repair", a["product"], RO_DERIVES, a["source"], "restriction",
        rule=a.get("rule"), guards=", ".join(a.get("guards_passed") or []),
        evidence=a.get("evidence"), confidence=a.get("confidence", "high"),
        creator="build/repair_derives.py + build/classify_repairs.py",
        note="FoodOn omits `derives from` on 62% of its `<X> food product` classes. "
             "Recovered from the naming convention plus two structural guards.")

# ---- 2. signed mined bridges --------------------------------------------------
for a in json.load(open("data/mined-classified.json"))["signed_off"]:
    isa = a.get("relation") == "is a"
    add("mined", a["product"], None if isa else RO_DERIVES, a["source"],
        "named" if isa else "restriction",
        rule=a.get("rule"), evidence=a.get("evidence"),
        confidence=a.get("confidence", "medium"),
        creator=a.get("signed_off_by") or "Matt",
        rationale=a.get("rationale"),
        note="Extracted from FoodOn's own definition text and signed off per class.")

# ---- 2b. missing `in taxon` links ---------------------------------------------
# Emitted on RO:0002162, the ontology's own property, not a local one. FoodOn asserts
# this link for six of the seventeen plant classes under `citrus family` and omits it
# for the rest; supplying the omission means a consumer reaches `lemon plant` by the
# identical path it already walks to `grapefruit plant`, and the SPARQL materialiser
# needs no new branch to understand it.
RO_IN_TAXON = "http://purl.obolibrary.org/obo/RO_0002162"
for b in json.load(open("config/taxon-bridges.json"))["signed_off"]:
    add("taxon", b["class"], RO_IN_TAXON, b["taxon"], "restriction",
        evidence=b.get("evidence"), confidence=b.get("confidence", "high"),
        creator=b.get("signed_off_by") or "Matt",
        note="FoodOn's plant hierarchy has no genus-level citrus class: these hang off "
             "`citrus family`, which is Rutaceae and therefore above the genus, so a "
             "query cannot ascend to it without also collecting Zanthoxylum. The "
             "species link is the route FoodOn itself uses.")

# ---- 3. overrides -------------------------------------------------------------
ov = json.load(open("config/overrides.json"))
WEAK = {"may_contain": BASE + "mayDeriveFrom",
        "shared_compound": BASE + "sharesCompoundWith",
        "cross_reactive": BASE + "crossReactiveWith",
        "disputed": BASE + "disputedAvoidance"}
for o in ov["overrides"]:
    tgt, claim, typ = o.get("target_class"), o.get("claim"), o.get("type")
    roots = o.get("query_roots") or ([o["query_root"]] if o.get("query_root") else [])
    if typ == "superseded":
        add("superseded", tgt, RO_DERIVES, (roots or [None])[0], "skip",
            note=o.get("superseded_reason"), creator=o.get("reviewed_by"),
            label=o.get("target_label"), by=o.get("superseded_by"))
        continue
    if not tgt:
        add("absent", None, None, None, "skip", label=o.get("target_label"),
            claim=claim, note=o.get("reason"), creator=o.get("reviewed_by"),
            query=o.get("query_class"))
        continue
    if typ == "remove":
        add("remove", tgt, BASE + "notAvoidanceRelevantFor", roots[0], "assertion",
            note=o.get("reason"), creator=o.get("reviewed_by"), claim=claim,
            confidence="high", query=o.get("query_root_label"))
        continue
    if typ == "add" and claim == "contains":
        for r in roots:
            add("contains", tgt, RO_DERIVES, r, "restriction",
                note=o.get("reason"), creator=o.get("reviewed_by"),
                confidence=o.get("confidence", "high"), claim=claim,
                evidence=o.get("source"), query=o.get("query_class"))
    elif claim in WEAK:
        for r in roots:
            add("weak", tgt, WEAK[claim], r, "assertion",
                note=o.get("reason"), creator=o.get("reviewed_by"),
                confidence=o.get("confidence", "medium"), claim=claim,
                evidence=o.get("source"), query=o.get("query_class"),
                declined=(typ == "declined"))

pol = json.load(open("config/relation_policy.json"))
store = json.load(open("data/resolution-store.json"))

# ---- parallel-hierarchy correspondences --------------------------------------
# Computed per root, one at a time: expand_roots on a SET returns the union, and
# cross-joining that against every root in the set invents pairs that do not hold
# (`barley plant sameOrganismAs Secale cereale`, from the five-root gluten query).
sys.path.insert(0, "build")
from traverse import Graph as _G
_g = _G()
_ROOTS = sorted({r for e in store["entries"].values()
                 if e.get("status") == "resolved" for r in (e.get("roots") or [])})
_EXPAND = {}
for _r in _ROOTS:
    _exp = _g.expand_roots([_r]) or {}
    _EXPAND[_r] = {k: (v[0] if isinstance(v, (list, tuple)) else v)
                   for k, v in _exp.items() if k != _r}

# ------------------------------------------------------------------ write it out
w = []
A = w.append
A(f"""# =============================================================================
# FoodOn local patch layer
# =============================================================================
#
# GENERATED FILE -- do not hand-edit. Regenerate with:
#
#     python3 build/emit_patches.py
#
# Source of truth is the governed decision files, which carry the guards, the
# claim types and the sign-off records, and which the test suite runs against:
#
#     data/repairs-classified.json    label-convention repairs (rule + guards)
#     config/repair-signoff.json      human rulings on those
#     data/mined-classified.json      definition-mined bridges
#     config/mined-signoff.json       human rulings on those, per class
#     config/overrides.json           reviewed claims, by claim type
#     config/relation_policy.json     which relations propagate, and exclusions
#     data/resolution-store.json      pinned free-text resolutions
#
# HOW TO USE
#
#     java -jar tools/robot.jar merge \\
#          --input ontology/foodon.owl \\
#          --input ontology/foodon-local-patches.ttl \\
#          --output ontology/foodon-merged.owl
#
# `ontology/foodon.owl` is never modified. Drop in a new upstream release and
# re-merge; a catalog (ontology/catalog-v001.xml) resolves the owl:imports below
# to the local copy so this file also loads standalone in a reasoner or
# triplestore.
#
# HOW TO AUDIT
#
# Every axiom below is preceded by a comment block naming the rule that produced
# it, the guards it passed, the evidence, and who signed it. The same facts are
# repeated as a machine-readable `local:Patch` record, so an audit can also be run
# in SPARQL -- see build/sparql/upstream_fixed.rq, which finds patches that a new
# upstream release has made redundant.
#
# WHAT IS DELIBERATELY NOT A CONTAINMENT AXIOM
#
# `may_contain`, `cross_reactive` and `disputed` are NOT containment and are
# emitted on their own declared properties, never on RO:0001000. Asserting them as
# `derives from` would tell a corn-avoider that citric acid contains corn, which is
# not a property of the substance. See the property comments below.
#
# ontology version patched : {ONT_VERSION}
# generated                : {TODAY}
# =============================================================================

@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix obo:     <{OBO}> .
@prefix local:   <{BASE}> .

<{BASE}patches.ttl> a owl:Ontology ;
    owl:imports <{FOODON_IRI}> ;
    dcterms:title "FoodOn local patch layer"@en ;
    dcterms:description \"\"\"Locally asserted axioms that FoodOn omits, plus locally
declared properties for claims that are weaker than containment. Generated from
reviewed decision files by build/emit_patches.py; see the header of that file for
what can and cannot be expressed as an axiom.\"\"\"@en ;
    dcterms:created "{TODAY}"^^xsd:date ;
    dcterms:creator "Matt" ;
    owl:versionInfo "patches for FoodOn {ONT_VERSION}, generated {TODAY}" ;
    rdfs:comment "Upstream foodon.owl is never modified. This layer is additive."@en .


# =============================================================================
# Local vocabulary
# =============================================================================
# Four object properties and a small provenance vocabulary. The three weak-claim
# properties exist so that a claim which is NOT containment can be stated honestly
# rather than being smuggled onto RO:0001000.

local:mayDeriveFrom a owl:ObjectProperty ;
    rdfs:label "may derive from"@en ;
    rdfs:comment \"\"\"Commonly but not necessarily derived from the subject. The
feedstock is a producer choice, not a property of the substance: citric acid is
Aspergillus fermentation on a sugar feedstock that is often, but not always, corn.
THIS IS NOT CONTAINMENT and must not be treated as obo:RO_0001000. A consumer
should surface it as a label to check or a supplier to ask.\"\"\"@en ;
    rdfs:seeAlso <{FOODON_IRI}> .

local:sharesCompoundWith a owl:ObjectProperty ;
    rdfs:label "shares compound with"@en ;
    rdfs:comment \"\"\"Subject and object share the compound that drives a non-immune
INTOLERANCE response. Neither derives from the other and no allergen protein is
involved: the molecule is the same whatever its origin. Citric acid is what citrus is
named for and is the usual trigger in citrus intolerance, yet commercial citric acid
is Aspergillus niger fermentation -- and the imitation-citrus beverages built on it
are formulated that way precisely to contain no citrus. THIS IS NOT CONTAINMENT and
must not be treated as obo:RO_0001000. A consumer should surface it to someone
avoiding the subject for an intolerance, and not to someone avoiding it for an
allergy.\"\"\"@en .

local:crossReactiveWith a owl:ObjectProperty ;
    rdfs:label "cross reactive with"@en ;
    rdfs:comment \"\"\"Immunologically related to the subject, but the allergen protein
is NOT present. Relevant to a clinical history, not to what is in the dish.
Treating this as containment is wrong in the direction that needlessly excludes
safe food.\"\"\"@en .

local:disputedAvoidance a owl:ObjectProperty ;
    rdfs:label "disputed avoidance"@en ;
    rdfs:comment \"\"\"Appears on avoidance lists for the subject without an established
containment basis. Recorded so the claim is visible and auditable; NOT
containment.\"\"\"@en .

local:notAvoidanceRelevantFor a owl:ObjectProperty ;
    rdfs:label "not avoidance relevant for"@en ;
    rdfs:comment \"\"\"The subject is ontologically a descendant of the object in
FoodOn, but must NOT be treated as part of its avoidance closure. OWL is monotonic
and an import cannot retract an upstream axiom, so this states the exception
declaratively for a traversal to honour instead. The motivating case is
`peanut plant is_a nut producing plant`, which is defensible botanically and wrong
for allergens: FALCPA treats peanut and tree nut as separate allergens.\"\"\"@en .

local:propagatesAvoidance a owl:AnnotationProperty ;
    rdfs:label "propagates avoidance"@en ;
    rdfs:comment \"\"\"On an object property: whether avoidance travels along it, and in
which direction. `inverse` means avoidance travels object to subject, which is the
direction obo:RO_0001000 is asserted in (product derives from source).\"\"\"@en .

local:excludedFromTraversal a owl:AnnotationProperty ;
    rdfs:label "excluded from traversal"@en ;
    rdfs:comment \"\"\"On a class: this class and everything beneath it is out of scope
for avoidance traversal. Not a claim about the ontology, a claim about scope.\"\"\"@en .

local:pivotsTo a owl:ObjectProperty ;
    rdfs:label "pivots to"@en ;
    rdfs:comment \"\"\"Materialised by build/sparql/patch_materialize_avoidance.rq, not
asserted here: the rank-guarded forward `in taxon` hop from a FoodOn class to its own
species-rank taxon. Kept separate from local:propagatesTo because it belongs to the
taxonomic phase of a query -- it fires from a class reached by is_a descent from the
root, never from a derivative. Declared here so the vocabulary is documented in one
place.\"\"\"@en .

local:propagatesTo a owl:ObjectProperty ;
    rdfs:label "propagates avoidance to"@en ;
    rdfs:comment \"\"\"Materialised, not asserted here. One hop of avoidance, always
source to product, so a closure over it can never ascend to a shared ancestor and
come back down. That is what keeps corn from reaching wheat.\"\"\"@en .

local:sameOrganismAs a owl:ObjectProperty ;
    rdfs:label "same organism as"@en ;
    rdfs:comment \"\"\"The subject and object denote the SAME organism in two parallel
FoodOn hierarchies that share no terms. Solanaceae exists twice -- NCBITaxon_4070 and
FoodOn's own `solanaceae plant` -- and rooting a query on either one silently loses
the other, which is how eggplant went missing. Deliberately NOT owl:equivalentClass:
the two classes have different subclass trees and different annotation, so asserting
equivalence would invite a reasoner to merge things this project has not reviewed.
A consumer should treat both ends as co-roots of the same query. Derived two ways --
a species-rank `in taxon` pivot, or FoodOn's own label convention -- never by a
hardcoded pair; see audit F4 and Graph.expand_roots.\"\"\"@en ;
    a owl:SymmetricProperty .

local:resolvesQuery a owl:AnnotationProperty ;
    rdfs:label "resolves query"@en ;
    rdfs:comment \"\"\"On a class: a free-text query that has been pinned to this class
as one of its roots. Several classes may carry the same query string when one class
cannot cover the allergen on its own -- `gluten` pins five grain species.\"\"\"@en .

local:Patch a owl:Class ;
    rdfs:label "local patch record"@en ;
    rdfs:comment \"\"\"Provenance for one locally asserted axiom or claim. Carries the
rule, guards, evidence and reviewer so the patch layer can be audited in SPARQL as
well as by reading the comments.\"\"\"@en .
""")

for p, lab in [("patchTarget", "patch target"), ("patchProperty", "patch property"),
               ("patchValue", "patch value"), ("patchRule", "patch rule"),
               ("patchGuards", "patch guards"), ("patchEvidence", "patch evidence"),
               ("patchConfidence", "patch confidence"), ("patchClaim", "patch claim"),
               ("patchSection", "patch section"), ("patchQuery", "patch query class"),
               ("supersededBy", "superseded by")]:
    A(f'local:{p} a owl:AnnotationProperty ;\n    rdfs:label "{lab}"@en .\n')

SECTIONS = [
 ("repair", "Omitted `derives from` axioms, recovered by naming convention",
  "FoodOn applies `<X> food product --derives from--> <X> plant` inconsistently: only "
  "38% of those classes carry it. `hungarian wax pepper food product` omits it while "
  "its sibling `hungarian wax pepper pickle food product` has it, which is why paprika "
  "was structurally disconnected from the nightshade family. Recovered by rule, not by "
  "a per-ingredient list, with two structural guards: organism-branch compatibility "
  "and uniqueness of the candidate source. Note the source is the most specific true "
  "one -- the CULTIVAR plant, not the family. Solanaceae is then reached through "
  "FoodOn's own is_a chain, which keeps the axiom correct for a narrower query too."),
 ("mined", "Bridges extracted from FoodOn's own definition text",
  "FoodOn frequently states an origin in prose while asserting nothing. Paprika's "
  "definition reads 'derived from the dried fruit of several varieties of Capsicum "
  "annuum L.'; pasta's reads 'an unleavened dough of wheat flour'. Each of these was "
  "extracted, passed five guards, and signed off against that one class's own "
  "sentence. Prose is not an axiom, so a human ruling is recorded per class."),
 ("taxon", "Omitted `in taxon` links on plant classes",
  "A third kind of gap, on the ontology's own property RO:0002162. FoodOn's plant "
  "hierarchy has no genus-level citrus class: seventeen plant classes hang directly "
  "off `citrus family`, which is Rutaceae and therefore ABOVE the genus, so a citrus "
  "query cannot reach them without ascending -- and ascending to the family also "
  "collects Zanthoxylum (prickly ash, japan pepper, sansho, uzazi fruit), which is in "
  "the family and is not citrus. Six of the seventeen carry `in taxon <species>` and "
  "are reached through it; these five are the ones where FoodOn asserts that link on "
  "the FRUIT class and omits it on the PLANT. Emitted on RO:0002162 rather than a "
  "local property so a consumer reaches them by the identical path it already walks "
  "to `grapefruit plant`."),
 ("contains", "Reviewed containment claims FoodOn cannot make",
  "FoodOn parents processed ingredients by function -- `tahini is_a condiment`, "
  "`casein is_a protein extract` -- and asserts no source. These are the cases where "
  "the containment is real and the ontology simply has no axiom for it."),
 ("weak", "Claims that are NOT containment",
  "Emitted on local properties, never on RO:0001000. Read the property comments "
  "before consuming these. Entries marked DECLINED were reviewed and rejected as "
  "containment; they are kept because the reasoning is the useful part."),
 ("remove", "Exceptions that OWL cannot express as retractions",
  "OWL is monotonic: an import adds and never removes. Where an upstream axiom is "
  "ontologically defensible but wrong for avoidance, the exception is stated "
  "declaratively for a traversal to honour."),
 ("superseded", "Retired patches, kept for the audit trail",
  "These were correct and signed, and are now carried by structure instead -- either "
  "upstream or by another patch. No axiom is emitted. They are listed so that the "
  "record of why the gap existed survives, and so a regression is recognisable."),
 ("absent", "Claims whose target has no FoodOn class",
  "There is nothing to point an axiom at. Recorded as text because the safety "
  "information matters more than the modelling."),
]

for key, title, blurb in SECTIONS:
    rows = [p for p in patches if p[0] == key]
    if not rows: continue
    A("\n\n# " + "=" * 77)
    A(f"# {title}   ({len(rows)})")
    A("# " + "=" * 77)
    A(wrap(blurb, indent="# "))
    A("")
    def sortkey(r):
        return ((lbl(r[1]) or r[5].get("label") or "").lower(), str(r[3]))
    for section, target, prop, value, kind, meta in sorted(rows, key=sortkey):
        tname = lbl(target) if target else (meta.get("label") or "?")
        vname = lbl(value) if value else "-"
        A("")
        A(f"### {tname}" + (f"  --{prop.rsplit('/',1)[-1].replace('_',':') if prop and prop.startswith(OBO) else (prop.rsplit('/',1)[-1] if prop else 'n/a')}-->  {vname}"
                            if value else ""))
        for k in ("rule", "guards", "evidence", "confidence", "claim", "query", "by"):
            if meta.get(k): A(f"#   {k+':':<12}{meta[k]}")
        if meta.get("declined"): A("#   status:     DECLINED as containment")
        if meta.get("creator"): A(f"#   {'reviewer:':<12}{meta['creator']}")
        for k in ("note", "rationale"):
            if meta.get(k): A(wrap(meta[k], indent="#   "))
        if kind == "skip":
            A("#   (no axiom emitted)")
        elif kind == "restriction":
            A(f"{curie(target)} rdfs:subClassOf [")
            A(f"    a owl:Restriction ;")
            A(f"    owl:onProperty {curie(prop)} ;")
            A(f"    owl:someValuesFrom {curie(value)} ] .")
        elif kind == "named":
            A(f"{curie(target)} rdfs:subClassOf {curie(value)} .")
        elif kind == "assertion":
            A(f"{curie(target)} {curie(prop)} {curie(value)} .")
        # provenance record
        ident = pid(section, target, prop, value)
        A(f"{ident} a local:Patch ;")
        A(f"    local:patchSection {tl(section)} ;")
        if target: A(f"    local:patchTarget {curie(target)} ;")
        if prop:   A(f"    local:patchProperty {curie(prop)} ;")
        if value:  A(f"    local:patchValue {curie(value)} ;")
        for k, ap in (("rule", "patchRule"), ("guards", "patchGuards"),
                      ("evidence", "patchEvidence"), ("confidence", "patchConfidence"),
                      ("claim", "patchClaim"), ("query", "patchQuery"),
                      ("by", "supersededBy")):
            if meta.get(k): A(f"    local:{ap} {tl(str(meta[k]))} ;")
        txt = " ".join(x for x in (meta.get("note"), meta.get("rationale")) if x)
        if txt: A(f"    rdfs:comment {tl(txt)} ;")
        A(f'    dcterms:creator {tl(meta.get("creator") or "Matt")} ;')
        A(f'    dcterms:created "{TODAY}"^^xsd:date .')

# ---- relation policy, exclusions, resolutions as annotations ------------------
A("\n\n# " + "=" * 77)
A("# Traversal policy, as annotations")
A("# " + "=" * 77)
A(wrap("Not axioms: these say how a consumer should WALK the merged graph. A "
       "relation propagating `inverse` means avoidance travels object to subject, "
       "which is the direction RO:0001000 is asserted in. Emitted so a SPARQL "
       "consumer can read the policy from the data instead of re-deriving it.",
       indent="# "))
A("")
for r in pol["propagating_relations"]:
    A(f'{curie(r["property"])} local:propagatesAvoidance {tl(r["direction"])} ;')
    A(f'    rdfs:comment {tl(r.get("rationale") or r.get("reason") or "")} .')
for r in pol["non_propagating_relations"]:
    A(f'{curie(r["property"])} local:propagatesAvoidance "none" ;')
    A(f'    rdfs:comment {tl(r.get("rationale") or r.get("reason") or "")} .')
A("")
for b in pol["excluded_branches"]:
    A(f'### excluded branch: {b.get("label")}  ({b.get("size")} classes)')
    A(wrap(b.get("reason") or "", indent="#   "))
    A(f'{curie(b["class"])} local:excludedFromTraversal true .')
A("\n# --- parallel-hierarchy correspondences -------------------------------------")
A(wrap("The same organism under two FoodOn class trees that share no terms. Emitted "
       "because a closure that starts on only one of the pair silently under-reports: "
       "measured on Solanaceae, 620 classes from NCBITaxon_4070 alone against 630 with "
       "the pair. Computed per root by taxon pivot or label convention, not listed by "
       "hand.", indent="# "))
A("")
_seen_pair = set()
for _r in sorted(_ROOTS, key=lambda x: lbl(x)):
    for _k, _why in sorted((_EXPAND.get(_r) or {}).items(), key=lambda kv: lbl(kv[0])):
        if _k == _r or (_r, _k) in _seen_pair: continue
        _seen_pair.add((_r, _k)); _seen_pair.add((_k, _r))
        A(f"### {lbl(_r)}  <->  {lbl(_k)}   [{_why}]")
        A(f"{curie(_r)} local:sameOrganismAs {curie(_k)} .")
A("")

A("\n# --- pinned free-text resolutions -------------------------------------------")
A(wrap("Which classes a free-text query resolves to. Several classes carry the same "
       "string where one cannot cover the allergen alone.", indent="# "))
byroot = collections.defaultdict(list)
for q, e in store["entries"].items():
    if e.get("status") != "resolved": continue
    for r in e.get("roots") or []:
        byroot[r].append(q)
for r in sorted(byroot, key=lambda x: lbl(x)):
    qs = " , ".join(tl(q) for q in sorted(byroot[r]))
    A(f'{curie(r)} local:resolvesQuery {qs} .')

open(OUT, "w").write("\n".join(w) + "\n")

kinds = collections.Counter(p[4] for p in patches)
sect = collections.Counter(p[0] for p in patches)
print(f"wrote {OUT}")
print(f"  axioms emitted     : {kinds['restriction'] + kinds['named']}"
      f"  (restriction {kinds['restriction']}, named subClassOf {kinds['named']})")
print(f"  local assertions   : {kinds['assertion']}")
print(f"  recorded, no axiom : {kinds['skip']}")
print(f"  by section         : {dict(sect)}")
print(f"  excluded branches  : {len(pol['excluded_branches'])}")
print(f"  pinned resolutions : {sum(len(v) for v in byroot.values())} across {len(byroot)} classes")

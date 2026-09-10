#!/usr/bin/env python3
"""Generate config/relation_policy.json from the audited property inventory.

Counts come from data/index.json so the file is regenerable and auditable against
a new FoodOn release. The propagate/direction/confidence judgements are the draft
requiring sign-off (spec 1a).

DIRECTION is not a free choice, and the spec's suggested "both" is unsafe. Avoidance
propagates along exactly one direction per relation:

    query = the thing being avoided; we want everything that CONTAINS or DERIVES FROM it.

`derives from` is asserted product -> source, so from a source query we walk
object -> subject ("inverse"). Permitting "both" would allow product -> source ->
sibling product, which is ascend-then-redescend wearing a different hat. Only
`part_of` is asserted in the direction avoidance already travels ("forward").
"""
import json, collections

ix = json.load(open("data/index.json")); N, E = ix["nodes"], ix["edges"]
lbl = lambda i: N.get(i, {}).get("l", "") or ""
counts = collections.Counter(e["p"] for e in E if e["p"] != "isa")
O = "http://purl.obolibrary.org/obo/"

# property -> (propagates, direction, confidence, rationale)
POLICY = {
 O+"RO_0001000":     (True,  "inverse", "high",   "core derivation: product derives from source organism/material"),
 O+"RO_0002162":     (True,  "inverse", "high",   "only systematic bridge from FoodOn classes into the NCBITaxon backbone; required for class-level botanical queries"),
 O+"FOODON_00001563":(True,  "inverse", "high",   "has defining ingredient: strawberry wine -> strawberry. Direct composition"),
 O+"FOODON_00002420":(True,  "inverse", "high",   "has ingredient: direct composition"),
 O+"RO_0009001":     (True,  "inverse", "high",   "has substance added: lasagne -> cheese food product. Direct composition"),
 O+"RO_0002473":     (True,  "inverse", "high",   "composed primarily of: brown sugar -> sucrose. Targets are ChEBI, so gated by the label-granularity boundary"),
 O+"RO_0003001":     (True,  "inverse", "high",   "produced by: food produced by an organism"),
 O+"BFO_0000051":    (True,  "inverse", "medium", "has_part: whole -> part. Composition, but 411 of 483 have anonymous fillers and are not edge-able"),
 O+"BFO_0000050":    (True,  "inverse", "medium", "part_of: traverse whole -> part. Was drafted as `forward` on the reasoning that part->whole is the direction avoidance travels; that was wrong and measurably so. Forward made a soy query return lobster and its 73-node subtree via `soybean oil (flavored with extract from lobster shell) part_of lobster`. Inverse is correct: avoiding lobster should flag that oil, avoiding soy should not flag lobster"),
 O+"RO_0002233":     (True,  "inverse", "medium", "has input: bean flour -> bean (dried). Derivation-like"),
 O+"OBI_0000293":    (True,  "inverse", "medium", "has specified input: process input becomes part of the output"),
 O+"RO_0002202":     (True,  "inverse", "medium", "develops_from: mostly PO plant-anatomy, but genuinely a derivation"),
 O+"RO_0002160":     (True,  "inverse", "medium", "only_in_taxon: taxon restriction, same role as in taxon"),
 O+"RO_0009003":     (True,  "inverse", "low",    "immersed in: 1 edge (lasagne -> packed in gravy or sauce). Kept for recall, low confidence"),

 O+"RO_0002350":     (False, None, None, "member of: 2,343 edges pointing almost entirely at US CFR regulatory groupings. A classification facet, not composition -- propagating it would link every nutritive sweetener to every other. Retained as the primary input to the section 6 functional rollup"),
 O+"RO_0002351":     (False, None, None, "has member: inverse of member of, same reasoning"),
 O+"FOODON_00001301":(False, None, None, "has food substance analog: imitation peanut butter -> peanut butter. MUST NOT propagate -- an analog is defined by NOT containing the thing it imitates. Surfaced in the UI as 'related, verify separately', never as containment"),
 O+"RO_0000086":     (False, None, None, "has quality: quality annotation, not composition"),
 O+"RO_0000053":     (False, None, None, "has characteristic: quality annotation"),
 O+"RO_0002353":     (False, None, None, "output of: points at a process (food (canned) -> food canning), not an ingredient"),
 O+"OBI_0000312":    (False, None, None, "is specified output of: points at a process"),
 O+"OBI_0000299":    (False, None, None, "has specified output: process output, wrong direction for containment"),
 O+"RO_0002234":     (False, None, None, "has output: process output"),
 O+"RO_0001025":     (False, None, None, "located_in: geography (GAZ)"),
 O+"HANCESTRO_0308": (False, None, None, "hasCountryOfOrigin: geography"),
 O+"RO_0009004":     (False, None, None, "has consumer: who eats it, not what is in it"),
 O+"RO_0000056":     (False, None, None, "participates_in: process participation"),
 O+"RO_0000057":     (False, None, None, "has_participant: process participation"),
 O+"IAO_0000136":    (False, None, None, "is about: metadata"),
 O+"RO_0002219":     (False, None, None, "surrounded by: spatial, not compositional"),
 O+"RO_0002170":     (False, None, None, "connected to: spatial"),
 O+"BFO_0000062":    (False, None, None, "preceded_by: temporal"),
}

# Relations with no measurable effect on any golden query. Semantically sound, but
# no evidence has exercised them, and the policy file should not imply otherwise.
UNTESTED = {O+"RO_0002202", O+"RO_0003001", O+"RO_0002233", O+"OBI_0000293",
            O+"RO_0009001", O+"RO_0002473", O+"RO_0002160", O+"RO_0009003"}

prop, nonprop, unclassified = [], [], []
for p, c in counts.most_common():
    entry = {"property": p, "curie": p.rsplit("/", 1)[-1].replace("_", ":", 1),
             "label": lbl(p), "usage_count": c}
    if p not in POLICY:
        unclassified.append(entry); continue
    propagates, direction, conf, why = POLICY[p]
    if propagates:
        prop.append(dict(entry, direction=direction, confidence=conf,
                         evidence=("untested - no effect on any golden query as of "
                                   "build/policy_sensitivity.py 2026-09-09"
                                   if p in UNTESTED else "exercised by the golden set"),
                         rationale=why))
    else:
        nonprop.append(dict(entry, reason=why))

out = {
  "version": "2026-09-09b",
  "status": "REVIEWED",
  "review": {
    "reviewed_by": "Matt",
    "reviewed_date": "2026-09-09",
    "method": "walked through with measured sensitivity per relation (build/policy_sensitivity.py): each propagating relation dropped and each non-propagating relation enabled, closure delta measured across corn, nightshade, milk, soy, wheat and tree nut.",
    "decisions": [
      "part_of flipped from forward to inverse. Forward made a soy query return lobster and its 73-node subtree via `soybean oil (flavored with extract from lobster shell) part_of lobster`. Regression tests in test/golden.json now fail if it is flipped back.",
      "Eight propagating relations with no measurable effect on any golden query are KEPT for recall-first, each flagged evidence=untested rather than left implying validation.",
      "composed primarily of keeps propagating into ChEBI, gated by terminal_namespaces: a ChEBI class is reachable but never expanded, so sucrose and maltodextrin are admissible as label items while molecular structure stays out of scope."
    ],
    "confirmed_without_change": [
      "derives from and in taxon as the two load-bearing relations (dropping them costs 2,574 and 359 nodes respectively).",
      "member of NON-propagating: its 2,343 edges point at US CFR regulatory groupings; propagating would link every nutritive sweetener to every other. Retained as the section 6 rollup source.",
      "has food substance analog NON-propagating: asserts `imitation blue cheese -> blue cheese` and `egg material analog -> egg food product`. Propagating would tell a milk-avoider that imitation cheese contains milk, steering them away from the safe substitute. The relation is also asserted in both directions for some pairs and includes `cheese analog, dairy-based`, so it is unreliable either way.",
      "output of / is specified output of NON-propagating: they point at processes, not ingredients."
    ]
  },
  "ontology_version": ix["meta"]["version"],
  "generated_by": "build/build_relation_policy.py",
  "direction_semantics": {
    "inverse": "traverse object -> subject. The relation is asserted product -> source, so avoidance travels backwards along it.",
    "forward": "traverse subject -> object. The relation is already asserted in the direction avoidance travels.",
    "note": "No relation is bidirectional. 'both' would permit product -> source -> sibling product, which is the ascend-then-redescend failure in another form."
  },
  "hierarchy_traversal": {
    "property": "rdfs:subClassOf",
    "direction": "inverse",
    "rationale": "descend to subclasses only. Ascending is forbidden by the section 2 invariant; see build/traverse.py."
  },
  "terminal_namespaces": [
    {"namespace": "CHEBI",
     "rule": "reachable but not expanded",
     "reason": "spec target granularity is the ingredient label. A ChEBI class may be reached when a food product points at it (brown sugar composed primarily of sucrose; maltodextrin exists ONLY as CHEBI:25140 and is a real label item), but traversal stops there rather than descending into molecular structure. The boundary is ingredient-label granularity, not the ontology border."}
  ],
  "excluded_branches": [
    {"class": O+"FOODON_03400361", "label": "agency food product type", "size": 6074,
     "reason": "parallel regulatory classification vocabularies (EFSA FoodEx2, US CFR, EC, CCPR). '00030 - cereal grains' alone groups wheat, maize, rye, barley and rice, so traversing this branch leaks corn into wheat without ever ascending the food hierarchy. See audit F10."}
  ],
  "propagating_relations": prop,
  "non_propagating_relations": nonprop,
  "unclassified": unclassified,
}
json.dump(out, open("config/relation_policy.json", "w"), indent=2)
print(f"propagating     : {len(prop)}  (covering {sum(e['usage_count'] for e in prop):,} edges)")
print(f"non-propagating : {len(nonprop)}  (covering {sum(e['usage_count'] for e in nonprop):,} edges)")
print(f"unclassified    : {len(unclassified)}")
for e in unclassified: print("   !!", e["curie"], e["label"], e["usage_count"])

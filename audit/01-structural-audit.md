# Section 1 structural audit — FoodOn 2025-12-30

Source: `ontology/foodon.owl`, sha256 `1e11fc50…3db0`, versionIRI
`.../releases/2025-12-30/foodon.owl`. No `owl:imports` — this is the merged release,
NCBITaxon / CHEBI / PO / UBERON / ENVO / PATO classes are already inlined.
Tooling: ROBOT 1.9.10 (`tools/robot.jar`, sha256 `16a73c07…6105`), ELK, Java 21.

Scale: 39,893 classes (607 deprecated), 46,027 asserted `is_a` edges,
14,931 property restrictions, 4,640 logical-definition axioms.

---

## F1. Reasoning adds almost nothing — the ELK premise does not hold

`robot reason --reasoner ELK` over the full release produced **14 new subsumptions**
(46,027 → 46,041 `is_a`). Two independent causes:

1. The OBO release is already deductively closed for ELK over named classes —
   inferred axioms are materialized before publication.
2. More importantly, FoodOn's *culinary grouping* classes carry no equivalence
   definitions. For a reasoner to infer `paprika ⊑ nightshade food product`, something
   would have to define that grouping as e.g.
   `≡ plant food product ⊓ (derives from some Solanaceae)`. Nothing does. Groupings
   like `spice food product` are primitive classes with hand-attached children.

**Consequence:** the reasoner cannot manufacture the connections this project needs.
ROBOT stays in the pipeline for export, SPARQL extraction and validation, but
classification is not the lever. The leverage is in the asserted restrictions.

## F2. obographs silently drops ~10% of restrictions

Raw `owl:onProperty` counts from the XML vs. what the obographs export exposes across
`edges[]` + `logicalDefinitionAxioms[]`:

| property | label | raw | exposed | lost |
|---|---|---:|---:|---:|
| RO:0001000 | derives from | 4,004 | 3,555 | **449** |
| RO:0002162 | in taxon | 4,003 | 3,986 | 17 |
| RO:0002350 | member of | 2,343 | 2,343 | 0 |
| RO:0000086 | has quality | 2,230 | 2,199 | 31 |
| RO:0002351 | has member | 755 | 323 | **432** |
| BFO:0000051 | has_part | 483 | 64 | **419** |
| FOODON:00001563 | has defining ingredient | 325 | 318 | 7 |
| FOODON:00002420 | has ingredient | 158 | 152 | 6 |
| | **total** | **14,931** | **13,491** | **1,440** |

Losses are restrictions nested inside class expressions obographs does not model
(unions, nested intersections, cardinality). Under the section 7 recall-first policy,
**449 missing `derives from` assertions is an unacceptable false-negative source.**

**Decision:** do not consume obographs `edges[]` as the edge source. Extract all
restrictions with `robot query` (SPARQL over the RDF graph, blank-node depth
irrelevant) and use obographs only for labels, synonyms, definitions, deprecation.

## F3. The real mechanism is a source-anchored product family

`derives from` does not hang off individual products. It attaches at the head of a
product family, and everything else descends by `is_a`:

```
field corn plant  <--derives from--  field corn food product
                                     field corn refined food product
                                     field corn sweetener product      (+27 in-edges)
                                        `--is_a-- corn oil, corn syrup, corn dextrin,
                                                  dextrose anhydrous, masa, grits, …
```

68 `is_a` descendants under `field corn food product` alone. So the general traversal
is three stages, not a uniform walk:

1. resolve query → source node (organism / plant / taxon)
2. collect classes asserting `derives from` that node **or any sub-variety of it**
3. `is_a`-descend from each of those

## F4. `in taxon` (RO:0002162) is the bridge the spec doesn't mention

4,003 assertions — the second most-used property, and the only systematic link from
FoodOn's own classes into the NCBITaxon backbone
(`Maize plant --in taxon--> Zea mays subsp. mays`). Class-level botanical queries must
route *out* into NCBITaxon, descend the taxonomy, and come back *in* via inverse
`in taxon`. Measured recall of that bridge:

| query root | taxa | via in_taxon | via derives | + is_a closure |
|---|---:|---:|---:|---:|
| NCBITaxon:4070 Solanaceae | 130 | 86 | 27 | **252** |
| FOODON:03414934 solanaceae plant | 64 | 12 | 38 | **129** |
| NCBITaxon:4678 Allium | 22 | 20 | 5 | **48** |
| NCBITaxon:4577 Zea mays | 8 | 8 | 1 | **119** |

**Two disjoint Solanaceae hierarchies exist and must be unioned.** The NCBITaxon one
carries potatoes and tomatoes; the FoodOn one carries peppers and `ancho powder`.
Rooting on either alone silently loses the other.

## F5. Ascend-then-redescend is a live hazard one hop from the query

Not a theoretical concern. `field corn plant` is directly `is_a`:

- `starch-producing plant`
- `oil-producing plant`
- `sugar-producing plant`

One `is_a` step up from corn lands in functional classes containing wheat, potato,
cassava and sugar cane. Likewise paprika ascends into `spice food product` →
`spice or flavor-producing plant` → `whole plant` → Viridiplantae within four hops.
The invariant must be enforced structurally, as the spec requires. Note the shared
grass-family ancestor the spec worries about (Poaceae) is *not* the nearest hazard —
the functional plant classes are, and they are much closer.

## F6. The spec's motivating nightshade example does not exist in FoodOn

Neither hypothesized path is present:

- **Path A fails.** `paprika (ground)` (FOODON:03301223) has **no `derives from`
  edge at all**. Its only parent is `hungarian wax pepper food product`, whose only
  parent is `spice food product` — a *functional* class, not a botanical one.
  `Capsicum annuum` (NCBITaxon:4072) has 7 in-edges, none of them paprika.
- **Path B fails.** There is no "nightshade vegetables" culinary grouping. Every
  label matching *nightshade* is either an EFSA FoodEx2 code or an unrelated plant
  (`malabar nightshade`, `black nightshade`).
- FoodOn also models paprika as a *Hungarian wax pepper* product, which is
  questionable on its own terms — paprika is normally *C. annuum*.

### F6a. But it is a data gap with a detectable pattern, not a modelling philosophy

The sibling class **does** carry the axiom:

```
hungarian wax pepper pickle food product  --derives from-->  hungarian wax pepper plant   ✓
hungarian wax pepper food product         (no derives from)                               ✗
```

Same `<X>` plant, same product-class pattern, one has the axiom and one doesn't. So
this is an **omitted axiom**, and the omission is machine-detectable in general: for
every `<X> food product` class lacking a `derives from`, where an `<X> plant` class
exists, the axiom is missing. That is a general repair rule, not a per-ingredient
override — which is what the generality requirement asks for.

Related, and reachable *without* any repair, via `is_a` into `serrano pepper` which
does carry `in taxon → Capsicum annuum`:

- `cayenne pepper` → `serrano pepper` ✓
- `ancho powder` → `ancho pepper` ✓
- `hungarian wax pepper` (the fruit) → `serrano pepper` ✓
- `hungarian wax pepper food product` (paprika's parent, a *product* class) ✗

## F7. Granularity boundary conflicts with the golden set

- `dextrose` (FOODON:03315177) is `is_a plant sweetener` — **not** corn-anchored.
  But `dextrose powdered` / `anhydrous` / `monohydrate` are `field corn sweetener
  product`. Generic and specific forms sit in different branches.
- **`maltodextrin` exists only as CHEBI:25140.** FoodOn has no food-product class for
  it. The spec's rule "stop before the chemistry ontology" would exclude it — but
  maltodextrin is in the section 9 golden set and is unambiguously an ingredient-label
  item. The boundary needs to be "ingredient-label granularity", not "not ChEBI".

---

## Open decisions this audit surfaces

1. Reasoning is not the lever (F1) — confirm dropping ELK classification from the
   pipeline while keeping ROBOT for export/SPARQL/validation.
2. Switch the edge source from obographs to SPARQL extraction (F2).
3. Whether to build the general missing-`derives from` repair pass (F6a) or send
   paprika to `overrides.json`.
4. How to redraw the ChEBI granularity boundary so maltodextrin is in scope (F7).

---

# Addendum — extraction, repair pass, and first closures

## F2-resolved. Extraction is now provably complete

SPARQL property paths could not express the fully general query in tractable time
(three formulations were killed after 10 min). Replaced with a flat structural-triple
dump (`build/sparql/structure.rq`, 117k triples, 4s) plus an explicit cycle-safe walk
in Python (`build/extract_edges.py`, 0.4s).

```
restriction nodes in file : 14,931
  IRI filler (edge-able)  : 14,408   -> all 14,408 attributed to a named class
  blank-node filler       :    523   -> filler is itself an expression, no single
                                        target IRI exists (411 of these are has_part)
  unaccounted             :      0
```

**917 restrictions recovered over obographs, including 429 `derives from`.**
Three causes, all invisible in the obographs export: restrictions inside
`equivalentClass`/`intersectionOf` list structure; restrictions nested in another
restriction's filler (kept, but tagged `rel_nest` for a lower confidence tier, since
`A ⊑ has_part some (B ⊓ derives_from some C)` does not assert A derives from C); and
309 whose subject is never explicitly declared `a owl:Class`.

Verified by `build/verify_extraction.py`, which fails the build if any property's
extracted count diverges from the ground-truth count.

Index: **39,894 nodes, 58,664 typed edges** (46,769 `is_a`, 11,343 `rel`, 552 `rel_nest`).

## F8. The repair pass: 77 accepted, 2 held for review

`build/repair_derives.py`. Two structural guards, both derived from FoodOn's own
structure rather than enumerated:

- **organism-branch compatibility** — the direct children of `organism material`
  (animal 9,135 / plant 8,222 / organism piece 2,745 / fungus 179 / algae 85 /
  microbial 4 / lichen 1) are FoodOn's own top-level partition. Comparing at this
  level is deliberate: a finer comparison rejects `rye food product → rye plant`,
  because product-side and source-side markers sit in parallel subtrees that never
  subsume each other while still being the same organism. `organism piece`
  cross-cuts the rest and carries no evidence.
- **uniqueness** — more than one candidate means the name is ambiguous. This holds
  back `tea food product`, which matches both `tea plant` (*Camellia*) and
  `tea tree` (*Melaleuca*). Correctly not auto-applied.

`fish` is excluded from the source-suffix list on principle, not to fix a case: fish
common names routinely *end* in it (elephant fish, swordfish, catfish), so `<X> fish`
is ambiguous between a compositional source name and a single lexical species name.
This is what removed the bogus `elephant food product → elephant fish` candidate.

Guard development note: two earlier formulations were wrong in opposite directions —
one lumped mammal and fish into a single "animal" bucket and passed `elephant`
(0 rejections), the next inverted the most-specific test and rejected 50 legitimate
plant→plant pairs. Both were caught by inspecting the rejected list, which is the
argument for keeping this file reviewable as a unit.

## F9. Closures now work — and the spec's golden set has an error

With repairs applied, unioning both Solanaceae hierarchies:

**nightshade → 285 classes.** `paprika (ground)` ✓ `paprika puree` ✓ `cayenne pepper` ✓
`chili powder` ✓ `ancho powder` ✓ `potato` ✓ `tomato` ✓ `eggplant` ✓

Paprika is reached **structurally, with no override entry** — the repair edge
`hungarian wax pepper food product → hungarian wax pepper plant` connects it through
`Capsicum annuum` and `solanaceae plant`. This confirms the F6a diagnosis: it was an
omitted axiom, not a case for `overrides.json`.

**corn → 185 classes.** `corn starch hydrolyzate` ✓ `corn oil` ✓ `corn syrup` ✓
`dextrose anhydrous` ✓ `corn dextrin` ✓ `grits` ✓ `cornmeal` ✓ (`masa` misses —
open, it should be reachable via `field corn food product`).

Negative controls, no ascent performed: `wheat plant`, `soft wheat plant`,
`wheat bran`, `rye plant`, `sugar cane plant`, `potato` — **no leakage.**

### The golden set lists black and white pepper as nightshades. They are not.

Black and white pepper are *Piper nigrum* (Piperaceae). FoodOn models this correctly:
`black pepper plant → black or white pepper plant`, with no route to Solanaceae. Their
absence from the nightshade closure is the system being **right**, not a recall gap.
Chasing them would mean loosening the traversal until it produced exactly the
ascend-then-redescend false positives section 2 warns against. Recommend striking them
from the golden set; `paprika`, `cayenne`, `chili flakes` are all genuine and all pass.

---

# Addendum 2 — sign-off, the agency branch, and two FoodOn defects

## F8-resolved. Repair sign-off complete

76 of 77 repairs applied (75 high confidence, 1 medium), 1 declined, 0 outstanding.
Decisions recorded in `config/repair-signoff.json` with a rationale each; the
classifier consults that file, so a FoodOn version bump re-runs the automated
signals and re-presents only what the sign-off does not already cover.

- **declined**: `avian food product → avian animal` — class rank (Aves), a 319-node
  source subtree, too coarse to accept.
- **medium confidence**: `ginseng food product → ginseng plant` — the source genuinely
  mixes genera (three *Panax* species plus *Eleutherococcus senticosus*).

Reviewing the actual subtrees rather than reasoning from general botany overturned
four of my own research flags: `sorrel` (subtree is entirely *Rumex*, no *Hibiscus*),
`nasturtium` (all *Tropaeolum*, no watercress), `sarsaparilla` (products name
*Smilax aristolochiifolia* explicitly, no *Aralia*), `angelica` (only *A. archangelica*
and *A. sylvestris*, no toxic congener). Only the `ginseng` flag survived contact with
the data. A `sage` recommendation was also corrected mid-review: my mention of
sagebrush implied *Artemisia* was reachable, when the subtree is entirely *Salvia*.

**Lesson for the remaining LLM-assisted passes (sections 3 and 6): general knowledge
about a term generates the hypothesis, but the subtree has to be read before the
hypothesis is trusted.** Four of five flags were false alarms about material that
isn't in FoodOn at all.

## F10. The `agency food product type` branch must be excluded from traversal

FoodOn carries parallel regulatory classification vocabularies — EFSA FoodEx2,
US CFR, EC, CCPR — under a single root, `agency food product type`
(FOODON:03400361): **6,074 classes, 15.2% of the ontology.**

These are classification *facets*, not composition. Traversing them is actively
dangerous: `00030 - cereal grains (and cereal-like grains)` is a single 63-class
grouping containing wheat, maize, rye, barley and rice. Any traversal that entered
this branch would leak corn into wheat immediately — the exact failure the section 2
invariant exists to prevent, reachable without ever ascending the *food* hierarchy.

Excluded from derivation traversal. Note the same branch is likely **useful** for
section 6's functional rollup and for the ingredient-label granularity boundary,
since the US CFR groupings are literally regulatory ingredient vocabularies — the
`nutritive sweetener (us cfr)` grouping already showed up attached to corn syrup,
dextrose and their variants.

## F11. Two genuine FoodOn defects, both allergen-relevant

`build/detect_misparent.py`. Reported for review only — re-parenting alters the
hierarchy, a heavier edit than adding a derivation edge.

The detector needed four rounds of sharpening because label-vs-ancestry disagreement
is *normal* in FoodOn: classes are legitimately parented by food type
(`almond cheese → nut cheese`), preparation (`albacore (raw) → fish meat (raw)`) and
function (`allspice → spice food product`). Successive filters — exclude the agency
branch, exclude imported taxa parented by Latin rank name, and finally require the
conflicting parent to name a *different specific source organism* — took 3,150
candidates to 104, and a preparation-word filter to a 26-row review queue.

Yield: **2 confirmed defects.** Precision is low by design; this is a review queue,
not a repair.

| defect | consequence |
|---|---|
| `rye kernel` parented under `sumac food product` (IDs 00003734 vs sumac berry 00003733 — an adjacent-ID data-entry slip) | **gluten false negative**: a rye query misses `rye kernel` and its raw/cooked/dried forms |
| `hickory nut` parented under `mustard spinach food product` | **tree-nut false negative**: `hickory tree` has a closure of 1. `pecan` sits *under* `hickory nut`, so both are orphaned from their tree |

Both are false negatives, the safety-failing direction, and neither is reachable by
any amount of correct traversal — the edges simply are not there. These are the first
genuine candidates for `overrides.json`, and unlike paprika they are not fixable by a
general rule, because a mis-parenting is arbitrary by nature.

---

# Addendum 3 — relation policy and traversal

## F12. `direction: "both"` is unsafe; every relation propagates one way

The spec's sketch for `relation_policy.json` gives `"direction": "both"`. That would
reintroduce the section 2 failure. `derives from` is asserted *product → source*, so
from a source query avoidance travels object → subject. Permitting both directions
allows `product → source → sibling product`: ascend-then-redescend wearing a
different hat, reachable through a relation rather than through `is_a`.

`config/relation_policy.json` therefore accepts only `inverse` (object → subject,
which is almost everything) and `forward` (subject → object). `part_of` is the sole
relation already asserted in the direction avoidance travels. `build/traverse.py`
raises on any other value rather than guessing.

**14 propagating relations** covering 7,026 edges; **18 non-propagating** covering
4,732. Nothing unclassified. Three judgements worth surfacing:

- **`member of` (2,343 edges) does not propagate.** Its targets are almost entirely
  US CFR regulatory groupings. Propagating it would link every nutritive sweetener
  to every other one. It is instead the primary input to the section 6 rollup —
  answering that open question: FoodOn's role coverage is thin, but this US CFR
  grouping layer is a ready-made culinary-function vocabulary, already tagging 51 of
  189 corn nodes (`nutritive sweetener`, `milled grain or starch product`).
- **`has food substance analog` (38 edges) must never propagate.** It asserts
  `imitation peanut butter → peanut butter`. An analog is defined by *not* containing
  what it imitates; propagating it would flag the substitute as containing the
  allergen. Surfaced in the UI as "related, verify separately", never as containment.
- **`output of` / `is specified output of` do not propagate.** They point at
  processes (`food (canned) → food canning`), not ingredients.

## F13. The invariant is structural, not a check

`build/traverse.py` builds its adjacency once, containing only edges in the
propagating direction. `rdfs:subClassOf` is indexed parent → child; child → parent is
never added. There is no code path that ascends, so no configuration error can
create one — the invariant holds by construction rather than by a guard that could be
bypassed.

Two phases, as section 4 requires: taxonomic descent to members, then derivative
traversal from every node phase 1 reached. A leaf query makes phase 1 a no-op, so
both query kinds use one code path.

### Root expansion — the general fix for FoodOn's split hierarchies

The nightshade case needs both `Solanaceae` and `solanaceae plant`; allium needs both
`allium` and `allium species`. Hardcoding each pair is the special-casing the spec
forbids, so correspondence is derived two ways, both **lateral** (same organism,
different hierarchy) and therefore invariant-safe:

- **taxon pivot** — `root --in taxon--> T` where T is **species rank**. The rank
  requirement is the safety property: `peanut plant → Arachis hypogaea` is lateral,
  but a pivot to a genus or family would silently widen the query to a broader
  organism. Without this, a `peanut plant` query returned 1 node.
- **label convention**, applied in both directions — FoodOn names its own copy of a
  taxon `<taxon> species` / `<taxon> plant`. Symmetric, so either side of a split
  resolves to the same graph: `solanaceae plant` and `Solanaceae` both give 480 nodes.

## F14. Results

```
corn        189 nodes  212 edges   22 multi-path   51 nodes rollup-tagged
nightshade  480 nodes  569 edges   86 multi-path   162 convergent across roots
allium      137 nodes               (5/5 members, cross-root convergence present)
```

`test/run.py`: **57 assertions pass**, covering the two spec golden cases, three novel
cases never tuned against (walnut/tree nut, peanut/legume, shellfish), both
ascend-then-redescend invariants, cross-root convergence, and an assertion on every
case that no agency-branch class leaks in.

The paprika edge is visible in the output with `repair` provenance:
`hungarian wax pepper plant --derives from--> hungarian wax pepper food product`,
with `paprika (ground)` reached at depth 5, convergent from both roots.

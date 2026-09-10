# Project: FoodOn-Grounded Ingredient Avoidance Graph

## Goal

Build a tool that lets a user type in an ingredient (`paprika`, `corn`, `edamame`) or a
class (`nightshade`, `allium`, `dairy`) and:

1. Resolves that free-text input to the best-matching class in the **FoodOn ontology**
   (foodon.owl), grounded by **culinary usage**, not preparation method.
2. Walks the ontology to find every ingredient/derivative that should be treated as
   "contains this" for allergy/avoidance purposes — including ones reached through a
   **different branch or relation type** than the one the user's term lives in.
3. Renders the result as an **interactive node-link graph**, so the user can see *why*
   something is flagged (which path connects it back to their query).

This is a grounding/graph layer, not a full recipe parser — assume recipes are already
decomposed to atomic ingredients before they're checked against this system (i.e. we
never need to reason about "mayonnaise," only "egg," "soybean oil," etc.).

**Generality requirement:** corn, nightshade, dairy, allium, etc. are *test cases*,
not the scope. The system must work for any ingredient or class a user types in,
including ones nobody thought of during development. That means the traversal and
matching logic has to come from general rules discovered in FoodOn's own structure —
its naming conventions, ID namespaces, annotation properties, and axiom patterns —
not from a hand-maintained list of "corn → corn starch, corn oil, ..." mappings. A
hardcoded exception list is a sign the ontology-side logic hasn't found the general
rule yet, not an acceptable fallback. Treat any case that seems to need a manual
override as a prompt to go back and find what structural pattern in FoodOn should
have covered it instead. The one exception to "no manual overrides" is section 3
below — regulatory/culinary mismatches are a real category, not a workaround, and get
their own governed file rather than being smuggled into the general rules.

**Target output granularity — ingredient-label level.** Do not decompose past what
would appear as a distinct item on a packaged food's ingredient label (e.g. stop at
"corn starch," "modified corn starch," "dextrose," "soy lecithin" — do not continue
into molecular/chemical-formula territory). This bounds both the traversal depth and
which FoodOn branches are in scope: the target nodes are FoodOn's food-product/
material-entity classes, not the chemistry-ontology classes (ChEBI etc.) that FoodOn
sometimes imports or points to underneath a product class. Use the branch-structure
audit in section 1 to identify the FoodOn branch(es) that correspond to "ingredient as
sold or used" and treat descent past that boundary as out of scope by default.

## Why this is hard (read before building)

FoodOn is not a single clean is-a tree. A term like "paprika" is a *processed culinary
product* that relates to "nightshade" only by way of its source organism
(*Capsicum annuum*), not by direct subsumption under a "nightshade" food category. Two
separate paths can converge on the same real-world entity:

- Path A: `nightshade family (Solanaceae)` → `Capsicum` (genus) → `Capsicum annuum`
  (species) → `paprika` (processed product, via `derives_from` / `has_ingredient`)
- Path B: `nightshade vegetables` (a culinary/food-product grouping) → `pepper` →
  `paprika`

If the traversal only follows one relation type (e.g. `rdfs:subClassOf` /
`BFO:is_a`), it will miss derivative relationships that live on `derives_from`,
`has_ingredient`, `part_of`, or `develops_from` edges — producing false negatives on
exactly the cases in the prompt (corn starch, malto-dextrin, black pepper, cayenne).
Conversely, if two paths reach the same OWL class by different routes, the graph must
recognize it as **one node with two incoming edges**, not two nodes — otherwise the
UI will show duplicate entities and the user won't be able to tell that both paths
"agree."

**This convergence-detection logic is the core intellectual challenge of the project.
Design and test it before building the UI on top of it.**

### The other failure mode: ascend-then-redescend

The opposite risk is just as dangerous for a safety tool: traversing *up* to a shared
ancestor and back *down* into an unrelated sibling branch. Corn and wheat are both in
Poaceae (the grass family) — if the traversal is allowed to climb to a shared ancestor
and then descend again, it will conclude wheat is corn-related, which is simply wrong.

**This must be enforced as a hard structural invariant in the traversal algorithm, not
as a config file of allowed/disallowed pairs.** A pairwise exception list is the wrong
tool here — it doesn't scale (every ancestor node could pair with every descendant) and
it's exactly the kind of hand-maintained special-casing the generality requirement is
trying to avoid. The correct fix is algorithmic: from the resolved query node, only
traverse edges that move toward more specific/derived classes (children, `derives_from`
sources feeding into more processed products, part-of relations moving toward the
whole ingredient) — never traverse an edge that moves toward a more general class and
then back down. Write this as an explicit invariant and a unit test (query = corn,
assert wheat is never reached; query = wheat, assert corn is never reached),
independent of whatever relation-type configuration ends up in section 1.

Where a config file *does* help is different: which relation types are trustworthy
enough to propagate avoidance through at all, discovered via the ontology audit below,
not which node-pairs are acceptable.

## Requirements

### 1. Ontology grounding

- Load `foodon.owl` with `owlready2` (reuse whatever loading/query pattern already
  works from the existing allergen-detection pipeline — do not re-derive this from
  scratch).
- Before writing any traversal logic, do a structural audit of FoodOn itself and
  derive general rules from what you find, rather than reasoning ingredient-by-
  ingredient. Specifically look for:
  - **Object property inventory**: every object property actually used in the
    ontology (not just the commonly-cited ones) — their domains/ranges, and how
    consistently each one is applied. Some may be sparsely used or applied
    inconsistently; note that rather than assuming uniform coverage.
  - **ID namespace / IRI conventions**: FoodOn IDs (e.g. `FOODON:xxxxxxx`) often
    encode which upper-level branch a class belongs to (product, raw material,
    organism, role, quality, process, etc. — OBO Foundry classes like BFO/ChEBI/
    ENVO/PO/UBERON are imported and reused within FoodOn). Understand this
    branch structure generally — it's what tells you, for *any* class, whether it's
    a "food product" node, a "source organism" node, a "material entity" node, etc.,
    without special-casing individual ingredients. This is also what defines the
    ingredient-label-granularity boundary described above.
  - **Annotation properties / labels**: synonyms, alternate labels, and any
    "scientific name" vs. "culinary name" annotation pattern FoodOn uses — this is
    likely central to culinary-usage grounding and to matching free text without an
    LLM having to guess blind.
  - **Naming/tagging conventions in class labels themselves** (e.g. consistent
    suffixes or qualifiers marking a class as a processed product, a plant part, a
    preparation state, etc.) that could be parsed programmatically rather than
    inferred per-case.
  - Use this audit to produce a **relation-type policy file** — see 1a below — plus a
    written rule set describing branch roles (which branches are source organisms,
    which are products, which property links one to the other). Document it
    explicitly so it can be tested and revised as a whole, rather than accumulating
    one-off patches per failing test case.
- Ingredient identity should be resolved at the level of **presence of substance**,
  ignoring preparation state (raw/cooked/dried/ground) — if FoodOn models
  preparation-state siblings as distinct classes, use whatever general annotation or
  naming pattern marks something as a preparation-state variant (found during the
  audit above) to collapse them automatically, rather than listing preparation words
  to strip.

#### 1a. Relation-type policy file (`relation_policy.json`)

Externalize *which object properties propagate avoidance* as a small, versioned
config file rather than burying the decision in code:

```json
{
  "version": "2026-09-08",
  "propagating_relations": [
    {"property": "derives_from", "direction": "both", "confidence": "high"},
    {"property": "has_ingredient", "direction": "both", "confidence": "high"},
    {"property": "part_of", "direction": "both", "confidence": "medium"}
  ],
  "non_propagating_relations": [
    {"property": "has_quality", "reason": "quality/role annotation, not composition"}
  ]
}
```

This file is generated from the section 1 ontology audit — use an LLM-assisted pass to
propose the initial classification of each discovered object property (propagating vs.
not, and at what confidence), but **treat the proposal as a draft requiring your
sign-off before it governs traversal**, since a wrong classification here has direct
safety consequences (a wrongly-excluded property causes false negatives; a
wrongly-included one causes false positives). Re-run the audit and diff against this
file if FoodOn is ever updated to a new release.

### 2. Free-text → FoodOn class resolution (LLM step)

- Input can be a specific ingredient (`edamame`) or a class-level term
  (`nightshade`, `allium`, `dairy`).
- Use an LLM call to propose the best FoodOn class match(es), grounded in **culinary
  usage** — e.g. "black pepper" should resolve based on how it's used and understood
  in food, not get sent down a purely botanical disambiguation path that misses the
  culinary product class if one exists.
- Reuse the prompt-engineering finding already validated in the allergen-detection
  project: **few-shot, worked-example-anchored prompts** measurably outperform
  baseline/definitional/chain-of-thought/label-constrained approaches for this kind of
  term grounding (~99% consistency in that earlier work). Carry that prompt strategy
  forward here rather than re-testing from zero — but do re-validate it specifically
  against class-level queries (nightshade, allium), since the earlier testing was
  scoped to leaf ingredients.
- Handle ambiguity explicitly: if the LLM can't confidently pick one class, return
  candidates with confidence scores rather than silently guessing.

#### 2a. Resolution store — resolve once, reuse forever

Once an input string is resolved to a FoodOn class, that resolution is **persisted
and reused** — it is not re-queried on every request. Key the store by
`(input string, FoodOn ontology version, prompt/LLM version)` so that:
- Repeated queries for the same term are instant and deterministic (no LLM call).
- If FoodOn is updated or the resolution prompt changes, old resolutions are not
  silently assumed still valid — they're flagged for re-validation rather than
  auto-reused across a version change, so the golden-set tests keep meaning what they
  meant when they were written.
- A human can inspect and correct a stored resolution directly (edit the store),
  and that correction sticks until something invalidates it (ontology or prompt
  version bump).

### 3. Regulatory / culinary overrides (`overrides.json`)

FoodOn's structure is ontologically faithful, but a small number of avoidance-relevant
groupings are legal/regulatory rather than botanical, and will never fall out of the
ontology no matter how well the traversal logic works. Coconut is the canonical
example: botanically a drupe, but classified as a tree nut for U.S. allergen labeling.
These are genuine exceptions, not a sign the general rules failed — give them their
own governed file rather than letting them leak into the relation-policy or traversal
logic:

```json
{
  "version": "2026-09-08",
  "overrides": [
    {
      "type": "add",
      "query_class": "tree_nut",
      "target_class": "coconut",
      "reason": "FDA allergen labeling classifies coconut as a tree nut despite botanical classification as a drupe",
      "source": "FDA FALCPA guidance",
      "reviewed_by": "Matt",
      "reviewed_date": "2026-09-08"
    }
  ]
}
```

- `"add"` overrides inject a relationship the ontology doesn't structurally support
  (regulatory groupings, or genus/botanical alignments FoodOn hasn't modeled — see
  below).
- `"remove"` overrides suppress a specific edge that's ontologically real but not
  avoidance-relevant, if one is ever found (keep the type available even if unused at
  launch).
- Every entry requires a reason, a source, and a human reviewer — this file is small
  and high-signal by design, not a dumping ground. If it starts growing quickly,
  that's a signal to revisit the relation-policy file or the branch-role rules
  instead of keeping the override list as the primary fix.
- **Discovery, not just capture:** use an LLM-assisted research pass to proactively
  scan for known cases where botanical/genus alignment or regulatory grouping implies
  a relationship that FoodOn's graph structure doesn't directly connect — same
  approach as the allergen-detection project's "hidden allergen" work (barley malt in
  Rice Krispies, soy in pan spray were only findable by going beyond keyword
  matching). Treat the LLM's output as candidate entries for human review, not
  auto-applied additions — this file gates traversal-level safety decisions, so
  nothing lands in it without your sign-off.

### 4. Graph construction

- Given one or more resolved root classes, build a graph of all classes connected to
  them via the propagating relations from `relation_policy.json`, plus any applicable
  entries from `overrides.json`, subject to the ascend-then-redescend invariant, out
  to a configurable depth.
- **Class-level queries need two traversal phases, not one uniform walk:** first
  descend taxonomically from the class to its members (e.g. `allium` → garlic, onion,
  leek, shallot, chives), then run the normal derivative traversal from *each* member
  as its own root. A single-pass walk that tries to do both at once will either stop
  too early (member list only, no derivatives) or get tangled. Design these as two
  composable stages, not one.
- Nodes = FoodOn classes actually reached. Edges = the specific relation type
  traversed (is_a, derives_from, has_ingredient, part_of, etc.) — don't collapse edge
  semantics, the user should be able to see *what kind* of relationship connects two
  nodes. Tag each edge with whether it came from direct ontology traversal or from
  `overrides.json`, so the provenance is always visible.
- Merge nodes reached via multiple paths into a single node with multiple incoming
  edges — this includes convergence *across* multiple roots in a class-level query
  (e.g. if garlic and onion both lead to the same downstream product node, that
  product should appear once, not twice). Write a specific test case for the
  paprika/nightshade scenario, the corn/corn-starch/malto-dextrin scenario, and a
  cross-root convergence case under a class query, to confirm this works before
  moving on.
- Output as a clean JSON graph structure (nodes with FoodOn IRI + label + a rollup
  group tag if available — see section 6, edges with type + direction + provenance)
  that a frontend can consume directly.

### 5. Visualization

- Interactive node-link diagram. For a single-ingredient query, one root node
  radiating outward. For a class-level query, **one or more root-level nodes**
  representing the taxonomic members, feeding into their own derivative subtrees —
  the diagram should make clear these are siblings under a shared class, not
  independent unrelated roots.
- Distinguish edge types visually (e.g. line style or color per relation type), and
  make multi-path convergence visually obvious (e.g. a node with 2+ incoming edges
  from different branches, or from different root members, should look different
  from a plain leaf).
- Distinguish provenance: an edge sourced from `overrides.json` should look visually
  distinct from one derived directly from ontology traversal, so a user (or you,
  reviewing) can always tell an override from a structural match.
- Expand/collapse subtrees, hover/click for node detail (FoodOn IRI, label, which
  relation types lead to it, confidence if it came from the LLM step rather than a
  direct traversal).
- Suggested stack: force-directed layout (D3.js) inside a React component, since the
  existing React front-end work can likely be extended rather than started fresh.
  Vis-network or Cytoscape.js are reasonable alternatives if force-directed layout
  gets messy at depth — use your judgment once you see real graph sizes.

### 6. Culinary-function rollup (for readability, not for the underlying data)

A fully expanded "dairy" or "allium" graph could run to hundreds of nodes — not
something a force-directed layout renders legibly. Rather than truncating results
(which would work against the recall-first policy below), group nodes by culinary
function (sweetener, thickener, emulsifier, leavening agent, etc.) as a *view-layer*
concern:

- Check during the section 1 ontology audit whether FoodOn already carries
  functional-role annotations (OBO's relations ontology includes `has_role`-style
  properties, which FoodOn may use for exactly this). If so, use them directly —
  this is the "minimal overrides" outcome and should be preferred.
- If FoodOn's role coverage is thin or inconsistent, generate a supplementary
  **functional-role tag store** (same pattern as the resolution store in 2a: LLM-
  assisted tagging, cached, versioned, human-reviewable) rather than hardcoding a
  sweetener/thickener/etc. list per ingredient by hand.
- Critically: **the underlying JSON graph keeps full node/edge fidelity regardless.**
  Grouping is something the frontend applies for display (collapsed-by-default
  functional clusters that expand on click) — never lose data to make the picture
  smaller.

### 7. Recall-first policy

For an allergen/avoidance tool, a missed derivative (false negative) is a safety
failure; an over-flagged safe ingredient (false positive) is a usability annoyance.
These trade off against traversal depth, which relation types propagate, and
confidence thresholds — so default every one of those knobs toward **completeness
over precision**: deeper traversal, more permissive relation-type inclusion in
`relation_policy.json`, lower confidence threshold before something is at least shown.
Compensate for the resulting false-positive risk with **visible confidence, not
silent filtering** — every edge/node should carry enough provenance (direct ontology
match vs. LLM resolution vs. override, and a confidence tier) that a stricter
downstream consumer (or a more cautious user) can choose to hide low-confidence nodes
themselves, rather than the system deciding for them by never surfacing it at all.

### 8. Interface

- Minimal: one text input, submit, graph renders. Support both a single ingredient
  and a class name in the same input — the resolution step should figure out which
  kind of thing it's looking at.
- Show the resolved FoodOn class name/IRI and confidence alongside the graph so the
  user (or you, during testing) can sanity-check the grounding.

### 9. Testing / validation

- Build a small golden set of query → expected-derivative-set pairs covering the
  cases in the original spec: corn (corn starch, corn oil, malto-dextrin, dextrin),
  nightshade (black pepper, white pepper, paprika, cayenne, chili flakes). These
  exist to validate the general rule set above, not to be individually coded for —
  if a case fails, the fix should be a correction to the general rules or a
  reviewed override entry, not a new special case bolted into the traversal code.
- Add several query terms *not* discussed anywhere in this spec (pick your own —
  something like a tree nut, a legume, a shellfish class) specifically to test
  whether the general rule set holds up on cases it wasn't tuned against. This is
  the real test of whether the ontology-driven approach worked.
- Add explicit negative tests for the ascend-then-redescend invariant (corn should
  never reach wheat, and vice versa, despite the shared grass-family ancestor).
- Add a cross-root convergence test for class-level queries (two members of the same
  class sharing a downstream derivative should merge into one node).
- Reuse the existing Open Food Facts golden dataset pattern if it's a natural fit for
  generating additional real-world test cases.

## Suggested build order

1. Ontology exploration: enumerate FoodOn's actual object properties, draft
   `relation_policy.json` from that audit. Do this interactively and show me what you
   find before committing to the traversal rules — this decision drives everything
   downstream.
2. Traversal + convergence-merging + ascend/redescend-invariant logic, tested against
   the golden set, no LLM or UI yet (hardcode a few root classes to test against).
3. LLM resolution step + resolution store, tested against both leaf-ingredient and
   class-level queries.
4. Draft `overrides.json` from an LLM-assisted regulatory/botanical research pass,
   human-reviewed before it's wired into traversal.
5. Wire resolution → two-phase traversal → overrides → JSON graph output.
6. Frontend graph rendering, including provenance/confidence styling and
   functional-rollup grouping.
7. End-to-end pass on the full golden set, including the negative/invariant tests.

## Open questions to flag back to me if they come up

- Whether FoodOn's actual object property set supports the derives_from-style edges
  needed for the corn/nightshade examples cleanly, or whether some of these
  relationships need to lean more heavily on `overrides.json` than expected (this may
  turn out to be necessary — don't force a bad fit if the ontology doesn't have it).
- Whether FoodOn's functional/role annotations are rich enough to drive the
  culinary-function rollup directly, or whether the supplementary tag store in
  section 6 ends up doing most of the work.
- Depth limit for traversal (unbounded traversal on a big ontology could produce
  unusably large graphs for common classes like "dairy" even with rollup grouping
  applied).

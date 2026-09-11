# FoodOn-Grounded Ingredient Avoidance Graph

Type an ingredient (`paprika`, `edamame`) or a class (`nightshade`, `allium`, `gluten`)
and see everything that should be treated as containing it — with the path that
justifies each one.

```bash
python3 serve.py            # http://localhost:8790
```

**Find in graph** (the magnifier, or `/`, or ctrl/cmd-F) searches every class in the
current result, not just the ones on screen — labels and synonyms both, since terms
like `spelt` and `semolina` exist only as synonyms. Choosing a hit expands the path
down to it and pans there, so a match collapsed four levels deep is one click away.

A **JSON drawer** slides out from the right edge (the tab marked `JSON`), collapsed by
default. It shows the graph as **one document**: every node and edge carries a
`legend` key naming its category — `query root`, `derives from`, `override` and the
rest — and records are ordered by that category, so the legend groups read as
contiguous blocks without the graph being split apart. A key above the JSON lists the
categories with the legend's own swatches and counts.

`compact` (the default) identifies classes by curie and puts both endpoint labels on
each edge, so an edge reads without cross-referencing; `full` restores IRIs,
definitions and synonyms. Compact keeps every node and every edge — it drops repeated
identifiers and prose, not records. Rendering is capped at 400k characters, which only
the largest closures reach; the copy buttons always emit the complete document.

Nothing calls an LLM at query time. Semantic judgements were made once, offline, and
frozen into reviewable files.

## Reading the graph

**Layout is a radial dendrogram, not a force simulation.** Measured: 83% of the
nightshade closure and 89% of corn have in-degree 1, so a closure is a tree with a few
extra edges — and a force layout is the wrong instrument for that. `forceRadial` pinned
each node to a ring by depth but nothing ordered them *within* the ring, so siblings
from different parents interleaved and their edges crossed back and forth. `d3.cluster`
places every node deterministically: no node overlap and no crossings among tree edges,
guaranteed by the layout rather than negotiated by forces, and identical on every
reload. The remaining ~15% of edges — a term with a second parent — are drawn as curves
bowed through the centre, so nothing is hidden; they are the only lines that can cross,
and they are the ones worth looking at.

**Every leaf sits on the outer ring.** The leaves are the answer to the query — the
things you must not serve — and on the rim they all sit at the maximum radius, where the
circumference is greatest and each one gets the same generous slice of arc. Under
`d3.tree` a leaf sat at its own depth, so a shallow leaf landed on a small ring holding
almost no arc; that is where the crowding was worst. Switching to the dendrogram took
nightshade from 45 labels to **115, with zero collisions**.

The cost, stated plainly: **radius no longer means hops-from-the-root.** In a dendrogram
an internal node's radius is its distance to the deepest leaf beneath it, so a grouping
class with a shallow subtree sits further out than one with a deep subtree. Hop count
moved to the tooltip and the breadcrumb, which report it exactly rather than by eye.

Angular space is allocated per *leaf*, not per subtree, so a wedge is as wide as what is
actually in it. `size([2π, R])` splits the circle evenly between the root's children,
which gave nightshade's 17-term `solanaceae plant` the same half of the canvas as its
130-term `Solanaceae`.

The drawing is sized to its content — arc per leaf, and a ring gap measured from the
labels this query actually has — and never to the pane. That gap used to be a flat 62px
whose own comment said it existed "so the rings stay far enough apart for an internal
node's label to run outward without immediately meeting the next one". It never did
that: on a citrus query the rings land 62px apart and the median label is 93px, so a
typical name ran a ring and a half outward, straight across the nodes sitting there —
`Citrus limonia` printed over its neighbour. The floor is now the **45th percentile of
the query's own label lengths** (capped at 180px, or one query of EFSA code-list names
would set a gap nothing could read). Measured on citrus expanded to 149 nodes:

| ring gap | radius | labels shown | crossings |
|---|---|---|---|
| 62px, flat | 248 | 73 | many |
| 124px, measured | 494 | 133 | 0 |

More labels *and* none of them overlapping, because wider rings let the planner admit
candidates it used to have to drop.

**Each ring gets the gap its own labels need, not a shared one.** A uniform gap makes an
empty ring cost exactly as much radius as a full one, and in a dendrogram the inner rings
are nearly always the empty ones: every leaf is pushed to the rim, so what is left inside
is the skeleton. Measured on `pepper` — 122 drawn nodes in rings of 1, 1, 2, 2, 5, 7, 25,
79. **The six innermost rings held 18 nodes between them and took 973px of radius**, which
is the hole in the middle of that drawing. A ring carrying two labels or fewer has the
angle to itself and cannot realistically be blocked, so it gets the 62px minimum; a
crowded ring keeps its full allowance.

| query | radius before | radius after | on-screen scale | labels | crossings |
|---|---|---|---|---|---|
| `pepper` | 1297 | **802** | 0.25 → **0.37** | 108/122 | 0 |
| `citrus` | 494 | **401** | 0.55 → **0.64** | 124/149 | 0 |

None of this is what keeps labels off nodes — the clearance test does that, at any
spacing. Ring gaps only decide how many labels survive, so compressing an empty ring
costs nothing and buys back the radius. Sizing it to the pane made a 2-node `paprika` query fill the canvas
with two nodes 660px apart and their labels turned vertical. At four leaves or fewer the
labels are counter-rotated back to horizontal, because the radial form buys nothing at
that size.

**Labels are placed by geometry, not by a budget.** A label must clear every other
label *and every node* — the planner only ever compared labels with labels, so a name
could be drawn straight through a circle on the next ring out and nothing objected.
Wider rings fix the typical case by geometry; the node test catches the tail that is
longer than the gap, and drops it rather than printing over a node. Candidates are
considered in priority order — roots, clusters and collapsed parents first, then grouping classes,
organisms, multi-path nodes, leaves — and one is admitted only if it clears every label
already placed, testing arc distance and radial run length. Tier order is what makes it
behave: when a ray is contested the more useful name wins it. That matters because
single-child chains collapse onto one ray (`d3.tree` centres a parent over its
children — corn puts 89 nodes on 72 distinct angles), which is a radial collision no
amount of extra circumference fixes. `always show labels` overrides the whole pass.

**A collapsed cluster is named by culinary function, or by nothing at all.** Where
FoodOn supplies a US CFR rollup, the cluster gets a readable category —
`Bakery & Grain Products · 20`, `Thickeners, Stabilizers & Gelling Agents · 9`. That
path works, and `config/function-categories.json` maps all 170 CFR groups FoodOn uses
onto 19 categories with none left over.

But only **2,342 of 39,894 classes** carry a `member of` rollup at all, so across 16
allergen queries 93 of 136 clusters had no category. Those used to read `via is a` or
`via derives from`, which claimed a grouping rationale the data cannot support: every
child in a taxonomy is reached by `is a`, so the label only repeated what the edge
colour already drew. They now read **`16 more`** — the count is the one fact about
such a group that is certainly true, and it is what you act on. The relation stays on
the edge colour and in the tooltip (`reached by derives from`).

Measured before removing it, on the 135 affected clusters: a shared label stem that
adds anything beyond the parent's own name exists for **8%**. Another 27% have a stem
that merely echoes the parent — `potato` under `potato (whole or pieces)`, `pepper
plant` under `hot pepper plant` — which is no better than `via is a`, and 64% have no
stem at all. Role homogeneity was no better: 62% of clusters are role-pure, but the
labels that yields read as `18 derivatives`. FoodOn names children by extending the
parent's name, which is exactly what makes a shared stem redundant here.

Grouping is still by relation even when unlabelled, so two count-only clusters can
hang off one parent with different edge colours. Merging them would force one colour
onto a mixed group and misreport how the members were reached.

One signal per visual channel, and none of them doubles up:

| channel | encodes |
|---|---|
| **fill** | what kind of thing — near-black query root, brass organism/taxon, sage derivative |
| **unfilled dashed ring** | a FoodOn grouping class (`field corn sweetener product`) — scaffolding, not something you can be served |
| **node size + type size** | role rank, on one ladder: root 15 · organism 10 · category 9 · multi-path 8 · leaf 6.5 |
| **stroke ring** | reached by several paths; a dashed outer ring means reached from more than one query root |
| **edge colour + dash** | the relation, and whether the hop is `ontology`, `repair`, `mined` or `override` |

**Hover anything to see why it is there.** The chain back to the query root is dimmed in
and printed along the bottom with the relation named at every hop, provenance included —
which is how paprika answers for itself:

```
… —is a→ hungarian wax pepper plant —derives from (repair)→ hungarian wax pepper food
product —is a→ paprika (ground)          5 hops from the root
```

That `(repair)` is the point: FoodOn omits the axiom, `build/repair_derives.py` supplies
it, and the breadcrumb says so rather than passing it off as the ontology's own claim.
Clicking keeps the chain up; each crumb is clickable to walk back.

The whole drawing is scaled to fit the pane once, measured from the rendered bounding
box so labels are included rather than clipped; `Reset view` returns to that fit. The
measurement happens on an animation frame, not inline — inline, `getBBox` reported a
613px height for a box that settled at 843, and the gluten query was scaled to 1.27x
instead of 0.93x and clipped on both sides.

## Import & patch layer — using this outside the app

The relationships this project establishes are exportable as a standards-compliant
OWL patch layer, so a team can take a fresh vendor `foodon.owl`, apply one file, and
query the same closures over SPARQL with none of this codebase in the loop.

```bash
./tools/apply_patches.sh          # vendor + patches -> merged -> queryable
```

`ontology/foodon.owl` is never modified. Drop in a new upstream release, re-run, and
the patch layer re-applies unchanged; `ontology/foodon.owl.sha256` pins the release
the patches were reviewed against and the script warns when it differs.

| file | role |
|---|---|
| `ontology/foodon.owl` | vendor, untouched, gitignored |
| `ontology/foodon-local-patches.ttl` | **the patch layer** — generated, reviewed, committed |
| `ontology/catalog-v001.xml` | resolves the `owl:imports` to the local vendor copy, offline |
| `ontology/foodon-merged.owl` | the two as one ontology, for a reasoner or an upload |
| `ontology/foodon-avoidance.ttl` | materialised one-hop relations (derived) |
| `ontology/foodon-queryable.owl` | what `build/sparql/patch_*.rq` runs against |

**The patch file is generated, and that is the point.** `build/emit_patches.py`
reads the governed decision files, so the guards, the claim types and the sign-off
records stay the review surface and the tests keep running against them. It is
written to be *read*: every axiom carries a comment block naming the rule, the
guards, the evidence and the reviewer, and the same facts again as a machine-readable
`local:Patch` record so the audit can be done in SPARQL. `test/patch_run.py` asserts
the round trip both ways — a hand-edit to the generated file, or a decision that
fails to export, breaks the build.

**Only `contains` is emitted as `RO:0001000`.** Four claim types are not
containment and get their own declared object properties, each with an
`rdfs:comment` saying so plainly: `local:mayDeriveFrom` (feedstock is a producer
choice), `local:sharesCompoundWith` (the same molecule reached another way),
`local:crossReactiveWith` (the allergen protein is *not* present),
`local:disputedAvoidance`. Emitting these as `derives from` would tell a
corn-avoider that citric acid contains corn.

**One thing OWL cannot do.** An import is monotonic — it adds and never retracts. So
`peanut plant is_a nut producing plant`, which is defensible botanically and wrong
for allergens, cannot be removed by a patch. It is stated declaratively as
`local:notAvoidanceRelevantFor` for a consumer to honour, rather than pretending the
upstream axiom is gone.

**Patch at the most specific true source.** The tempting axiom for the motivating
case is `hungarian wax pepper food product derives from Solanaceae`. That is wrong:
Solanaceae is family rank with a 631-class closure, while the cultivar plant has 9.
The patch names the cultivar, and Solanaceae is reached through FoodOn's own `is_a`
chain — which keeps the axiom correct for a narrower `Capsicum annuum` query too.
This is the same rule `classify_repairs.py` applies when it declines
`avian food product → avian animal` as class-rank.

### SPARQL, and why it needs two relations

```bash
java -jar tools/robot.jar query --input ontology/foodon-merged.owl      --query build/sparql/patch_validate_paprika.rq /dev/stdout
```

```
paprika (ground) | hungarian wax pepper food product | RO:0001000 |
hungarian wax pepper plant | Solanaceae | local:patch-9a1936568ec0
```

That last column is the audit trail: the bridging hop is identified as one this
layer supplied, not FoodOn's own.

Every IRI in the side panel is a link to the OBO PURL resolver, and they all share
one **named** companion tab, so a session of looking terms up leaves you two tabs to
switch between rather than one per term. `target="_blank"` was wrong for this twice:
it spawns a tab per click, and an embedded webview ignored it and navigated the app's
own tab away, losing the query. The trade-off, recorded in the code: `rel="noopener"`
is deliberately absent, because noopener and name reuse are mutually exclusive — the
destination is the OBO Foundry resolver and this is a localhost tool, so the opener
reference is accepted. Revisit if it is ever served publicly.

SPARQL 1.1 property paths cannot step through a blank-node `owl:Restriction`, so
"subClassOf plus propagating properties" has no single-path form. The one-hop
relation is materialised first and a `+` path closes over it, and it takes **two**
relations rather than one:

- `local:propagatesTo` — derivative propagation, always source → product, so a
  closure over it can never ascend to a shared ancestor and come back down
- `local:pivotsTo` — the rank-guarded forward `in taxon` hop to a species-rank taxon

They are separate because the pivot belongs to the *taxonomic* phase: it fires from
a class reached by `is_a` descent from the root, never from a derivative. Folding
them together is wrong in both directions — measured, omitting the pivot loses
`Brassica juncea` and `brown mustard plant` from a mustard query, and applying it
everywhere pivots `Nirvana corn kernel` up to the species `Zea mays` and gains three
cultivars the app does not reach. `patch_closure.rq` composes them as two phases.

Which properties propagate is **read from the patch layer**, not hardcoded in the
query: `emit_patches.py` writes `local:propagatesAvoidance "inverse"` from
`config/relation_policy.json`, so the policy has one source of truth.

**Verified parity.** `test/patch_run.py` runs the SPARQL closure and the application
traversal over the same roots and requires them to agree exactly:

| root | app | SPARQL | diff |
|---|---|---|---|
| Solanaceae | 630 | 630 | 0 |
| Maize plant | 188 | 188 | 0 |
| wheat plant | 744 | 744 | 0 |
| sesame plant | 18 | 18 | 0 |
| mustard plant | 25 | 25 | 0 |
| Capsicum | 176 | 176 | 0 |

### Retiring a patch upstream has fixed

```bash
java -jar tools/robot.jar query --input ontology/foodon.owl      --query build/sparql/patch_native_axioms.rq data/native-axioms.csv
python3 build/check_upstream_fixes.py
```

The comparison is against the **vendor file alone**, because the patch layer is
additive and leaves no seam: once merged, our axiom is indistinguishable from
FoodOn's. Currently 93 of 93 patches are still doing work. Nothing is deleted
automatically — retiring goes through the same sign-off, using the `superseded`
status, so the record of why the gap existed survives the fix and
`test/override_run.py` keeps asserting the target is still reached.

A triplestore keeps the vendor graph separate and so can do this in one query;
`build/sparql/named_graphs.ru` has the ingest, the base-graph-only replacement and
that check for a SPARQL 1.1 Update endpoint. It is optional — the ROBOT merge needs
no infrastructure.

## Reclaiming disk

About 160 MB of what sits in `data/` and `ontology/` is derived and rebuildable. All
of it is already gitignored, so this is a local-disk question only.

```bash
./tools/clean.sh                 # dry run: what would go, and the rebuild cost
./tools/clean.sh --sparql --yes  # ~85 MB, 19s to rebuild
./tools/clean.sh --build  --yes  # ~73 MB, 12s to rebuild
./tools/clean.sh --all    --yes  # both
```

Dry run by default; nothing is deleted without `--yes`.

The app opens exactly seven files at startup — `data/index.json` plus
`repairs-classified.json`, `mined-classified.json`, `resolution-store.json` and three
configs. Everything else is either a vendor download or an intermediate. `--build`
does remove `index.json`, so the app will not start again until
`build/build_index.py` has re-run; `--sparql` touches nothing the app reads, and
costs only the parity half of `test/patch_run.py`, which degrades to 6 assertions
with a message rather than failing.

Two guards, and the second is the one that matters:

- the vendor files (`ontology/foodon.owl`, `tools/robot.jar`) are on an explicit deny
  list — they are downloads, not derivations, so re-fetching them is a network round
  trip rather than a build step
- **anything git tracks is skipped**, checked per file against the index rather than
  trusted to the path lists. `repairs-classified.json` and `mined-classified.json`
  look like intermediates and are read by the traversal at startup;
  `resolution-store.json` is a governed decision. A typo in the target list cannot
  destroy a reviewed decision — verified by adding two governed files to the list and
  confirming they were skipped with a reason while the derived files went.

## Getting the two vendor files

Neither is committed: both are large, hash-pinned and downloadable. A fresh clone
needs them before anything will build.

```bash
mkdir -p ontology tools

# FoodOn 2025-12-30 (40 MB). Any release works; the patch layer is re-applied
# against whatever is here, and tools/apply_patches.sh warns when it differs from
# the pinned hash.
curl -L -o ontology/foodon.owl http://purl.obolibrary.org/obo/foodon.owl
shasum -a 256 -c ontology/foodon.owl.sha256

# ROBOT 1.9.10 (79 MB)
curl -L -o tools/robot.jar \
  https://github.com/ontodev/robot/releases/download/v1.9.10/robot.jar
shasum -a 256 -c tools/robot.jar.sha256
```

Both `.sha256` files ARE committed, so a mismatch is visible immediately: for ROBOT
it means the wrong version, and for FoodOn it means a release the local patch layer
has not been reviewed against.

## Build and test

```bash
java -Xmx10g -jar tools/robot.jar convert -i ontology/foodon.owl --format json -o data/foodon-asserted.obo.json
java -Xmx12g -jar tools/robot.jar query   -i ontology/foodon.owl --query build/sparql/structure.rq data/structure.csv
python3 build/extract_edges.py        # restrictions -> data/restrictions.csv
python3 build/verify_extraction.py    # fails if any restriction is lost
python3 build/build_index.py          # -> data/index.json
python3 build/repair_derives.py       # omitted derives-from axioms
python3 build/classify_repairs.py     # auto-apply vs sign-off
python3 build/mine_definitions.py     # origin phrasing in FoodOn's own prose
python3 build/classify_mined.py       # -> review queue; applies only what is signed
python3 build/emit_patches.py         # -> ontology/foodon-local-patches.ttl
./tools/apply_patches.sh              # vendor + patches -> queryable ontology
python3 build/build_relation_policy.py
python3 build/build_resolution_store.py
python3 build/validate_store.py

python3 test/run.py             # 116 golden + invariant assertions
python3 test/resolution_run.py  # 155 resolution assertions
python3 test/override_run.py    # 61 assertions: signed claims do what their claim says
python3 test/mined_run.py       # 123 assertions: nothing unsigned reaches an answer
python3 test/allergen_run.py    # real allergen derivative coverage
python3 test/patch_run.py       # 12 assertions: the .ttl export means what the app means

python3 build/audit/probe.py    # the one-off discovery scripts; see build/audit/README.md
```

## Layout

```
ontology/    vendor foodon.owl (gitignored) + the local patch layer + merge products
config/      the governed decisions -- see the table below
data/        derived indexes and classified candidate sets
build/       the pipeline, in the order the Build section runs it
build/audit/ one-off discovery scripts, provenance for audit/01-structural-audit.md
build/sparql/ extraction and patch-layer queries
test/        six suites, ~440 assertions
web/         the UI (React + D3, no build step)
tools/       robot.jar and apply_patches.sh
```

`build/` holds three kinds of script and the directory alone does not distinguish
them, so: the **pipeline** ones are exactly those listed in the Build section, in
that order. The **generators** for governed files — `build_function_categories.py`,
`draft_overrides.py`, `make_allergen_golden.py`, `detect_misparent.py` — run rarely
and are safe to re-run: each carries a decision forward rather than restamping it.
`policy_sensitivity.py` is a verification harness cited by
`config/relation_policy.json` as the method behind each direction ruling. Everything
that ran once and produced the structural audit is under `build/audit/`.

Two files look dead and are not, and both now say so at the top: `build/sparql/diag.rq`
(feeds the extraction-completeness check) and `build/build_function_categories.py`
(the only way to regenerate a config the traversal reads).

## Governed files — the decisions, not the code

| file | what it governs |
|---|---|
| `config/relation_policy.json` | which relations propagate avoidance, and in which direction |
| `config/repair-signoff.json` | human rulings on repaired axioms |
| `config/overrides.json` | regulatory and provenance claims the ontology cannot make; `entry_types` documents `add` / `remove` / `declined` / `superseded` |
| `config/mined-signoff.json` | human rulings on bridges mined from FoodOn's prose |
| `data/resolution-store.json` | pinned free-text resolutions |
| `config/function-categories.json` | readable grouping vocabulary over FoodOn's raw CFR groups |

`audit/01-structural-audit.md` records what FoodOn turned out to be like and why each
rule exists. Read it before changing anything that looks arbitrary.

## Grouping for readability

Section 6 asks for culinary-function rollup. FoodOn carries one — 170 US CFR groups
over 2,342 classes — but it is uneven and mixes two axes: `nutritive sweetener` is an
ingredient role, `doughnut` is a finished food. `config/function-categories.json`
folds all 170 into 17 readable categories on two tiers:

- **ingredient_function** — the six categories of the supplied taxonomy: emulsifiers
  and binders, thickeners and gelling agents, sweeteners, preservatives and
  acidulants, clarifying agents, flavour enhancers.
- **product_type** — bakery, confectionery, dairy, beverages, alcohol, meat and
  seafood, sauces and soups, fruit and vegetable, desserts, prepared foods,
  substitutes, eggs, fats and oils.

The second tier exists because most of the CFR vocabulary is product type, and forcing
those into a functional category would be a category error.

**Why not the supplied derivative lists directly.** Measured: naming the derivatives
outright (soy lecithin, HWP, mono- and diglycerides, gelatin, isinglass…) tags 77 of
39,894 classes and **zero** nodes on gluten, soy, tree nut and nightshade queries —
55% of those terms have no FoodOn class, because the list names precisely the
processed ingredients FoodOn models worst. Mapping the CFR vocabulary instead tags
53 corn, 163 milk, 274 gluten and 274 tree-nut nodes. The taxonomy was right; the
route to it had to change.

## The nine things that decide correctness

**No ascent, structurally.** The traversal adjacency contains only edges pointing in
the avoidance-propagating direction; `subClassOf` is indexed parent→child and the
reverse is never added. There is no code path that ascends, so no configuration
mistake can create one. Corn cannot reach wheat because the upward half of that walk
does not exist in the graph. Two negative tests assert it in both directions.

**Direction is never "both".** `derives from` is asserted product→source, so avoidance
travels object→subject. Allowing both directions permits product→source→sibling
product — ascend-then-redescend through a relation instead of through `is_a`. This was
not hypothetical: `part_of` was drafted as `forward` and made a soy query return
lobster and its 73-node subtree.

**Only `contains` enters the closure.** The closure means one thing — treat this as
containing the query — so the four weaker claim types in `config/overrides.json` are
reported beside the graph rather than drawn in it. Their own definitions say why:
`may_contain` is "feedstock is a producer choice", so corn-derived citric acid is
corn-derived *at some producers* and asserting containment states a fact about the
substance that is not true; `cross_reactive` says outright that "the allergen protein
is NOT present", which as a containment edge is wrong in the direction that needlessly
excludes safe food; `disputed` has "no established containment basis";
`shared_compound` is the intolerance case below. All of them used
to be injected exactly like `contains`, which is what `test/allergen_run.py` was
failing on — 11 terms reached by traversal that only a weaker claim supported. Nothing
is dropped: they surface under *Reported, not traversed* with the claim, the reason and
the reviewer's note, and `test/override_run.py` asserts both halves — a `contains`
override must reach the graph, and a weaker one must not, but must still be reported.

**Intolerance is not allergy, and the graph says which.** A diner who cannot take
citrus is often reacting to **citric acid**, not to the fruit proteins — so the
avoidance is real but the containment is not. Commercial citric acid is *Aspergillus
niger* fermentation on a sugar feedstock; the project already carries a signed
`may_contain` linking it to **corn** for that reason. And its FoodOn closure is ten
*imitation* citrus beverage bases — products formulated with citric acid precisely so
they contain no citrus. A `contains` edge from citrus would therefore put on a
citrus-avoider's list the very products that exist to be citrus-free.

The fifth claim type, `shared_compound`, is for exactly this shape: *the query and the
target share the compound that drives a non-immune intolerance response. Neither
derives from the other, and no allergen protein is involved; the compound is the same
molecule whatever its origin.* Three entries carry it — `citric acid` (E330), the
buffered `citrate salt` forms, and `citric acid esters of mono- and diglycerides`
(E472c), which smuggles the compound into baked goods where a label gives no hint of
citrus.

It is attached to **all 19 citrus query roots**, not just the genus: someone with this
intolerance types `lemon` or `orange` far more often than `citrus`, and a weak claim is
matched on the resolved root rather than inherited down the hierarchy. No traversal
change was needed — anything that is not `contains` is already collected and reported —
so the cost of a new claim type is its definition, its OWL property, a note in the UI
and a line in the ordering. `test/override_run.py` now also asserts that every claim
used is **declared** in `claim_types`, because a typo would fall through the
not-`contains` branch and be reported rather than drawn: safe by luck rather than by
design.

**Excluded branches are config, not code.** `config/relation_policy.json` lists them
and `build/traverse.py` reads that list. It used to hardcode the agency root while the
policy file described the rule as documentation, so the file named a rule the code
never consulted and a second branch could not be added without editing code. Two
branches are excluded now: `agency food product type` (6,074 classes of parallel
regulatory vocabularies — audit F10) and `embryo` (UBERON:0000922, 12 classes).

The embryo one came out of the union fix. FoodOn parents `embryo` under `animal egg`,
which is defensible — an egg does contain one — but morula, blastula, gastrula and the
2/4/8-cell stages are stages of development, not things on a plate. They are also the
only non-food members of the `animal egg` subtree, which mattered because that class
had to become a root: see below. Measured cost of the exclusion across 18 queries: the
12 classes and nothing else.

**`egg` resolves to three roots.** `egg or egg component` (yolk and white),
`chicken egg`, and `animal egg` — none subsumes another. The third was added after the
union fix, which exposed a false negative on a FALCPA top-9 allergen: `animal egg` had
been reachable only through the inverted edge `animal egg is_a shelled egg`, so
correcting the direction dropped `quail egg`, `goose egg`, `ostrich egg`, `turkey egg`,
`turtle egg` and `animal roe` out of an egg query. Egg allergy is to proteins every
bird egg carries, so the species-spanning class belongs in the roots; the embryology
classes underneath it are handled by the exclusion above rather than by narrowing the
root. Egg: 894 before the union fix → 1,148 after → **1,160** with the third root.

**Union operands are children, not parents.** A named class inside a class expression
points one of two ways, and which one depends on the connective:

| axiom | meaning | count |
|---|---|---|
| `X ≡ A ⊓ B` | X ⊑ A, X ⊑ B — operands are **parents** | 5,254 |
| `X ≡ A ⊔ B` | A ⊑ X, B ⊑ X — operands are **children** | 50 |
| `X ⊑ A ⊔ B` | every X is an A or a B, and **nothing** about X ⊑ A | 13 |
| `X ⊑ A ⊓ B` | operands are parents | 8 |

`build/build_index.py` used to descend `owl:unionOf` and `owl:intersectionOf`
identically, so union operands became parents. A mutual `is_a` **is** an equivalence,
and the result was 50 of them — `nut food product`, `plant seed or nut food product`
and `plant seed food product` collapsed into one class, and so did the aquatic-animal
groupings. Two allergen consequences, both severe:

- a **tree nut** query descended into every plant seed and returned 2,176 classes
  including `rice plant`, `soybean plant`, `buckwheat plant` and `quinoa seed`
- **fish** and **shellfish** returned the *same* 4,508 classes — they were one query,
  though FALCPA treats them as separate allergens

Fixed: union operands under an equivalence are emitted as children; under a
`subClassOf` they yield no subsumption at all and are kept on their own weaker
`isa_union` kind, because recall-first still wants `chia seed (whole or pieces)`
reachable from chia even though we cannot say which operand it is. A union reached
inside a *restriction filler* is neither — `blood meal ≡ derives from some (Bos taurus
or swine)` makes neither a parent nor a child, and that stayed on `rel_nest`.

Mutual pairs went 50 → 4, and the four that remain are genuine FoodOn defects rather
than extraction artefacts (`vegetable ↔ vegetable (whole or pieces)` and three like
it), plus one self-loop (`atlantic cod material is_a atlantic cod material`). Only
four queries moved: tree nut 2,176 → **399**, shellfish 4,508 → **1,314**, fish
4,508 → **3,173**, egg 894 → **1,148**. Everything else is byte-identical and
containment recall stays 23/23. Verified that nothing real was lost: `cashew`,
`pistachio`, `brazil nut` and `pine nut` were already unreachable from a tree-nut
query *before* the fix — that is the FoodOn coverage gap the peanut `remove` override
already documents, not a regression. Three invariants in `test/golden.json` pin it.

**Depth budgets are runaway guards, not policy.** Taxonomic descent and derivative
traversal get separate budgets, each counted from where that phase starts. They used
to share one budget of 6 counted from the query root, and that silently truncated real
answers in two ways at once. `pepper` is a shallow grouping over a deep taxonomy, so
`hungarian wax pepper plant` landed at depth 6 with the budget already spent — its
food products were never looked at, and a `pepper` query returned 147 classes and no
paprika while the *narrower* `Capsicum` returned 177 and found it. The same cap also
lost jalapeño, pimiento, guajillo, pasilla, anaheim and 14 more actual peppers, and
cost `tree nut` 671 classes. Every query saturates well inside the current guard of
12 and the whole set runs in 0.01–0.03s, so the cap costs nothing and exists only so
a future cyclic release cannot spin. How deep an organism sits in FoodOn's taxonomy
is an artefact of how finely that branch was subdivided; it is not a statement about
relevance, and truncating on it hands back a shorter answer with nothing on screen to
say it was shortened.

**Plurals are normalised, but only to a form FoodOn knows.** A diner types
`tomatoes`. FoodOn is inconsistent about which form it carries — `potatoes` is a
synonym upstream and resolved, `tomatoes` was not and returned `absent`. Measured over
84 real singular/plural pairs, 25 plurals failed while the singular worked.

The query as typed always wins; a singular is only tried if it resolves to nothing
usable, so `molluscs`, `sulphites`, `nightshades` and `grits` are never rewritten out
from under themselves. And a candidate singular is accepted **only if FoodOn already
knows it** — an exact hit on a pin, a label, a synonym or a preparation-stripped
label. That guard is the whole point: a bare suffix-stripper is worse than doing
nothing, because `peaches → pea` *resolves*, to pea's 106-class closure instead of
peach's 59. Candidates are tried smallest-edit first, which is what sends `peaches` to
`peach` before it could ever reach `pea`, and `octopuses` to `octopus` rather than
`octopu`. **70 of 72 plural forms now resolve**, 22 of them by this route; the two that
did not were `prawns` (four species, genuinely ambiguous) and `knives`. `prawns` has
since been pinned — see *Culinary vocabulary* below — leaving `knives`, which is not
food.

**A facet is not a sense.** FoodOn splits one ingredient across up to four classes —
the plant, the food, the `<X> food product` grouping and the NCBITaxon taxon. Scoring
those against each other treats them as competing answers, and they are not:
`tomato plant` / `tomato` / `tomato food product` / `Solanum lycopersicum` all returned
the **identical** 164-class closure, sat 1.8 points apart against a margin of 8, and
so `tomato` resolved to nothing at all. The resolver was asking "which one?" where the
answer is "those are the same thing". Facets now merge into a multi-root answer, which
is what `gluten` (five grain species) and `egg` (three classes) already do.

Two tests, and the first is not a heuristic:

- **identical closures** — a proof that the choice cannot change the answer
- **parallel hierarchy** — `expand_roots` links them, the same rank-guarded test used
  for the split Solanaceae hierarchies (audit F4)

Only the longest **prefix** of pairwise-compatible candidates merges, which is what
keeps the traps out: `strawberry` merges 2 and leaves `strawberry tree` (*Arbutus
unedo*) behind; `bean` merges 2 and leaves its polysemous variants behind; `prawn`
(four species), `coffee` and `basil` stay ambiguous for sign-off.

`prawn` has since been **pinned**, which took it off that path — so its trap in
`test/resolution_run.py` now runs against a store-free resolver. A guard that passes
because the code it guards was bypassed has quietly stopped guarding, and pinning one
term is not a decision to stop asserting the merge behaviour underneath it.

**Subsumption is deliberately not a third test.** Measured across 30 cuisine terms it
would merge 70 candidate pairs, and almost all differ by taxonomic **rank** rather
than facet — `Ocimum` (16) contains `Ocimum basilicum` (11), `pepper` (176) contains
`bell pepper` (45). Accepting it widens a species query to its genus, which is exactly
what `config/repair-signoff.json` declines by name for `avian animal`; a resolver may
not do quietly what the repair pass refuses to do explicitly. Two rank pins in
`test/resolution_run.py` hold that line.

Over 107 everyday cuisine terms this took resolution from **82 to 101**. Of the
remainder, `wine`, `beer` and `beef` were never a tuning problem: FoodOn has **no base
class** for any of them, only preparation variants like `wine (dealcoholized)` and
`beef (ground)`. They are now pinned:

| query | root | closure |
|---|---|---|
| `wine` | `wine or wine-like food product` | 106 — chosen over `grape wine` (55) because it carries fruit wine too |
| `beer` | `beer beverage` | 17 — ale, IPA, porter, brown beer, barley malt beer |
| `beef` | `bovine meat food product` | 1,555 → **785** after the override below |

**Beef needed an override as well as a pin.** Its root reaches `cow food product`,
which carries `in taxon Bos taurus`; the species pivot then walks back down from the
taxon and returns everything else bovine — `cow milk`, `cheddar cheese` and 675 more
dairy classes. A **beef** query was telling a diner to avoid milk. The meat-cut
classes were considered instead — `piece of beef` (320) and `butchery cut of beef`
(286) are dairy-clean — and rejected because they miss every processed form: jerky,
broth, patties, organs. So the pin stays broad and a signed `remove` override
suppresses `milk` for that root, the same mechanism as peanut/tree-nut. Dairy drops
from 677 classes to 25, and those remaining are legitimate: `dairy cow` is a bovine,
and a cheeseburger does contain beef. Verified in both directions — a `milk` query's
1,098 classes contain no beef, because reaching it would require ascending.

### Culinary vocabulary

Nine further terms are pinned for a different reason: FoodOn has the ingredient, but
not under the name a diner uses for it. They were found by running the deterministic
resolver against a query-time LLM over 40 realistic diner phrasings, with the LLM's
answers written blind to a file before any lookup. Over those 40: **26 tie, 9 to the
LLM, 5 to the resolver**.

| query | pinned to | closure | the gap it closes |
|---|---|---|---|
| `mangetout` | `snow pea plant` | 11 | British/French name, on no FoodOn label |
| `cilantro` | `coriander` + `coriander plant` | 14 | was reaching `Coriandrum sativum` (8), thin but not wrong |
| `creme fraiche` | `cream (cultured)` | 1 | upstream only as an excluded EFSA code-list entry |
| `double cream` | `heavy cream` | 1 | same product, US name |
| `greek yoghurt` | `greek yogurt` | 1 | a spelling gap, nothing more |
| `chilli flakes` | `chili pepper` | 160 | British spelling plus a form FoodOn does not model |
| `smoked paprika` | `paprika (ground)` + `paprika puree` | 2 | agrees with the bare `paprika` pin |
| `san marzano tomatoes` | the three `tomato` facets | 164 | a cultivar FoodOn does not carry |
| `prawns` | `shrimp` | 214 | FoodOn commits to the American name |

**Two of these are deliberately narrow.** `creme fraiche` and `double cream` could
have gone to `cream food product` (61 — clotted cream, whipped cream, coffee creamer,
ranch dressing) and did not. Cream is not the allergen, milk is, and `dairy` and
`milk` both already resolve; a diner who says "double cream" is naming an ingredient,
not declaring a dairy allergy. `prawns` is `shrimp` (214) and not `crustacean` (731)
for the same reason — crab and lobster are a different question, and
`shellfish (crustacean)` answers it. The rejects in `test/resolution_run.py` are what
stop a later helpful widening.

**Why these are pinned and not inferred.** Every one is a fixed fact about vocabulary:
mangetout does not stop meaning snow pea between queries. Deciding it once is strictly
better than paying for it on every request, and it keeps the same dish returning the
same answer. The comparison argued the same thing from the other side — the LLM's two
worst answers were `gluten` (`wheat plant` alone, **missing barley, rye, triticale and
oats**) and `white fish` (all 3,173 fish rather than cod, haddock and plaice), both of
which would have silently overridden a signed multi-root decision, and one of which is
a false negative on a major allergen. It also invented `game meat food product`, which
does not exist. Plurals, which prompted the question, came out a **clean tie** — the
normalisation above had already closed that gap.

The store is generated by `build/build_resolution_store.py`, and as of this change it
genuinely is: `wine`, `beer`, `beef` and the third `egg` root had been edited into the
JSON directly, so regenerating would have dropped them. They are back in the
generator, which now reproduces every pre-existing entry byte-for-byte.

**Absent is an answer.** Roughly two thirds of everyday allergen vocabulary has no
FoodOn class at all. The resolver says so rather than resolving to something
approximate.

## A third kind of gap: missing `in taxon`

A `citrus` query used to return 308 classes and reach neither `lemon plant` nor
`orange plant`. Not a resolution problem and not a missing `derives from` — a missing
**taxon link**.

FoodOn's plant hierarchy has no genus-level citrus class. Seventeen plant classes hang
directly off `citrus family`, which is **Rutaceae** and therefore *above* the genus, so
a citrus query cannot reach them without ascending — and ascending to the family also
collects *Zanthoxylum*: `prickly ash plant`, `japan pepper plant`, `sansho`,
`uzazi fruit`. In the family, not citrus. FoodOn's own definition says so.

The route that does work is the one FoodOn already uses for six of the seventeen:

```
citrus fruit --is a--> grapefruit --in taxon--> Citrus x paradisi --in taxon--> grapefruit plant
```

`grapefruit` and `grapefruit plant` both carry the species link, so the query walks
fruit → species → plant. For `lemon`, FoodOn asserts it on the **fruit** and omits it
on the **plant**. That is the whole bug.

`config/taxon-bridges.json` supplies the omission, one class at a time:

| class | taxon | brings |
|---|---|---|
| `lemon plant` | *Citrus x limon* | 3 |
| `orange plant` | *Citrus sinensis* | 10 — navel, blood, valencia |
| `sour orange plant` | *Citrus x aurantium* | 3 — bergamot, summer orange |
| `clementine plant` | *Citrus x clementina* | 1 |
| `kumquat plant` | *Citrus japonica* | 2 — oval kumquat |

**308 → 324**, and the marmalades, conserves and lemon teas come with them: they
already had `derives from` edges to the fruit and were stranded behind the same gap.

Two things make this a repair rather than an opinion. The axiom is emitted on
**`RO:0002162`, the ontology's own property** — not a local one — so a SPARQL consumer
reaches `lemon plant` by the identical path it already walks to `grapefruit plant`, and
the materialiser needed no new branch. And the binomial is checkable: `test/run.py`
asserts the eleven classes arrive and the four *Zanthoxylum* stay out, `test/patch_run.py`
asserts the same thing again **through SPARQL**, 5/5 bridges honoured and 4/4 excluded.

Ten more are queued in `requires_signoff` rather than applied. Four are synonymy calls
(`myrtle-leaf orange` → *C. x aurantium*; `palestine sweet lime` → *C. limetta*); five
are hybrids FoodOn has no taxon for at all (`orangelo`, `oroblanco`, `persian lime`,
the Citrofortunella group); one — `citrus honey` — is not a taxon question, since the
honey carries no fruit.

### Two parity holes this exposed, one of them closed

Adding a seventh root to `test/patch_run.py` broke a parity claim that six roots had
never tested. Both pre-existing.

**Unpinned correspondences — fixed.** The emitter wrote `local:sameOrganismAs` only
for roots in `data/resolution-store.json`, so the export was parity-correct for pinned
queries and quietly wrong for every other one. `citrus fruit` is not pinned, so its
pairing with `citrus fruit food product` — worth 50 classes — was never written, and a
SPARQL consumer under-reported that root while the app did not.

It now emits the whole relation: **19 correspondences → 803**. The five-minute
estimate for that scan was wrong, and wrong in an instructive way — `expand_roots`
rebuilt its 39,894-entry label index on *every call*, so measuring it by calling it
2,000 times measured the rebuild, not the work. Hoisting the index makes the full scan
**0.04s**, and made each query's `expand_roots` 60× faster as a side effect (7.75ms →
0.12ms).

The rule now lives in one place, `Graph.all_correspondences()`, which both the emitter
and the test call — the application's rule and the exported rule cannot drift apart,
which is the failure this whole layer exists to prevent. `patch_run.py` asserts parity
on `citrus fruit` **because it is unpinned**: that root is the regression test.

The taxon-pivot half is deliberately not emitted. `local:pivotsTo` already carries it
and `patch_closure.rq` already walks it, so emitting it again would be 2,587 triples
saying what the graph says.

**Nested-filler subsumption — fixed.** FoodOn states some parents and some ingredient
links only *inside* a class expression: a named class sitting in a restriction filler,
or an operand of `X ⊑ (A ⊔ B)`. No `rdfs:subClassOf` triple exists for those and **no
reasoner will infer one** — `X ⊑ A ⊔ B` says every X is an A or a B and refuses to say
which. The application extracts them anyway on its weaker edge kinds (`rel_nest`,
`isa_union`) because recall-first wants them; SPARQL walking `rdfs:subClassOf` saw none
of it.

563 of them are now exported: 149 weak subsumptions on a new `local:weaklyUnder`, and
414 nested propagating relations folded into the `local:propagatesTo` the materialiser
already writes. Taken **from `data/index.json`, not re-derived in SPARQL** — the
extraction rule is 60 lines of tree-walking with a direction rule that has been wrong
before, and a second implementation of it would be a second thing to keep correct.

Each weak subsumption is emitted **twice**, which is exactly how an ordinary subclass
edge is consumed: `patch_closure.rq` descends `^rdfs:subClassOf` in phase one and
`local:propagatesTo` in phase two, so a weak parent must be walkable in both. With only
the phase-one form, `citrus fruit` reached `imitation orange juice drink` and `Citrus`
did not — from `Citrus` the same class sits one `derives from` further along.

### How far parity actually holds

`test/patch_run.py` asserts **eight** roots at exact parity, each chosen for a
mechanism: the species pivot, a union filler, a supplied `in taxon` link, an *unpinned*
root, a class defined inside a class expression. Twice now, adding a ninth revealed a
hole the eight could not see — so `build/audit/parity_sweep.py` sweeps every pinned
root instead. It is a diagnostic, not a test.

**29 of 38 roots at exact parity.** The nine that do not are unrelated to the two holes
above — verified: none of their diverging classes touches a nested edge — and fall into
three groups:

| | roots | direction |
|---|---|---|
| `remove` overrides suppress a subtree; the SPARQL filter only walks `propagatesTo*` ancestors, not `rdfs:subClassOf` descendants | `nut producing plant` | over-reports |
| terminal namespaces (CHEBI stops expansion in the app; the query knows nothing of them) | `sulfites`, `coriander plant` | over-reports |
| multi-root allergens whose co-roots and override edges the query does not compose | `egg or egg component`, `chicken egg`, `animal egg`, `mammal`, `bovine meat food product`, `mollusc` | under-reports |

The third group is the one that matters for safety and is the largest: `egg or egg
component` returns 1,147 classes in the app and 162 in SPARQL.

## Bridges awaiting review

FoodOn omits `derives from` on 62% of its `<X> food product` classes.
`build/repair_derives.py` recovers 76 of them from the naming convention plus two
structural guards — that is the edge that connects paprika to nightshade.
`build/classify_mined.py` covers what the convention cannot see, and puts every
candidate in a **review queue rather than the graph**:

| rule | source of evidence | in queue |
|---|---|---|
| E | FoodOn's own definitions (`pasta` is "an unleavened dough of wheat flour") | 11 |
| B | interior qualifier: `<X> <qualifier> food product` → `<X> <source>` | 1 |
| D | preparation-state twin, emitted as the missing `is a` it actually is | 13 |

**Signed so far: 10.**

| bridge | effect |
|---|---|
| `pasta → wheat plant`, `whole wheat pasta → wheat plant` | gluten 829 → 863 |
| `malt syrup → barley plant` | gluten → 864, barley 48. A classic hidden gluten source |
| `mustard condiment food product → mustard plant` | mustard 37 → 47: dijon, mustard sauce, relish, mostarda di frutta |
| `yellow mustard (prepared) → white mustard plant` | adds the species-level route, so a `white mustard` / *Sinapis alba* query reaches it too |
| `soy-based protein powder → soybean plant` | soy 133 → 134 |
| `acorn flour → oak tree` | reachable from oak and, correctly, from a tree-nut query — an acorn is a nut |
| `croziflette → buckwheat plant` | **medium** confidence, deliberately — see below |
| `tahini → sesame plant`, `white tahini → sesame plant` | sesame stays at 19, but on **structure instead of curation** — `Sesame → tahini` is now reported redundant in `override_run.py` |

`croziflette` is the only entry signed at **medium**. Its definition reads "crozets
de Savoie (usually made from buckwheat **but sometimes durum**)" — a recipe choice,
the same shape as the `may_contain` overrides that are kept out of the closure.
Signed anyway under recall-first, because buckwheat allergy is anaphylactic and
crozets usually *are* buckwheat, so the over-inclusion falls in the safe direction.
Two gaps it does not close, recorded in the sign-off so nobody reads the dish as
mapped: it is a multi-component dish that also contains milk (reblochon), pork
(bacon) and allium (onion), none of which FoodOn asserts; and the durum variant means
it may contain gluten, which will not show on a gluten query since buckwheat is
gluten-free.

The malt entry is the one that needed an argument. Its definition hedges — "a syrup
made from malted barley **or grains**" — but FoodOn keeps the generic reading in a
separate class (`malted cereal syrup`, under flavoring syrup), keeps `rice syrup`
separate again under plant sweetener, and already parents `malt extract` under
`barley product flavoring`. That last one is the ontology's own statement that
unqualified malt means barley. Verified after signing: neither `malted cereal syrup`
nor `rice syrup` is pulled into a gluten query.

That last row is the direction of travel: a signed override replaced by an axiom
FoodOn's own prose already contained. The `Sesame → tahini` override has since been
**retired** — `type: "superseded"`, not deleted, because the record of why the gap
existed is the useful part. `test/override_run.py` keeps that retirement honest: a
superseded entry's target must still be reached, and not by an override, or the test
fails and names the entry to reinstate. Verified by removing the mined bridge, which
produced exactly that failure. Retiring an override without this check would be an
untested deletion of a safety claim.

`test/mined_run.py` reports `white tahini` as redundant — it is `is a tahini`, so it
arrives by descent; it is kept as a direct anchor against a future re-parenting, the
same treatment as the sodium caseinate override.

The broader `pasta food product` was deliberately **not** signed — see below.

Nothing here changes an answer. `config/mined-signoff.json` is keyed by **product
IRI** — not by source label as `config/repair-signoff.json` is — because a mined
bridge rests on one class's own prose sentence and is evidence for exactly that
class. `test/mined_run.py` asserts the queue is inert and that a signed entry
actually fires.

**Five guards, each earned from a real false positive.** 295 of 330 candidates are
rejected: 182 already reachable, 103 external code-list rows, and then the ones that
matter — `pear tomato plant → pear plant` (the product is itself an organism; a pear
tomato is a tomato), `food milling → grain plant` (a process has no origin),
`enzyme supplement → pineapple plant` (the definition reads "plants like pineapple
and papaya" — an example list, not an origin), and `chocolate (imitation) → chocolate`
(an analog is defined by *not* containing what it imitates, which is why
`has food substance analog` is non-propagating in the relation policy).

**Every candidate carries its impact, because one of them needs it.** Dry-running
`pasta food product → wheat plant` grew a gluten query from 829 to 964 classes and
pulled in `gluten-free pasta` — `pasta food product` is a shape, not a grain. The
queue reports `+119` against that entry and names the conflict, so it reads as a
decline-or-narrow decision rather than a free win. `pasta → wheat plant` (+6) and
`whole wheat pasta` (+1) are the clean parts of the same finding.

**Not implemented, on purpose.** Product-form suffixes (`<X> oil`, `<X> sauce`,
`<X> syrup`) were measured at ~50% precision: `pancake syrup → pancake`,
`malt syrup → malt root` (it is barley), `feather meal → feather`. `<X> sauce` and
`<X> syrup` name the dish, not the source, and no guard separates the two cases.
Definition mining gets `malt syrup → barley plant` right from the prose instead, and
`test/mined_run.py` fails if rule C ever appears in the queue.

## Coverage

Against the supplied allergen derivative list (103 terms across 12 allergens), scored
by relation type because the list conflates four relations that need different
machinery:

| relation | result |
|---|---|
| containment | **23/23 reached** of those FoodOn has a class for |
| synonym | 4/4 resolve into the right closure |
| provenance / cross-reactive / disputed | 0 reached by structure — no false containment; 20 carried as reported claims |

## Known limits

- **48 of 71 containment terms do not exist in FoodOn at all.** `soy lecithin`,
  `whey protein concentrate`, `ovalbumin`, `bovine gelatin`, `isinglass`, `seitan`,
  `triticale`, `kamut`. No traversal work changes that; it is the single largest
  limit on the system and it is a data-availability problem.
- FoodOn parents processed ingredients by function (`tahini is_a condiment`,
  `casein is_a protein extract`) and asserts no source. Five such derivatives are
  reachable only through signed overrides, not through structure.
- 11 `may_contain` entries are signed but **reported rather than traversed**: the
  source is genuinely open (corn, wheat, cassava, beet or molasses by producer and
  region), so a corn query lists citric acid, xanthan gum, ascorbic acid and calcium
  citrate under *Reported, not traversed* instead of drawing them as containment.
  Revisit if a product-level layer can supply the actual source.
- 7 override targets, including `sorbitol` and `modified food starch`, name terms with
  no FoodOn class, so there is nothing to point an edge at; they surface as text in
  the same panel.
- Two FoodOn defects are recorded in `data/misparented.json`: `rye kernel` is parented
  under `sumac food product`, and `hickory nut` (with `pecan` beneath it) under
  `mustard spinach food product`. Both are allergen false negatives.
- Certified gluten-free oats cannot be expressed here. Oats count as gluten-containing
  by decision; the exception is a product-label fact and must be handled downstream.

/* FoodOn Avoidance Graph — React shell, D3 radial tidy-tree layout.
 *
 * Display strategy. Closures run from 189 nodes (corn) to 3,494 (fish). Layout is a
 * radial tidy tree over the shortest-route spanning tree, not a force simulation:
 * 83-89% of a closure has in-degree 1, so the data is a tree with a few extra edges,
 * and a tidy tree gives no node overlap and no tree-edge crossings by construction.
 * The extra edges are drawn as overlay curves. Rather than truncate — which would
 * work against the recall-first policy — the graph is progressively disclosed:
 * roots and their immediate children start visible, deeper subtrees collapse behind
 * a +N badge, and wide sibling sets group into culinary-function clusters drawn from
 * the US CFR groupings FoodOn already carries. The underlying data is never filtered;
 * everything hidden is one click away, and the counts are always on screen.
 */
const { useState, useEffect, useRef, useMemo, useCallback } = React;
const html = htm.bind(React.createElement);

const REL_STYLE = {
  "is a":                    { color: "var(--isa)",        dash: "4 3" },
  "derives from":            { color: "var(--derives)",    dash: null  },
  "in taxon":                { color: "var(--taxon)",      dash: null  },
  "has ingredient":          { color: "var(--ingredient)", dash: null  },
  "has defining ingredient": { color: "var(--ingredient)", dash: null  },
  "part_of":                 { color: "var(--part)",       dash: "1 3" },
  "has_part":                { color: "var(--part)",       dash: "1 3" },
};
const relStyle = (e) => {
  if (e.provenance === "override") return { color: "var(--override)", dash: "7 4" };
  if (e.provenance === "repair")   return { color: "var(--repair)",   dash: "7 4" };
  if (e.provenance === "mined")    return { color: "var(--mined)",    dash: "6 3" };
  // a supplied `in taxon` link: the taxon hue, because that is what the edge MEANS,
  // with the patched dash, because it is not FoodOn's own assertion
  if (e.provenance === "taxon")    return { color: "var(--taxon)",    dash: "7 4" };
  return REL_STYLE[e.relation_label] || { color: "var(--isa)", dash: "2 3" };
};
const EXAMPLES = ["corn", "nightshade", "allium", "gluten", "tree nut", "soy", "paprika", "edamame"];

/* ---------- node role: what KIND of thing, for the fill channel ----------
 * One signal per visual channel. Fill hue answers "what kind of thing is this",
 * and nothing else: reachability lives on the stroke rings, relation and
 * provenance live on the edges, rank lives in radius and type size.
 *
 * The four roles are the distinctions a nutritionist actually reads. `organism`
 * vs `derivative` is "the plant you are avoiding" vs "a thing made from it" —
 * the only one the previous fill encoded. `category` is FoodOn's grouping
 * scaffolding (`field corn sweetener product`), which is not an ingredient at
 * all and should not look like one; the label-suffix test is the same rule the
 * sibling project used to find those 1,217 classes, and it finds 24 of the 480
 * in the nightshade closure.
 *
 * Deliberately NOT encoded here: `confidence` is uniformly "high" across every
 * node of the saved closures and `function_category` is unset on all of them, so
 * spending a channel on either buys nothing today.
 */
/* `product` only. A trailing `food` was tried and is wrong: it matches
   `potato prepared food` and `corn-based snack food`, which are dishes, not
   FoodOn scaffolding. */
const CATEGORY_SUFFIX = /\b(product|products)$/;
function nodeRole(d) {
  if (d.kind === "cluster") return "cluster";
  if (d.is_root) return "root";
  if (CATEGORY_SUFFIX.test((d.label || "").toLowerCase())) return "category";
  if (d.phase === "taxonomic") return "organism";
  return "derivative";
}
const ROLE_FILL = {
  root: "var(--root)", organism: "var(--n-organism)", derivative: "var(--n-derivative)",
};
/* Label priority, lowest number survives longest. Roots, clusters and collapsed
 * parents are never dropped — a `+n` badge with no name is a dead end. Categories
 * come next because they are what makes the drawing skimmable, then organisms,
 * then convergent nodes, then ordinary leaves. */
function labelTier(d) {
  if (d.is_root || d.kind === "cluster" || d.hidden) return 0;
  const r = nodeRole(d);
  if (r === "category") return 1;
  if (r === "organism") return 2;
  if (d.multi_path || d.convergent) return 3;
  return 4;
}
/* A backstop only. Which labels appear is decided geometrically at layout time
 * against the real node positions — see the label-placement pass in GraphView. With
 * every leaf on the rim, most of them genuinely fit, so this is set well above what
 * a normal query needs and exists to bound the pathological case. It replaced a hard
 * `display:none` cliff at 60 nodes, which left the 480-node nightshade closure drawn
 * as a grey cloud with no text, and then a tier budget, which could not tell whether
 * two labels actually collided. */
const LABEL_CAP = 200;
/* type ladder: [px, weight] per role, on the same rank order as the radius ladder */
const TYPE = { root: [14, 640], organism: [12, 580], category: [11.5, 550],
               cluster: [11.5, 550], derivative: [11, 450] };
const TYPE_SIZE = Object.fromEntries(Object.entries(TYPE).map(([k, v]) => [k, v[0]]));
const trimLabel = (s, n) => (s || "").length > n ? (s || "").slice(0, n - 1) + "…" : (s || "");

/* ---------- display graph: what is actually drawn right now ---------- */
function buildDisplay(graph, expanded, showLow, revealed) {
  const byIri = new Map(graph.nodes.map((n) => [n.iri, n]));
  const kids = new Map();
  const parentOf = new Map();
  for (const e of graph.edges) {
    if (!byIri.has(e.source) || !byIri.has(e.target)) continue;
    if (!kids.has(e.source)) kids.set(e.source, []);
    kids.get(e.source).push(e);
    if (!parentOf.has(e.target)) parentOf.set(e.target, e.source);
  }
  const roots = graph.nodes.filter((n) => n.is_root).map((n) => n.iri);
  const conf = (n) => (showLow ? true : n.confidence !== "low");

  // A search hit is usually collapsed behind a cluster or an unexpanded parent, so
  // revealing it means forcing its whole ancestor chain visible. Computed up front so
  // the clustering step below can emit these nodes directly instead of hiding them.
  const forced = new Set();
  for (const id of revealed || []) {
    let cur = id, guard = 0;
    while (cur && !forced.has(cur) && guard++ < 40) {
      forced.add(cur);
      cur = parentOf.get(cur);
    }
  }

  // Opened breadth-first up to a budget chosen for legibility, not for data volume.
  // Phase-based rules were tried first and were worse: they left a corn query showing
  // 10 of 194 nodes while a wide taxonomic layer elsewhere blew past any sensible size.
  const AUTO_OPEN_BUDGET = 150;
  // A small closure should just be shown. Collapsing 15 nodes hides the answer
  // behind a click for no benefit; the budget exists for the 3,494-node cases.
  const SMALL_GRAPH = 70;
  const showAll = graph.nodes.length <= SMALL_GRAPH;
  const visible = new Set(roots);
  const clusters = [];
  const queue = [...roots];
  const hiddenUnder = new Map();

  while (queue.length) {
    const id = queue.shift();
    const out = (kids.get(id) || []).filter((e) => conf(byIri.get(e.target)));
    if (!out.length) continue;
    // Class-level queries must show their members up front (spec 5), so the whole
    // taxonomic phase opens by default; derivative subtrees stay collapsed.
    const self_ = byIri.get(id);
    // Opening only the taxonomic layer left a corn query showing 10 of 194 nodes.
    // The first derivative level is what the user actually came for, so it opens too,
    // still under the budget that keeps a 3,494-node closure manageable.
    const isOpen = showAll || expanded.has(id) || self_.is_root || forced.has(id) ||
      visible.size < AUTO_OPEN_BUDGET;
    if (!isOpen) { hiddenUnder.set(id, out.length); continue; }

    // wide sibling sets group by culinary function before they are drawn
    if (out.length > 14 && !out.some((e) => forced.has(e.target))) {
      /* A wide sibling set is grouped by CULINARY FUNCTION where FoodOn supplies
       * one (spec 6) -- `Bakery & Grain Products`, `Thickeners, Stabilizers &
       * Gelling Agents`. That path works and is kept, but it only ever applies to a
       * minority: only 2,342 of 39,894 classes carry a `member of` CFR rollup at
       * all, so across 16 allergen queries 93 of 136 clusters had no category.
       *
       * Those used to be labelled `via is a` / `via derives from`, which claimed a
       * grouping rationale the data does not support: every child in a taxonomy is
       * reached by `is a`, so the label only repeated what the edge already drew.
       * Measured before removing it -- a shared label stem that adds anything beyond
       * the parent's own name exists for 8% of these clusters; 27% have a stem that
       * merely echoes the parent (`potato` under `potato (whole or pieces)`, `pepper
       * plant` under `hot pepper plant`) and 64% have none at all. Role homogeneity
       * was no better: 62% pure, but the labels it yields read as `18 derivatives`.
       *
       * So an uncategorised cluster now states only what is certainly true: how
       * many. The relation stays on the edge colour, where it was already drawn, and
       * in the tooltip.
       *
       * Grouping is still BY RELATION even when unlabelled. Merging them would force
       * one incoming edge colour onto a mixed group and misreport how the members
       * were reached.
       */
      const groups = new Map();
      for (const e of out) {
        const n = byIri.get(e.target);
        // `rollup_groups?.[0]?.label` used to sit between these two as a fallback and
        // was dead code: function_category is DERIVED from rollup_groups, and
        // config/function-categories.json maps all 170 CFR groups FoodOn uses, so of
        // 863 nodes carrying a rollup, zero lacked a category.
        const cat = n.function_category?.label || null;
        const key = cat || ` via:${e.relation_label}`;
        if (!groups.has(key))
          groups.set(key, { cat, via: cat ? null : e.relation_label, members: [] });
        groups.get(key).members.push(e);
      }
      for (const [key, grp] of groups) {
        const members = grp.members;
        const cid = `cluster:${id}:${key}`;
        if (expanded.has(cid) || members.length <= 2 ||
            members.some((m) => forced.has(m.target))) {
          for (const e of members) {
            if (visible.has(e.target)) continue;
            visible.add(e.target); queue.push(e.target);
          }
        } else {
          clusters.push({ id: cid, parent: id, label: grp.cat, via: grp.via,
                          count: members.length,
                          members: members.map((m) => m.target) });
        }
      }
      continue;
    }
    for (const e of out) {
      if (visible.has(e.target)) continue;
      visible.add(e.target); queue.push(e.target);
    }
  }

  for (const id of forced) if (byIri.has(id)) visible.add(id);
  const nodes = graph.nodes.filter((n) => visible.has(n.iri)).map((n) => ({
    ...n, hidden: hiddenUnder.get(n.iri) || 0, kind: "node",
    revealed: (revealed || new Set()).has(n.iri),
  }));
  for (const c of clusters) {
    const pd = graph.nodes.find((n) => n.iri === c.parent)?.depth ?? 1;
    // `label` is the DISPLAY string and must always be one: the lineage
    // breadcrumb, the tooltip and the JSON drawer all read it, and a null here
    // made the breadcrumb fall through to the synthetic cluster IRI
    // ("cluster:http://purl.obolibrary.org/obo/..."). The category, which may
    // legitimately be absent, gets its own field.
    nodes.push({ iri: c.id, label: c.label || `${c.count} more`,
                 category: c.label, via: c.via, kind: "cluster",
                 count: c.count, depth: pd + 1, members: c.members,
                 is_root: false, convergent: false, multi_path: false });
  }
  const nodeIds = new Set(nodes.map((n) => n.iri));
  const links = graph.edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({ ...e }));
  for (const c of clusters) links.push({ source: c.parent, target: c.id, relation_label: "is a",
                                         provenance: "cluster", confidence: "high" });
  return { nodes, links, total: graph.nodes.length, shown: nodes.length };
}

/* ---------- the D3 canvas ---------- */
function GraphView({ graph, expanded, onToggle, onSelect, selected, showLow, revealed, focus,
                     matches, alwaysLabels }) {
  const ref = useRef(null);
  const tipRef = useRef(null);
  const [dims, setDims] = useState(null);   // pane size; a real change re-lays out
  const zoomRef = useRef(null);
  const nodesRef = useRef([]);
  const stickyRef = useRef(null);      // node whose chain stays painted after mouseleave
  const paintPathRef = useRef(null);   // lets the breadcrumb repaint without a redraw
  const [lineage, setLineage] = useState(null);
  const lineageRef = useRef(null);
  const display = useMemo(() => buildDisplay(graph, expanded, showLow, revealed),
                          [graph, expanded, showLow, revealed]);

  useEffect(() => {
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    const rect = ref.current.getBoundingClientRect();
    const width = Math.max(640, rect.width), height = Math.max(420, rect.height);
    const g = svg.append("g");

    const zoom = d3.zoom().scaleExtent([0.15, 4])
      .on("zoom", (ev) => g.attr("transform", ev.transform));
    svg.call(zoom);
    zoomRef.current = { svg, zoom, width, height };

    // userSpaceOnUse so the head stays 9px regardless of stroke width, and refX 0 so
    // it lands exactly where the line ends. Node radii now run 6.5–15, so a fixed
    // refX would bury the arrow inside the larger nodes; the tick shortens each line
    // to its own target's edge instead.
    svg.append("defs").append("marker")
      .attr("id", "arrow").attr("viewBox", "0 -5 10 10").attr("refX", 0)
      .attr("markerWidth", 10).attr("markerHeight", 10)
      .attr("markerUnits", "userSpaceOnUse").attr("orient", "auto")
      .append("path").attr("d", "M0,-4L9,0L0,4").attr("fill", "#b9b4ab");

    const nodes = display.nodes.map((d) => ({ ...d }));
    nodesRef.current = nodes;
    const links = display.links.map((d) => ({ ...d }));
    const byIriNode = new Map(nodes.map((n) => [n.iri, n]));

    // radius tracks role rank, on the same ladder as the type sizes below, so
    // size and weight reinforce each other instead of being flat and unreadable
    const radius = (d) => {
      if (d.kind === "cluster") return 9 + Math.min(13, Math.sqrt(d.count) * 2.6);
      const r = nodeRole(d);
      if (r === "root") return 15;
      if (d.iri === selected) return 12;
      if (r === "organism") return 10;
      if (r === "category") return 9;
      return d.multi_path ? 8 : 6.5;
    };

    /* ---- spanning tree ----------------------------------------------------
     * Measured: 83% of the nightshade closure and 89% of corn have in-degree 1.
     * The result is a tree with a few extra edges, and a force simulation is the
     * wrong instrument for that. forceRadial pinned each node to a depth ring but
     * nothing ordered them WITHIN the ring, so siblings from different parents
     * interleaved and their edges crossed back and forth. A tidy tree places every
     * node deterministically: no node overlap and no crossings among tree edges,
     * guaranteed by the layout rather than negotiated by forces. Nothing settles,
     * so the drawing is also identical across reloads.
     *
     * The tree is the breadth-first shortest-route parent for each node, the same
     * chain the breadcrumb reports. The remaining ~15% of edges are drawn as
     * overlay curves, so a multi-parent term still shows all of its parents.
     */
    const outAdj = new Map();
    for (const l of links) {
      if (!outAdj.has(l.source)) outAdj.set(l.source, []);
      outAdj.get(l.source).push(l);
    }
    const parentEdge = new Map();
    {
      const q = nodes.filter((n) => n.is_root).map((n) => n.iri);
      const seen = new Set(q);
      while (q.length) {
        const cur = q.shift();
        for (const l of outAdj.get(cur) || []) {
          if (seen.has(l.target)) continue;
          seen.add(l.target); parentEdge.set(l.target, l); q.push(l.target);
        }
      }
    }
    const childrenOf = new Map();
    for (const [child, e] of parentEdge) {
      if (!childrenOf.has(e.source)) childrenOf.set(e.source, []);
      childrenOf.get(e.source).push(child);
    }
    const realRoots = nodes.filter((n) => n.is_root).map((n) => n.iri);
    // one root sits at the centre; several share a synthetic hub that is never
    // drawn, which puts them on the first ring exactly as they were before
    const SYNTH = "__hub__";
    const single = realRoots.length === 1;
    const rootId = single ? realRoots[0] : SYNTH;
    if (!single) childrenOf.set(SYNTH, realRoots.slice());

    // Anything the walk cannot reach is attached to the root rather than dropped.
    // A node that is in the result but silently not drawn is the one failure mode
    // this tool must not have.
    {
      const attached = new Set([rootId]);
      const stack = [rootId];
      while (stack.length) {
        const cur = stack.pop();
        for (const c of childrenOf.get(cur) || [])
          if (!attached.has(c)) { attached.add(c); stack.push(c); }
      }
      const orphans = nodes.map((n) => n.iri).filter((i) => !attached.has(i));
      if (orphans.length)
        childrenOf.set(rootId, [...(childrenOf.get(rootId) || []), ...orphans]);
    }

    const toTree = (iri) => ({ iri, children: (childrenOf.get(iri) || []).map(toTree) });
    const root = d3.hierarchy(toTree(rootId));

    const leafCount = Math.max(1, root.leaves().length);
    // The outer circumference has to give every leaf a legible slice of arc. 15px
    // per leaf is the label line-height; below that the outer ring starts to
    // overprint itself, so the drawing grows and the view pans instead of cramming.
    /* Exact now, not an approximation: every leaf sits at outerR, so the outer
     * circumference must give each one 15px of arc (one line of text). Plus a floor
     * of 62px per ring, so the rings stay far enough apart for an internal node's
     * label to run outward without immediately meeting the next one.
     *
     * The pane size is deliberately NOT part of this. It used to be, and it made a
     * 2-node paprika query fill the whole canvas: two nodes 660px apart with their
     * labels turned vertical. Size the drawing to its content and let the fit
     * transform scale it — up as well as down. */
    const needed = (leafCount * 15) / (2 * Math.PI);
    const outerR = Math.max(120, needed, 62 * root.height);
    /* d3.cluster, not d3.tree: a dendrogram, which puts every LEAF on the outer ring.
     * The leaves are the answer to the query — the things you must not serve — and on
     * the rim they all sit at the maximum radius, where the circumference is greatest
     * and every one of them gets the same generous slice of arc. Under d3.tree a leaf
     * sat at its own depth, so a shallow leaf landed on a small ring holding almost no
     * arc, which is where the crowding was worst.
     *
     * The cost, stated plainly: radius no longer means hops-from-the-root. In a
     * dendrogram an internal node's radius is its distance to the deepest leaf
     * beneath it, so a grouping class with a shallow subtree sits further out than one
     * with a deep subtree. Hop count moves to the tooltip and the breadcrumb, which
     * report it exactly rather than by eye.
     *
     * nodeSize, not size([2*PI, R]). `size` normalises to exactly one turn, which
     * divides the circle between the ROOT's subtrees evenly no matter how big they
     * are: nightshade has a 130-term Solanaceae and a 17-term `solanaceae plant`, and
     * each was taking half the canvas. With a fixed angular step per leaf, every leaf
     * gets the same arc and each subtree gets a wedge proportional to its contents. */
    const ringStep = outerR / Math.max(1, root.height);
    d3.cluster()
      .nodeSize([(2 * Math.PI) / leafCount, ringStep])
      .separation((a, b) => (a.parent === b.parent ? 1 : 1.8))
      (root);
    // nodeSize leaves the angular extent unbounded (separation adds gaps between
    // non-siblings), so rescale onto the circle. Linear, so the proportional
    // allocation survives; the seam is left one leaf-step wide.
    {
      const xs = root.descendants().map((d) => d.x);
      const x0 = Math.min(...xs), span = (Math.max(...xs) - x0) || 1;
      const turn = 2 * Math.PI * (leafCount > 1 ? 1 - 1 / leafCount : 1);
      root.each((d) => { d.x = ((d.x - x0) / span) * turn; });
    }

    const cx = width / 2, cy = height / 2;
    root.each((h) => {
      const n = byIriNode.get(h.data.iri);
      if (!n) return;
      n.angle = h.x; n.rad = h.y;
      n.px = Math.cos(h.x - Math.PI / 2) * h.y;
      n.py = Math.sin(h.x - Math.PI / 2) * h.y;
      // absolute coordinates inside the zoom group, for fly-to
      n.x = cx + n.px; n.y = cy + n.py;
    });
    /* ---- label placement, by geometry rather than by budget ----
     * A fixed label budget cannot know whether two labels actually collide, and
     * two things make collisions unavoidable in a radial tree: at a shallow radius
     * a wedge holds very little arc, and single-child chains collapse onto ONE ray
     * (d3.tree centres a parent over its children — corn puts 89 nodes on 72
     * distinct angles). So labels are placed greedily against the real positions:
     * candidates are considered in tier order, and one is admitted only if it
     * clears every label already placed.
     *
     * Two labels clear each other if they are far enough apart along the arc, OR
     * far enough apart along the radius that the inner one's text ends before the
     * outer one begins. Tier order is what makes this behave well: when a ray is
     * contested, the more useful name wins it and the leaf is dropped, instead of
     * both being staggered into a two-line smudge.
     */
    const TAU2 = 2 * Math.PI;
    for (const d of nodes) {
      const base = trimLabel(d.label, labelTier(d) <= 2 ? 42 : 30);
      // a category keeps its name and count; an uncategorised cluster states only
      // the count, which is the one fact about it that is certainly true
      d.labelText = d.kind === "cluster"
                    ? (d.category ? base + " \u00b7 " + d.count : base)
                  : d.hidden ? base + "  +" + d.hidden : base;
    }
    const LINE = 12;            // perpendicular room one line of text needs
    const textLen = (d) => {
      const fs = (TYPE_SIZE[nodeRole(d)] || TYPE_SIZE.derivative);
      return d.labelText.length * fs * 0.53 + 12;
    };
    /* The centre node is the one label that is NOT laid along a ray — it sits
     * horizontally above the node — so the arc test cannot see it. Model it as a box
     * and reject any radial label whose text would run through it. */
    const rootBox = (() => {
      const r0 = nodes.find((d) => d.rad === 0);
      if (!r0) return null;
      const w = textLen(r0) / 2 + 4, top = -(radius(r0) + 9);
      return { x0: -w, x1: w, y0: top - LINE, y1: top + 5 };
    })();
    const hitsRootBox = (d) => {
      if (!rootBox || d.rad === 0) return false;
      const ux = Math.cos(d.angle - Math.PI / 2), uy = Math.sin(d.angle - Math.PI / 2);
      const s0 = d.rad + radius(d) + 6, s1 = s0 + textLen(d);
      for (let k = 0; k <= 6; k++) {
        const t = s0 + ((s1 - s0) * k) / 6, x = ux * t, y = uy * t;
        if (x >= rootBox.x0 && x <= rootBox.x1 && y >= rootBox.y0 && y <= rootBox.y1)
          return true;
      }
      return false;
    };
    const keepLabel = new Set();
    {
      const placedL = [];
      const cands = nodes.filter((d) => d.rad != null).sort((a, b) =>
        labelTier(a) - labelTier(b) || (a.depth || 0) - (b.depth || 0) ||
        (b.in_degree || 0) - (a.in_degree || 0) ||
        a.labelText.length - b.labelText.length);
      for (const d of cands) {
        if (alwaysLabels) { keepLabel.add(d.iri); continue; }
        if (keepLabel.size >= LABEL_CAP) break;
        const clears = placedL.every((p) => {
          let da = Math.abs(p.angle - d.angle);
          da = Math.min(da, TAU2 - da);
          const inner = p.rad <= d.rad ? p : d;
          if (da * Math.min(p.rad, d.rad) >= LINE) return true;
          return Math.abs(p.rad - d.rad) >= textLen(inner);
        });
        // tier 0 is never dropped: a +n badge or a root with no name is a dead end
        if ((clears && !hitsRootBox(d)) || labelTier(d) === 0) {
          keepLabel.add(d.iri); placedL.push(d);
        }
      }
    }
    const labelShown = (d) => keepLabel.has(d.iri);

    // laid out around the origin, then moved to the pane centre once
    const gRoot = g.append("g").attr("transform", "translate(" + cx + "," + cy + ")");

    const treeKeys = new Set();
    for (const [child, e] of parentEdge) treeKeys.add(e.source + ">" + child);
    const ekey = (l) => l.source + ">" + l.target;
    const placed = (l) => byIriNode.get(l.source)?.rad != null &&
                          byIriNode.get(l.target)?.rad != null;
    const treeLinks  = links.filter((l) => treeKeys.has(ekey(l)) && placed(l));
    const extraLinks = links.filter((l) => !treeKeys.has(ekey(l)) && placed(l));

    const lw = (d) => d.provenance === "cluster" ? 1
      : ["override", "repair", "mined"].includes(d.provenance) ? 2.2 : 1.4;
    const ld = (d) => d.provenance === "cluster" ? "2 4" : relStyle(d).dash;
    const lc = (d) => d.provenance === "cluster" ? "#ded9d1" : relStyle(d).color;

    // Tree edges follow the radius, so they never cross one another. The target
    // radius is pulled in by the node's own size to leave room for the arrow head.
    const linkGen = d3.linkRadial().angle((d) => d.angle).radius((d) => d.rad);
    const treePath = (l) => {
      const s = byIriNode.get(l.source), t = byIriNode.get(l.target);
      const back = radius(t) + (l.provenance === "cluster" ? 3 : 10);
      return linkGen({ source: { angle: s.angle, rad: s.rad },
                       target: { angle: t.angle, rad: Math.max(s.rad, t.rad - back) } });
    };
    // Non-tree edges are the only lines that can cross, and they are the
    // interesting ones: a second parent. Bowed toward the centre so they stay out
    // of the label ring at the rim.
    const extraPath = (l) => {
      const s = byIriNode.get(l.source), t = byIriNode.get(l.target);
      return "M" + s.px + "," + s.py +
             "Q" + (s.px + t.px) * 0.28 + "," + (s.py + t.py) * 0.28 +
             " " + t.px + "," + t.py;
    };

    const gLinks = gRoot.append("g").attr("fill", "none");
    const linkTree = gLinks.selectAll("path.tl").data(treeLinks).join("path")
      .attr("class", "glink").attr("d", treePath)
      .attr("stroke", lc).attr("stroke-width", lw).attr("stroke-dasharray", ld)
      .attr("stroke-opacity", 0.85)
      .attr("marker-end", (d) => d.provenance === "cluster" ? null : "url(#arrow)");
    const linkExtra = gLinks.selectAll("path.xl").data(extraLinks).join("path")
      .attr("class", "glink").attr("d", extraPath)
      .attr("stroke", lc).attr("stroke-width", lw)
      .attr("stroke-dasharray", (d) => relStyle(d).dash || "5 3")
      .attr("stroke-opacity", 0.5);
    const link = gRoot.selectAll("path.glink");

    // Groups are positioned radially rather than translated, so each node's local
    // +x axis points away from the centre and its label can be laid along it.
    const node = gRoot.append("g").selectAll("g")
      .data(nodes.filter((d) => d.rad != null)).join("g")
      .attr("cursor", "pointer")
      .attr("transform", (d) => d.rad === 0 ? "translate(0,0)"
        : "rotate(" + (d.angle * 180 / Math.PI - 90) + ") translate(" + d.rad + ",0)");

    node.filter((d) => d.kind === "cluster").append("rect")
      .attr("x", (d) => -radius(d)).attr("y", -11)
      .attr("width", (d) => radius(d) * 2).attr("height", 22).attr("rx", 11)
      .attr("fill", "#f4efe6").attr("stroke", "#d8cfbe").attr("stroke-width", 1.4);

    // A grouping class is an unfilled dashed ring, not a dot: `field corn sweetener
    // product` is FoodOn scaffolding, not something you can be served, and it should
    // not read as an ingredient. The ground-coloured stroke keeps a node legible
    // where an overlay edge passes behind it.
    node.filter((d) => d.kind !== "cluster").append("circle")
      .attr("r", radius)
      .attr("fill", (d) => nodeRole(d) === "category" ? "none"
                        : ROLE_FILL[nodeRole(d)] || "var(--n-derivative)")
      .attr("stroke", (d) => nodeRole(d) === "category" ? "var(--n-category)"
                          : d.multi_path ? "var(--convergent)" : "var(--bg)")
      .attr("stroke-width", (d) => nodeRole(d) === "category" ? 2
                                : d.multi_path ? 2.4 : 2)
      .attr("stroke-dasharray", (d) => nodeRole(d) === "category" ? "3.2 2.6" : null);

    // a second ring marks convergence across different query roots
    node.filter((d) => d.convergent && !d.is_root).append("circle")
      .attr("r", (d) => radius(d) + 3.5).attr("fill", "none")
      .attr("stroke", "var(--convergent)").attr("stroke-width", 1)
      .attr("stroke-dasharray", "2 2").attr("opacity", 0.8);

    // Type size and weight ride the same role ladder as the radius. Labels on the
    // left half are flipped and end-anchored so no text is ever upside down.
    const TAU = 2 * Math.PI;
    const flipped = (d) => d.rad !== 0 && (((d.angle % TAU) + TAU) % TAU) >= Math.PI;
    /* With only a handful of leaves the radial form buys nothing and costs legibility
     * — two leaves land at 0 and PI, so both labels stand on end. Counter-rotate them
     * back to horizontal instead. */
    const tiny = leafCount <= 4;
    const upright = (d) => -(d.angle * 180 / Math.PI - 90);
    node.append("text")
      .text((d) => d.labelText)
      .attr("transform", (d) => d.rad === 0 ? null
                             : tiny ? "rotate(" + upright(d) + ")"
                             : flipped(d) ? "rotate(180)" : null)
      .attr("x", (d) => d.rad === 0 || tiny ? 0
                      : flipped(d) ? -(radius(d) + 6) : radius(d) + 6)
      .attr("y", (d) => d.rad === 0 || tiny ? -(radius(d) + 9) : 4)
      .attr("text-anchor", (d) => d.rad === 0 || tiny ? "middle"
                               : flipped(d) ? "end" : "start")
      .attr("font-size", (d) => (TYPE[nodeRole(d)] || TYPE.derivative)[0])
      .attr("font-weight", (d) => (TYPE[nodeRole(d)] || TYPE.derivative)[1])
      .attr("fill", (d) => d.is_root ? "var(--root)"
                        : nodeRole(d) === "category" ? "var(--n-category)"
                        : "var(--label-ink)")
      // the ground-coloured outline is what lets a label sit on top of an edge and
      // still be read; without it dense areas turn into noise
      .attr("paint-order", "stroke").attr("stroke", "var(--bg)")
      .attr("stroke-width", 3.5).attr("stroke-linejoin", "round")
      .style("display", (d) => labelShown(d) ? null : "none");

    /* ---- ancestry path ----
     * The node's ancestor chain in the laid-out tree, which is the same shortest
     * route the breadth-first walk above produced. */
    const chainOf = (iri) => {
      const out = []; let cur = iri, guard = 0;
      while (guard++ < 60) {
        const e = parentEdge.get(cur);
        if (!e) break;
        out.push(e); cur = e.source;
      }
      return out;   // nearest hop first
    };

    /* Dim everything off the path. Dimming is opacity ONLY, never a recolour, so
     * the relation and provenance an edge encodes survive exactly when the user is
     * inspecting it. On the path an `is a` edge goes solid and thickens, because at
     * rest it is a faint dash and adjacent categories read as unconnected; its
     * colour is left alone. */
    function paintPath(iri) {
      if (!iri || !byIriNode.has(iri)) {
        node.attr("opacity", 1);
        node.selectAll("text").style("display", (d) => labelShown(d) ? null : "none");
        linkTree.attr("stroke-opacity", 0.85).attr("stroke-width", lw)
                .attr("stroke-dasharray", ld);
        linkExtra.attr("stroke-opacity", 0.5).attr("stroke-width", lw)
                 .attr("stroke-dasharray", (d) => relStyle(d).dash || "5 3");
        setLineage(null);
        return;
      }
      const chain = chainOf(iri);
      const onNodes = new Set([iri, ...chain.map((e) => e.source)]);
      const onEdges = new Set(chain.map(ekey));
      node.attr("opacity", (d) => onNodes.has(d.iri) ? 1 : 0.28);
      // the path's own labels come back regardless of the density budget
      node.selectAll("text").style("display", (d) =>
        onNodes.has(d.iri) || labelShown(d) ? null : "none");
      link.attr("stroke-opacity", (d) => onEdges.has(ekey(d)) ? 1 : 0.09)
          .attr("stroke-width", (d) => !onEdges.has(ekey(d)) ? lw(d)
            : (d.provenance === "override" || d.provenance === "repair") ? 3 : 2.4)
          .attr("stroke-dasharray", (d) => onEdges.has(ekey(d)) ? null : ld(d));
      // root-first, so it reads left to right as the graph reads outward
      setLineage({
        here: iri,
        hops: chain.slice().reverse().map((e) => ({
          from: e.source, fromLabel: byIriNode.get(e.source)?.label || e.source,
          relation: e.relation_label, provenance: e.provenance,
          isRoot: !!byIriNode.get(e.source)?.is_root,
          isCategory: byIriNode.get(e.source) &&
                      nodeRole(byIriNode.get(e.source)) === "category",
        })),
        hereLabel: byIriNode.get(iri)?.label || iri,
      });
    }
    paintPathRef.current = paintPath;

    const tip = d3.select(tipRef.current);
    node.on("mouseenter", (ev, d) => {
        tip.style("opacity", 1)
           .html(d.kind === "cluster"
             ? "<b>" + d.label + "</b><br>" +
               d.count + " items — click to expand" +
               (d.via ? "<br>reached by <i>" + d.via + "</i>" : "")
             : "<b>" + d.label + "</b><br>" + (d.curie || "") +
               // radius is distance-to-deepest-leaf under a dendrogram, not depth, so
               // the hop count has to be stated rather than read off the drawing
               (d.is_root ? "<br>query root"
                          : "<br>" + d.depth + (d.depth === 1 ? " hop" : " hops") +
                            " from the root") +
               (d.hidden ? "<br>" + d.hidden + " more below — click to expand" : "") +
               (d.multi_path ? "<br>reached by " + d.in_degree + " paths" : ""));
        paintPath(d.iri);
      })
      .on("mousemove", (ev) => {
        const r = ref.current.getBoundingClientRect();
        tip.style("left", (ev.clientX - r.left + 14) + "px")
           .style("top", (ev.clientY - r.top + 12) + "px");
      })
      // with nothing hovered the clicked node's chain stays up, so it can be read
      // without holding the pointer still
      .on("mouseleave", () => { tip.style("opacity", 0); paintPath(stickyRef.current); })
      .on("click", (ev, d) => {
        ev.stopPropagation();
        stickyRef.current = d.iri;
        paintPath(d.iri);
        if (d.kind === "cluster") onToggle(d.iri);
        else { onSelect(d.iri); if (d.hidden) onToggle(d.iri); }
      });
    svg.on("click", () => {
      stickyRef.current = null; paintPath(null); onSelect(null);
    });

    /* The path that stays up after the pointer leaves is the SELECTION, not a
     * separate piece of state. stickyRef is only a same-tick mirror of it, so a
     * click paints before React has re-rendered; deriving it from `selected` is what
     * makes a new query clear the path, since run() resets `selected` and a ref
     * would have survived. */
    stickyRef.current = selected && byIriNode.has(selected) ? selected : null;
    if (stickyRef.current) paintPath(stickyRef.current);

    node.filter((d) => d.iri === selected).select("circle")
      .attr("stroke", "var(--accent)").attr("stroke-width", 3);

    // search hits: a halo, plus their label forced on regardless of the label budget
    const hit = new Set(matches || []);
    node.filter((d) => hit.has(d.iri)).each(function () {
      const g2 = d3.select(this);
      g2.insert("circle", ":first-child")
        .attr("r", 15).attr("fill", "var(--accent)").attr("opacity", 0.16);
      g2.select("text").style("display", null).attr("font-weight", 650);
    });

    /* ---- fit to view ----
     * The drawing is sized by its leaf count, not by the pane: gluten needs an 843px
     * tall box where the pane is 832. So it is scaled to fit once, measured from the
     * rendered bounding box so the labels are included rather than clipped.
     *
     * Measured on a rAF, not inline. Inline, getBBox returned a 613px height for a
     * box that settled at 843 — text metrics are not final in the same frame the
     * nodes are appended, and the fit was then 1.27x instead of 0.93x and clipped
     * both sides. The fit also uses the REAL pane size, not the 640x420 floors the
     * layout uses, or it maps the drawing into a viewport that does not exist.
     *
     * `Reset view` returns here rather than to the identity transform.
     */
    const raf = requestAnimationFrame(() => {
      if (!ref.current) return;
      const pad = 26;
      const bb = gRoot.node().getBBox();
      const pw = ref.current.getBoundingClientRect().width || width;
      const ph = ref.current.getBoundingClientRect().height || height;
      const k = Math.max(0.15, Math.min(1.4, (pw - 2 * pad) / Math.max(1, bb.width),
                                             (ph - 2 * pad) / Math.max(1, bb.height)));
      const bcx = cx + bb.x + bb.width / 2, bcy = cy + bb.y + bb.height / 2;
      const t = d3.zoomIdentity.translate(pw / 2, ph / 2).scale(k).translate(-bcx, -bcy);
      svg.call(zoom.transform, t);
      zoomRef.current.home = t;
    });

    // The layout is a pure function of the pane size, so a resize re-runs it rather
    // than nudging a running simulation. Only a real change counts, or the
    // observer's own first callback would loop.
    const ro = new ResizeObserver(() => {
      const r2 = ref.current?.getBoundingClientRect();
      if (!r2 || !r2.width) return;
      if (Math.abs(r2.width - rect.width) < 24 &&
          Math.abs(r2.height - rect.height) < 24) return;
      setDims([Math.round(r2.width), Math.round(r2.height)]);
    });
    ro.observe(ref.current);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [display, selected, onToggle, onSelect, alwaysLabels, dims]);

  useEffect(() => {
    if (!focus || !zoomRef.current) return;
    let tries = 0;
    const id = setInterval(() => {
      const d = nodesRef.current.find((n) => n.iri === focus);
      const z = zoomRef.current;
      if ((d && d.x != null) || ++tries > 40) {
        clearInterval(id);
        if (!d || d.x == null) return;
        const k = 1.35;
        z.svg.transition().duration(500).call(z.zoom.transform,
          d3.zoomIdentity.translate(z.width / 2, z.height / 2).scale(k)
            .translate(-d.x, -d.y));
      }
    }, 120);
    return () => clearInterval(id);
  }, [focus, display]);

  // A long chain overflows the bar. Scroll to the right-hand end, which holds the
  // node the user actually clicked — the root end is the predictable half.
  useEffect(() => {
    const el = lineageRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [lineage]);

  const fit = useCallback(() => {
    const z = zoomRef.current; if (!z) return;
    z.svg.transition().duration(400)
     .call(z.zoom.transform, z.home || d3.zoomIdentity);
  }, []);

  return html`
    <div class="graphwrap">
      <svg ref=${ref}></svg>
      <div class="tooltip" ref=${tipRef}></div>
      <div class="controls">
        <button onClick=${fit}>Reset view</button>
        <span class="pill">${display.shown} of ${display.total} nodes drawn</span>
        ${display.nodes.some((n) => n.revealed) ? html`
          <span class="pill" style=${{ borderColor: "var(--accent)", color: "var(--accent)" }}>
            ${display.nodes.filter((n) => n.revealed).length} revealed by search</span>` : null}
      </div>
      ${lineage ? html`
        <div class="lineage" ref=${lineageRef}>
          ${lineage.hops.map((h, i) => html`
            <${React.Fragment} key=${h.from + i}>
              <button class=${"lchip" + (h.isRoot ? " root" : "") +
                              (h.isCategory ? " category" : "")}
                title=${h.fromLabel}
                onClick=${() => { stickyRef.current = h.from; onSelect(h.from);
                                  paintPathRef.current?.(h.from); }}>${h.fromLabel}</button>
              <span class=${"lrel " + (h.provenance || "")}
                title=${h.provenance === "repair"
                  ? "repaired axiom — FoodOn omitted this; build/repair_derives.py supplied it"
                  : h.provenance === "override"
                  ? "signed override — a claim the ontology cannot make"
                  : h.provenance === "mined"
                  ? "mined from FoodOn's own definition and signed off in config/mined-signoff.json"
                  : "asserted in FoodOn"}>${h.relation}${
                  ["repair", "override", "mined"].includes(h.provenance)
                    ? ` (${h.provenance})` : ""}</span>
            </${React.Fragment}>`)}
          <span class="lchip here" title=${lineage.hereLabel}>${lineage.hereLabel}</span>
          ${lineage.hops.length === 0 ? html`
            <span class="lhint">query root — nothing above it</span>` : html`
            <span class="lhint">${lineage.hops.length} hop${
              lineage.hops.length === 1 ? "" : "s"} from the root</span>`}
        </div>` : null}
    </div>`;
}

/* ---------- in-graph search ---------- */
function GraphSearch({ graph, onReveal, onClose, open, onOpen }) {
  const [q, setQ] = useState("");
  const inputRef = useRef(null);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);

  // Matches label and synonyms, because plenty of FoodOn classes are only findable
  // by synonym -- `spelt` and `semolina` are synonyms of their classes, not labels.
  const results = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (t.length < 2) return [];
    const scored = [];
    for (const n of graph.nodes) {
      const lab = (n.label || "").toLowerCase();
      let score = null, via = "label";
      if (lab === t) score = 0;
      else if (lab.startsWith(t)) score = 1;
      else if (lab.includes(t)) score = 2;
      else {
        const syn = (n.synonyms || []).find((x) => x.toLowerCase().includes(t));
        if (syn) { score = 3; via = `synonym: ${syn}`; }
      }
      if (score !== null) scored.push({ n, score, via });
    }
    scored.sort((a, b) => a.score - b.score || a.n.label.length - b.n.label.length);
    return scored.slice(0, 40);
  }, [q, graph]);

  if (!open) return html`
    <button class="iconbtn" title="Search within this graph" onClick=${onOpen}>
      ${magnifier()} <span>Find</span>
    </button>`;

  return html`
    <div class="searchbox">
      <div class="searchrow">
        ${magnifier()}
        <input ref=${inputRef} type="text" value=${q} placeholder="find in this graph…"
          onChange=${(e) => setQ(e.target.value)}
          onKeyDown=${(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "Enter" && results.length) onReveal(results[0].n.iri);
          }} />
        <button onClick=${onClose} title="Close">✕</button>
      </div>
      ${q.trim().length >= 2 ? html`
        <div class="searchmeta">
          ${results.length ? `${results.length}${results.length === 40 ? "+" : ""} in this graph`
                           : "no match in this graph"}
        </div>` : html`
        <div class="searchmeta">searches all ${graph.nodes.length.toLocaleString()} classes,
          including ones currently collapsed</div>`}
      <div class="searchresults">
        ${results.map(({ n, via }) => html`
          <button class="sresult" key=${n.iri} onClick=${() => onReveal(n.iri)}>
            <span class="slabel">${n.label}</span>
            <span class="smeta">
              ${n.is_root ? "root" : `depth ${n.depth}`}
              ${n.multi_path ? " · multi-path" : ""}
              ${via !== "label" ? ` · ${via}` : ""}
            </span>
          </button>`)}
      </div>
    </div>`;
}

function magnifier() {
  return html`<svg class="mag" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
    <circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.7" />
    <line x1="10.4" y1="10.4" x2="14" y2="14" stroke="currentColor"
      stroke-width="1.9" stroke-linecap="round" />
  </svg>`;
}

/* ---------- JSON drawer, grouped by the legend ---------- */

// The same categories the legend uses, so what you read in the drawer maps onto what
// you see in the graph. Order matches the legend exactly.
const EDGE_GROUPS = [
  { key: "derives from",      test: (e) => e.provenance === "ontology" && e.relation_label === "derives from" },
  { key: "in taxon",          test: (e) => e.provenance === "ontology" && e.relation_label === "in taxon" },
  { key: "has ingredient",    test: (e) => e.provenance === "ontology" &&
      (e.relation_label === "has ingredient" || e.relation_label === "has defining ingredient") },
  { key: "is a",              test: (e) => e.provenance === "ontology" && e.relation_label === "is a" },
  { key: "part of / has part",test: (e) => e.provenance === "ontology" &&
      (e.relation_label === "part_of" || e.relation_label === "has_part") },
  { key: "repaired axiom",    test: (e) => e.provenance === "repair" },
  { key: "override",          test: (e) => e.provenance === "override" },
  { key: "other relations",   test: () => true },
];
const NODE_GROUPS = [
  { key: "query root",              test: (n) => n.is_root },
  { key: "taxonomic member",        test: (n) => n.phase === "taxonomic" },
  { key: "reached by several paths",test: (n) => n.multi_path || n.convergent },
  { key: "has a function group",    test: (n) => n.function_category || n.rollup_groups?.length },
  { key: "other derivatives",       test: () => true },
];

// Rendering the whole document is capped by characters, not by dropping records:
// a fish query is ~2.4MB and no <pre> reads well at that size. The copy buttons
// always emit the complete JSON regardless of what is on screen.
const RENDER_CAP = 400000;

const curie = (iri) => {
  const t = String(iri).split("/").pop();
  return t.includes("_") ? t.replace("_", ":") : t;
};

function legendOf(item, groups) {
  const g = groups.find((x) => x.test(item));
  return g ? g.key : "other";
}

// One document. Every node and edge carries its legend identifier as its first key,
// and records are ordered by legend category, so the categories read as contiguous
// blocks without the graph being split into separate JSONs.
function annotatedGraph(graph, compact) {
  const labelOf = new Map(graph.nodes.map((n) => [n.iri, n.label]));
  const order = (groups) => Object.fromEntries(groups.map((g, i) => [g.key, i]));
  const nOrder = order(NODE_GROUPS), eOrder = order(EDGE_GROUPS);

  // Compact keeps every record and every relationship; it drops the repeated full
  // IRIs (the curie identifies the same class) and the prose metadata. Nothing is
  // filtered out, so the document still describes the whole graph.
  const nodes = graph.nodes
    .map((n) => compact
      ? { legend: legendOf(n, NODE_GROUPS), id: n.curie, label: n.label,
          depth: n.depth, confidence: n.confidence,
          ...(n.is_root ? { root: true } : {}),
          ...(n.multi_path ? { in_degree: n.in_degree,
                               via: n.incoming_relations } : {}),
          ...(n.convergent ? { convergent_from: n.roots } : {}),
          ...(n.function_category ? { function: n.function_category.label } : {}),
          ...(n.rollup_groups?.length
              ? { cfr_groups: n.rollup_groups.map((g) => g.label) } : {}) }
      : { legend: legendOf(n, NODE_GROUPS), ...n })
    .sort((a, b) => (nOrder[a.legend] - nOrder[b.legend]) ||
                    a.label.localeCompare(b.label));
  const edges = graph.edges
    .map((e) => compact
      // labels alongside the curies: an edge you have to cross-reference against the
      // nodes array to understand is not readable, which is the point of this view
      ? { legend: legendOf(e, EDGE_GROUPS),
          from: labelOf.get(e.source) || curie(e.source),
          to: labelOf.get(e.target) || curie(e.target),
          from_id: curie(e.source), to_id: curie(e.target),
          confidence: e.confidence }
      : { legend: legendOf(e, EDGE_GROUPS), ...e })
    .sort((a, b) => (eOrder[a.legend] - eOrder[b.legend]) ||
                    String(a.from ?? a.source).localeCompare(String(b.from ?? b.source)) ||
                    String(a.to ?? a.target).localeCompare(String(b.to ?? b.target)));

  const tally = (arr) => arr.reduce((acc, x) => {
    acc[x.legend] = (acc[x.legend] || 0) + 1; return acc;
  }, {});

  return {
    query: graph.query,
    ontology_version: graph.ontology_version,
    relation_policy_version: graph.relation_policy_version,
    roots: graph.roots,
    root_expansion: graph.root_expansion,
    counts: graph.counts,
    suppressed: graph.suppressed,
    legend: {
      note: "every node and edge below carries a `legend` key naming its category in the graph legend; records are ordered by that category" +
            (compact ? ". Compact view: classes are identified by curie and the relation is carried by the legend key. Switch to full for IRIs, definitions and synonyms." : ""),
      nodes: tally(nodes),
      edges: tally(edges),
    },
    nodes,
    edges,
  };
}

function JsonDrawer({ graph, open, onToggle, selectedNode }) {
  const [compact, setCompact] = useState(true);
  const doc = useMemo(() => (graph && open) ? annotatedGraph(graph, compact) : null,
                      [graph, open, compact]);
  const full = useMemo(() => doc ? JSON.stringify(doc, null, 2) : "", [doc]);
  const truncated = full.length > RENDER_CAP;
  const shown = truncated ? full.slice(0, RENDER_CAP) : full;
  if (!graph) return null;

  const copy = (text) => navigator.clipboard?.writeText(text);
  const line = (color, dash) => html`<span class="swatch"
    style=${{ borderTopColor: color, borderTopStyle: dash ? "dashed" : "solid" }}></span>`;
  const dot = (bg, extra) => html`<span class="dot" style=${{ background: bg, ...extra }}></span>`;
  const EDGE_SW = { "derives from": ["var(--derives)", 0], "in taxon": ["var(--taxon)", 0],
    "has ingredient": ["var(--ingredient)", 0], "is a": ["var(--isa)", 1],
    "part of / has part": ["var(--part)", 1], "repaired axiom": ["var(--repair)", 1],
    "override": ["var(--override)", 1], "other relations": ["var(--isa)", 1] };
  const NODE_SW = {
    "query root": ["var(--root)", null],
    "taxonomic member": ["#8aa2bd", null],
    "reached by several paths": ["#d9d3c9", { boxShadow: "0 0 0 2px var(--convergent)" }],
    "has a function group": ["#f4efe6", { border: "1.4px solid #d8cfbe", borderRadius: "3px" }],
    "other derivatives": ["#d9d3c9", null] };

  return html`
    <${React.Fragment}>
      <button class=${"drawertab" + (open ? " open" : "")} onClick=${onToggle}
        title=${open ? "Hide JSON" : "Show the JSON behind this graph"}>
        <span>${open ? "\u203A" : "\u2039"}</span> JSON
      </button>
      <div class=${"drawer" + (open ? " open" : "")}>
        <div class="drawerhead">
          <b>${graph.query}</b>
          <span class="hint">${graph.counts.nodes.toLocaleString()} nodes ·
            ${graph.counts.edges.toLocaleString()} edges · FoodOn ${graph.ontology_version}</span>
          <div class="drawerbtns">
            <button class=${"jcopy" + (compact ? " on" : "")}
              onClick=${() => setCompact((v) => !v)}>
              ${compact ? "compact" : "full"}</button>
            <button class="jcopy" onClick=${() => copy(full)}>copy the whole graph</button>
            ${selectedNode ? html`
              <button class="jcopy" onClick=${() => copy(JSON.stringify(
                { legend: legendOf(selectedNode, NODE_GROUPS), ...selectedNode,
                  edges_in: graph.edges.filter((e) => e.target === selectedNode.iri)
                    .map((e) => ({ legend: legendOf(e, EDGE_GROUPS), ...e })) }, null, 2))}>
                copy ${selectedNode.label}</button>` : null}
          </div>
        </div>
        ${doc ? html`
          <div class="drawerkey">
            ${Object.entries(doc.legend.nodes).map(([k, v]) => {
              const sw = NODE_SW[k] || ["#d9d3c9", null];
              return html`<span class="keyrow" key=${k}>${dot(sw[0], sw[1])}${k}
                <b>${v}</b></span>`; })}
            ${Object.entries(doc.legend.edges).map(([k, v]) => {
              const sw = EDGE_SW[k] || ["var(--isa)", 1];
              return html`<span class="keyrow" key=${k}>${line(sw[0], sw[1])}${k}
                <b>${v}</b></span>`; })}
          </div>` : null}
        <div class="drawerbody">
          ${truncated ? html`
            <p class="hint trunc">Showing the first ${Math.round(RENDER_CAP / 1000)}k characters
              of ${Math.round(full.length / 1000)}k — a graph this size does not read well in
              one block. <b>Copy emits the whole document.</b></p>` : null}
          <pre class="jsonfull">${shown}</pre>
        </div>
      </div>
    </${React.Fragment}>`;
}

/* ---------- side panel ---------- */
function Resolution({ data }) {
  const r = data.resolution;
  const g = data.graph;
  if (r.status !== "resolved")
    return html`
      <div class="res">
        <div class="q">${r.query}</div>
        <div class="pill low">${r.status}</div>
        <p class="note">${r.status === "absent"
          ? "FoodOn has no class matching this term. That is a real answer, not an error — roughly two thirds of everyday allergen vocabulary is absent from the ontology, and resolving it to something approximate would be worse than saying so."
          : r.note || ""}</p>
        ${r.candidates?.length ? html`
          <div class="note"><b>Closest candidates</b>
            <ul>${r.candidates.map((c) => html`<li key=${c.iri}>${c.label} · closure ${c.closure}</li>`)}</ul>
          </div>` : null}
      </div>`;
  return html`
    <div class="res">
      <div class="q">${r.query}</div>
      <div>
        <span class="pill ${r.confidence}">${r.confidence} confidence</span>${" "}
        <span class="pill">${r.method}</span>
      </div>
      <div class="roots">
        ${r.roots.map((iri, i) => html`
          <div class="root" key=${iri}>
            <span>${r.root_labels[i]}</span>
            <${IriField} iri=${iri} curie=${iri.split("/").pop().replace("_", ":")}
              compact=${true} />
          </div>`)}
      </div>
      ${r.roots.length > 1 ? html`<p class="note">Resolved to ${r.roots.length} roots.
        Nodes reached from more than one are ringed in the graph.</p>` : null}
      ${g && Object.keys(g.root_expansion || {}).length ? html`
        <p class="note"><b>Root expansion:</b> ${Object.entries(g.root_expansion)
          .map(([k, v]) => `${k} (${v})`).join(", ")}. FoodOn splits some organisms across
          parallel hierarchies; these denote the same organism and are merged.</p>` : null}
      ${r.rationale ? html`<p class="note">${r.rationale}</p>` : null}
      ${r.note ? html`<div class="warn">${r.note}</div>` : null}
      ${g?.suppressed ? html`<div class="warn">${g.suppressed} classes suppressed by a
        reviewed <code>remove</code> override.</div>` : null}
    </div>`;
}

function Detail({ node, graph, onClear }) {
  if (!node) return html`<p class="hint">Click a node for its FoodOn record, the relations
    that reach it, and its provenance. Click a cluster to expand it.</p>`;
  const incoming = graph.edges.filter((e) => e.target === node.iri);
  const byNode = new Map(graph.nodes.map((n) => [n.iri, n]));
  return html`
    <div class="detail">
      <button onClick=${onClear} style=${{ float: "right", padding: "2px 8px", fontSize: 11 }}>close</button>
      <dl>
        <dt>Label</dt><dd><b>${node.label}</b></dd>
        <dt>FoodOn IRI</dt>
        <dd><${IriField} iri=${node.iri} curie=${node.curie} /></dd>
        <dt>Reached at</dt>
        <dd>depth ${node.depth} · ${node.phase} phase ·
          <span class="pill ${node.confidence}">${node.confidence}</span></dd>
        ${node.convergent ? html`<${React.Fragment}>
          <dt>Convergence</dt>
          <dd>reached from ${node.roots.length} query roots: ${node.roots.join(", ")}</dd>
        </${React.Fragment}>` : null}
        ${node.in_degree > 1 ? html`<${React.Fragment}>
          <dt>Multiple paths</dt>
          <dd>${node.in_degree} incoming edges via ${node.incoming_relations.join(", ")}</dd>
        </${React.Fragment}>` : null}
        ${incoming.length ? html`<${React.Fragment}>
          <dt>How it is reached</dt>
          <dd><ul>${incoming.map((e) => html`
            <li key=${e.source + e.relation}>
              <span style=${{ color: relStyle(e).color }}>●</span>${" "}
              ${byNode.get(e.source)?.label || "?"} — <i>${e.relation_label}</i>
              ${e.provenance !== "ontology" ? html` · <b>${e.provenance}</b>` : null}
            </li>`)}</ul></dd>
        </${React.Fragment}>` : null}
        ${node.function_category ? html`<${React.Fragment}>
          <dt>Culinary function</dt>
          <dd>${node.function_category.label}
            <span class="pill">${node.function_category.kind.replace("_", " ")}</span></dd>
        </${React.Fragment}>` : null}
        ${node.rollup_groups?.length ? html`<${React.Fragment}>
          <dt>FoodOn regulatory groups</dt>
          <dd>${node.rollup_groups.map((g) => g.label).join(", ")}</dd>
        </${React.Fragment}>` : null}
        ${node.synonyms?.length ? html`<${React.Fragment}>
          <dt>Synonyms</dt><dd>${node.synonyms.slice(0, 6).join(", ")}</dd>
        </${React.Fragment}>` : null}
        ${node.definition ? html`<${React.Fragment}>
          <dt>Definition</dt><dd>${node.definition}</dd>
        </${React.Fragment}>` : null}
      </dl>
    </div>`;
}

/* The IRI is the thing a curator needs to leave the app with — it opens the class in
 * the OBO PURL resolver, which is the canonical record — so it is a real link, and a
 * copy button sits beside it because an IRI is more often pasted into a script or a
 * spreadsheet than followed. Opens in a new tab: losing the current query to a
 * navigation would throw away the traversal the user is reading. */
function IriField({ iri, curie, compact }) {
  const [copied, setCopied] = useState(false);
  if (!iri) return null;
  const copy = async (ev) => {
    ev.preventDefault(); ev.stopPropagation();
    try { await navigator.clipboard.writeText(iri); }
    catch (e) {
      // clipboard can be unavailable or refused; fall back to a selection the
      // user can copy by hand rather than failing silently
      const ta = document.createElement("textarea");
      ta.value = iri; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e2) { /* nothing else to try */ }
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  /* ONE companion tab, reused -- and no JavaScript needed to get it.
   *
   * `target="_blank"` was wrong twice over. It spawns a fresh tab per click, so
   * reading six terms leaves six tabs, which is the opposite of being able to switch
   * back and forth. And an embedded webview ignored it outright and navigated the
   * CURRENT tab to ontobee.org, losing the query and everything expanded in the
   * graph. A NAMED target fixes both: the browser reuses the window with that name,
   * and it is honoured where `_blank` was not (verified -- a named-target click
   * leaves the app loaded, while `_blank` replaced it).
   *
   * An interception via window.open() was tried first and is worse: this webview
   * blocks page-initiated popups entirely, so window.open returned null and the
   * click became a silent no-op. A user-initiated link click with a target is not a
   * popup and is never blocked, so the declarative form is both simpler and more
   * robust. It also keeps cmd/ctrl/shift-click, middle-click and "copy link
   * address" working for free.
   *
   * Deliberately NO rel="noopener": noopener and name reuse are mutually exclusive,
   * because noopener creates a context the opener cannot find again by name. Reuse
   * is the requested behaviour, the destination is the OBO Foundry PURL resolver,
   * and this is a localhost tool -- so the opener reference is accepted. Revisit if
   * the app is ever served publicly.
   */
  return html`
    <span class=${"irirow" + (compact ? " compact" : "")}>
      <a class="iri" href=${iri} target="foodon-term"
         title=${"Open " + iri + " at purl.obolibrary.org — reuses one companion tab"}
         onClick=${(ev) => ev.stopPropagation()}>
        <code>${curie || iri}</code><span class="ext" aria-hidden="true">↗</span>
      </a>
      <button class="copyiri" onClick=${copy}
        title=${copied ? "IRI copied" : "Copy " + iri}>
        ${copied ? "copied" : "copy"}
      </button>
    </span>`;
}

/* Signed claims that are deliberately not edges. Two reasons, and the reader needs
 * to be told which: either FoodOn has no class to point at, or a class exists but the
 * claim is weaker than containment and the closure means containment only. Grouped
 * by claim so `may_contain` — the one that changes what you do next — leads, and
 * `cross_reactive` — which says the protein is NOT present — cannot be misread as a
 * reason to avoid something. */
const CLAIM_NOTE = {
  may_contain: "May be derived from it. The feedstock is a producer choice, so this " +
               "is a label to check or a supplier to ask — not a term to treat as " +
               "containing the allergen.",
  shared_compound: "The same compound, reached another way \u2014 not derived from " +
                   "it. Relevant to an INTOLERANCE, where the response is to the " +
                   "molecule and its origin does not matter. It is not in the dish " +
                   "because the query is, so it stays out of the graph.",
  disputed: "Appears on avoidance lists with no established containment basis.",
  cross_reactive: "Immunologically related, but the allergen protein is NOT present. " +
                  "Relevant to a clinical history, not to what is in the dish.",
};
function Annotations({ items }) {
  if (!items?.length) return null;
  const groups = [];
  for (const a of items) {
    const g = groups.find((x) => x.claim === a.claim);
    (g || groups[groups.push({ claim: a.claim, rows: [] }) - 1]).rows.push(a);
  }
  return html`
    <section>
      <h2>Reported, not traversed</h2>
      <p class="hint" style=${{ marginTop: -4, marginBottom: 8 }}>
        Signed claims held outside the graph on purpose. The graph asserts containment;
        these do not, so drawing them as edges would overstate what was signed.</p>
      ${groups.map((g) => html`
        <div key=${g.claim} style=${{ marginBottom: 10 }}>
          <div class="claimhead">
            <span class="pill">${g.claim}</span>
            <span>${g.rows.length}</span>
          </div>
          ${CLAIM_NOTE[g.claim] ? html`
            <p class="hint" style=${{ margin: "3px 0 6px" }}>${CLAIM_NOTE[g.claim]}</p>` : null}
          ${g.rows.map((a) => html`
            <div class="annot" key=${a.term}>
              <b>${a.term}</b>
              ${a.in_foodon
                ? html` <${IriField} iri=${a.iri} curie=${a.curie} compact=${true} />`
                : html` <span class="pill">no FoodOn class</span>`}
              <div>${a.reason}</div>
              ${a.source ? html`<div><i>${a.source}</i></div>` : null}
            </div>`)}
        </div>`)}
    </section>`;
}

function Legend() {
  const rows = [
    ["derives from", "var(--derives)", null], ["in taxon", "var(--taxon)", null],
    ["has ingredient", "var(--ingredient)", null], ["is a", "var(--isa)", "4 3"],
    ["part of / has part", "var(--part)", "1 3"],
    ["repaired axiom", "var(--repair)", "7 4"], ["override", "var(--override)", "7 4"],
    ["mined from a definition", "var(--mined)", "6 3"],
  ];
  return html`
    <div class="legend">
      ${rows.map(([label, color, dash]) => html`
        <div key=${label}>
          <span class="swatch" style=${{ borderTopColor: color,
            borderTopStyle: dash ? "dashed" : "solid" }}></span>${label}
        </div>`)}
      <div style=${{ marginTop: 6 }}>
        <span class="dot" style=${{ background: "var(--root)" }}></span>query root</div>
      <div><span class="dot" style=${{ background: "var(--n-organism)" }}></span>
        organism / taxon — the thing being avoided</div>
      <div><span class="dot" style=${{ background: "var(--n-derivative)" }}></span>
        derivative — made from it</div>
      <div><span class="dot ring"></span>grouping class — FoodOn scaffolding, not an ingredient</div>
      <div><span class="dot" style=${{ background: "var(--n-derivative)",
        boxShadow: "0 0 0 2px var(--convergent)" }}></span>reached by several paths</div>
      <div><span class="dot" style=${{ background: "#f4efe6",
        border: "1.4px solid #d8cfbe", borderRadius: 3 }}></span>collapsed — named by
        culinary function where FoodOn has one, else just the count</div>
      <div class="hint" style=${{ marginTop: 6, display: "block" }}>
        Hover any node to trace its route back to the root; the breadcrumb names the
        relation and provenance at every hop.</div>
    </div>`;
}

/* ---------- app shell ---------- */
function App() {
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [expanded, setExpanded] = useState(new Set());
  const [selected, setSelected] = useState(null);
  const [showLow, setShowLow] = useState(true);
  const [alwaysLabels, setAlwaysLabels] = useState(false);
  const [health, setHealth] = useState(null);
  const [revealed, setRevealed] = useState(new Set());
  const [focus, setFocus] = useState(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);   // collapsed by default

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
      if (e.key === "/" && !typing) { e.preventDefault(); setSearchOpen(true); }
      if ((e.key === "f" || e.key === "F") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault(); setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = useCallback(async (term) => {
    if (!term.trim()) return;
    setBusy(true); setErr(null); setSelected(null); setExpanded(new Set());
    setRevealed(new Set()); setFocus(null); setSearchOpen(false);
    setDrawerOpen(false);
    try {
      const r = await fetch("/api/query?q=" + encodeURIComponent(term));
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      setData(j);
    } catch (e) { setErr(e.message); setData(null); }
    finally { setBusy(false); }
  }, []);

  const toggle = useCallback((id) => setExpanded((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  }), []);

  const reveal = useCallback((iri) => {
    setRevealed((prev) => new Set(prev).add(iri));
    setSelected(iri);
    setFocus(iri);
  }, []);

  const selectedNode = useMemo(() =>
    data?.graph?.nodes.find((n) => n.iri === selected) || null, [data, selected]);

  const g = data?.graph;
  return html`
    <${React.Fragment}>
      <header>
        <h1>FoodOn Avoidance Graph${" "}
          <span>${health ? `· ${health.classes.toLocaleString()} classes · FoodOn ${health.foodon_version}` : ""}</span>
        </h1>
        <form onSubmit=${(e) => { e.preventDefault(); run(q); }}>
          <input type="text" value=${q} placeholder="an ingredient or a class — corn, nightshade, gluten…"
            onChange=${(e) => setQ(e.target.value)}
            onKeyDown=${(e) => { if (e.key === "Enter") { e.preventDefault(); run(e.target.value); } }} />
          <button class="primary" type="submit" disabled=${busy}>${busy ? "…" : "Trace"}</button>
        </form>
        <div class="examples">
          ${EXAMPLES.map((x) => html`
            <button key=${x} onClick=${() => { setQ(x); run(x); }}>${x}</button>`)}
        </div>
      </header>
      <main>
        <div class="canvas" style=${{ position: "relative" }}>
          ${busy ? html`<div class="loading">tracing…</div>` : null}
          ${err ? html`<div class="empty"><p>${err}</p></div>` : null}
          ${!busy && !data ? html`
            <div class="empty"><p>Type an ingredient (<b>paprika</b>, <b>edamame</b>) or a
              class (<b>nightshade</b>, <b>allium</b>, <b>gluten</b>). The graph shows
              everything that should be treated as containing it, and the path that
              justifies each one.</p></div>` : null}
          ${!busy && g ? html`
            <${GraphView} graph=${g} expanded=${expanded} onToggle=${toggle}
              onSelect=${setSelected} selected=${selected} showLow=${showLow}
              revealed=${revealed} focus=${focus} matches=${revealed}
              alwaysLabels=${alwaysLabels} />` : null}
          ${!busy && data && !g ? html`
            <div class="empty"><p>No graph: the term did not resolve to a FoodOn class.
              See the panel for the closest candidates.</p></div>` : null}
          ${g ? html`
            <div class="searchwrap">
              <${GraphSearch} graph=${g} open=${searchOpen}
                onOpen=${() => setSearchOpen(true)} onClose=${() => setSearchOpen(false)}
                onReveal=${reveal} />
            </div>` : null}
          ${g ? html`<${JsonDrawer} graph=${g} open=${drawerOpen}
            onToggle=${() => setDrawerOpen((v) => !v)} selectedNode=${selectedNode} />` : null}
          ${g ? html`
            <div class="filters">
              <label><input type="checkbox" checked=${showLow}
                onChange=${(e) => setShowLow(e.target.checked)} />
                show low-confidence nodes</label>
              <label><input type="checkbox" checked=${alwaysLabels}
                onChange=${(e) => setAlwaysLabels(e.target.checked)} />
                always show labels</label>
              <div class="hint" style=${{ marginTop: 4 }}>
                nothing is ever filtered from the data — only from this view</div>
            </div>` : null}
        </div>
        <aside>
          ${data ? html`<section><${Resolution} data=${data} /></section>` : null}
          ${g ? html`
            <section>
              <h2>Graph</h2>
              <div class="stats">
                <div class="stat"><b>${g.counts.nodes.toLocaleString()}</b><span>classes</span></div>
                <div class="stat"><b>${g.counts.edges.toLocaleString()}</b><span>edges</span></div>
                <div class="stat"><b>${g.counts.multi_path}</b><span>multi-path</span></div>
                <div class="stat"><b>${g.counts.convergent_across_roots}</b><span>cross-root</span></div>
              </div>
              <p class="note">provenance:${" "}
                ${Object.entries(g.counts.by_provenance).map(([k, v]) => `${v} ${k}`).join(", ")}</p>
            </section>` : null}
          <section>
            <h2>Selected</h2>
            ${g ? html`<${Detail} node=${selectedNode} graph=${g}
              onClear=${() => setSelected(null)} />` : html`<p class="hint">Run a query first.</p>`}
          </section>
          ${data ? html`<${Annotations} items=${data.annotations} />` : null}
          ${g ? html`<section><h2>Legend</h2><${Legend} /></section>` : null}
          ${health ? html`
            <section>
              <h2>Provenance of this build</h2>
              <p class="hint">
                relation policy ${health.relation_policy} (${health.policy_status})<br />
                ${health.store_entries} pinned resolutions<br />
                ${health.overrides_active} of ${health.overrides} overrides active
                ${health.overrides_annotation ? html`· ${health.overrides_annotation} annotation-only` : null}
                ${health.overrides_declined ? html`· ${health.overrides_declined} declined` : null}
                ${health.overrides_superseded ? html`· ${health.overrides_superseded} retired,
                  now carried by structure` : null}
              </p>
            </section>` : null}
        </aside>
      </main>
    </${React.Fragment}>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);

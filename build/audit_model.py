#!/usr/bin/env python3
"""The audit layer's read and write model: what the local patch layer does to each
ingredient, and how an edit gets back into the decision files.

READ. For every pinned resolution, run the query twice -- once against the full graph
and once against a graph with the whole local layer switched off -- and report the
difference. That comparison is the whole point of the view: a list of 233 decisions
answers "what did we change", and a kitchen needs "what does this tool say about beef,
and how much of that is ours". Measured across the 21 ingredients, the layer adds 27
classes and suppresses 861, which no list-of-decisions view made visible.

WRITE. Every edit lands in a governed decision file, never in the .ttl. The .ttl is
generated from these files by build/emit_patches.py and test/patch_run.py fails on a
hand-edit, so an editor that wrote Turtle would be writing something the next build
discards. `apply_edit` validates, writes, and reports what now needs regenerating.
"""
import json, os, copy, datetime, subprocess, sys

sys.path.insert(0, "build")
from traverse import Graph

OVERRIDES = "config/overrides.json"
TAXON     = "config/taxon-bridges.json"
MINED_SIGNOFF = "config/mined-signoff.json"
MINED_CLASSIFIED = "data/mined-classified.json"
PINS      = "config/resolution-pins.json"
STORE     = "data/resolution-store.json"
REPAIRS   = "data/repairs-classified.json"

TODAY = lambda: datetime.date.today().isoformat()
_read = lambda p: json.load(open(p))


def _write(path, obj):
    """Write via a temp file in the same directory, then rename.

    The decision files are the only copy of months of review. A half-written
    overrides.json from an interrupted request would lose every claim after the
    truncation point, and the failure mode of json.dump onto an open handle is exactly
    that. os.replace is atomic within a filesystem.
    """
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n") if False else None
    os.replace(tmp, path)


def roots_of(o):
    """One reader for both spellings. The data is normalised and test/override_run.py
    keeps it that way, but a file edited by hand between releases should not silently
    lose its suppression."""
    return o.get("query_roots") or ([o["query_root"]] if o.get("query_root") else [])


# --------------------------------------------------------------------------- read
def build(full=None, bare=None):
    g = full or Graph()
    b = bare or Graph(repairs=None, mined=None, taxon_bridges=None,
                      overrides={"overrides": []})
    L = lambda i: (g.N.get(i, {}) or {}).get("l") or i
    cur = lambda i: (i.rsplit("/", 1)[-1].replace("_", ":", 1)) \
        if i and str(i).startswith("http") else None

    dec = []
    for a in _read(REPAIRS)["auto_apply"]:
        dec.append(dict(kind="repair", file=REPAIRS, status="signed", claim="contains",
                        tgt=a["product"], src=a["source"],
                        why=a.get("evidence") or a.get("rule"),
                        by="build/repair_derives.py", conf=a.get("confidence", "high"),
                        editable=False))
    mc = _read(MINED_CLASSIFIED)
    for a in mc["signed_off"]:
        dec.append(dict(kind="mined", file=MINED_SIGNOFF, status="signed", id=a["product"],
                        claim="contains" if a.get("relation") != "is a" else "is a",
                        tgt=a["product"], src=a["source"], why=a.get("rationale"),
                        by=a.get("signed_off_by"), conf=a.get("confidence"),
                        impact=a.get("would_add_classes"), editable=True))
    for a in mc["requires_signoff"]:
        dec.append(dict(kind="mined", file=MINED_CLASSIFIED, status="queued", id=a["product"],
                        claim="contains" if a.get("relation") != "is a" else "is a",
                        tgt=a["product"], src=a["source"], why=a.get("evidence"),
                        by=None, conf=a.get("confidence"),
                        impact=a.get("would_add_classes"), editable=True))
    tb = _read(TAXON)
    for a in tb["signed_off"]:
        dec.append(dict(kind="taxon", file=TAXON, status="signed", id=a["class"],
                        claim="in taxon", tgt=a["class"], src=a["taxon"],
                        why=a.get("evidence"), by=a.get("signed_off_by"),
                        conf=a.get("confidence"), impact=a.get("would_add_classes"),
                        editable=True))
    for a in tb["requires_signoff"]:
        dec.append(dict(kind="taxon", file=TAXON, status="queued", id=a["class"],
                        claim="in taxon", tgt=a["class"], src=a.get("taxon"),
                        why=a.get("question"), by=None, conf=a.get("confidence"),
                        impact=a.get("would_add_classes"), editable=True))
    for i, o in enumerate(_read(OVERRIDES)["overrides"]):
        dec.append(dict(kind="override", file=OVERRIDES, id=i,
                        status={"declined": "declined", "superseded": "superseded"}
                               .get(o.get("type"), "signed"),
                        claim=o.get("claim"), tgt=o.get("target_class"),
                        tgt_label=o.get("target_label"), src=None, why=o.get("reason"),
                        by=o.get("reviewed_by"), conf=o.get("confidence"),
                        roots=roots_of(o), etype=o.get("type"), editable=True))

    store = _read(STORE)["entries"]
    pins = {p["query"]: p for p in _read(PINS)["pins"]}
    groups = {}
    for q, e in store.items():
        if e.get("status") != "resolved":
            continue
        groups.setdefault(tuple(e["roots"]), []).append(q)

    cards = []
    for roots, qs in groups.items():
        rs = list(roots)
        name = min((p for p in pins if p in qs), key=len, default=min(qs, key=len))
        f = set(g.closure(rs)[0]); v = set(b.closure(rs)[0])
        added, removed = f - v, v - f
        e = store[qs[0]]
        mine = []
        for d in dec:
            if d["kind"] == "override":
                if set(d.get("roots") or []) & set(rs): mine.append(d)
            elif d["status"] == "signed":
                if d.get("tgt") in added or (d.get("src") in f and d.get("tgt") in f):
                    mine.append(d)
            elif d["status"] == "queued" and d.get("src") in f:
                mine.append(d)
        cards.append(dict(
            name=name, pin=name in pins, aliases=sorted(qs),
            roots=[L(x) for x in rs], root_curies=[cur(x) for x in rs], root_iris=rs,
            vendor=len(v), ours=len(f), added=len(added), removed=len(removed),
            added_sample=sorted(L(x) for x in added)[:8],
            removed_sample=sorted(L(x) for x in removed)[:8],
            rationale=e.get("rationale"), note=e.get("note"),
            by=e.get("reviewed_by"), date=e.get("reviewed_date"),
            confidence=e.get("confidence"),
            decisions=[_decorate(d, L, cur) for d in mine]))
    cards.sort(key=lambda c: -(c["added"] + c["removed"]))

    used = {(d["kind"], d.get("tgt"), d.get("src"), d["status"])
            for c in cards for d in c["decisions"]}
    rest = [_decorate(copy.deepcopy(d), L, cur) for d in dec
            if (d["kind"], d.get("tgt"), d.get("src"), d["status"]) not in used]
    return dict(cards=cards, rest=rest, ontology=g.meta["version"],
                classes=len(g.N), generated=TODAY())


def _decorate(d, L, cur):
    d = dict(d)
    d["tgt_label"] = d.get("tgt_label") or (L(d["tgt"]) if d.get("tgt") else None)
    d["src_label"] = L(d["src"]) if d.get("src") else None
    d["tgt_curie"] = cur(d.get("tgt")); d["src_curie"] = cur(d.get("src"))
    d.pop("roots", None)
    return d


# -------------------------------------------------------------------------- write
class EditError(Exception):
    pass


def apply_edit(action, p, who="Matt"):
    """Validate and write one edit. Returns the files touched.

    Nothing here writes Turtle. Every action lands in a governed JSON file, and the
    caller regenerates ontology/foodon-local-patches.ttl from those -- which is the
    only direction that survives the next build.
    """
    if action == "signoff":        return _signoff(p, who, True)
    if action == "decline":        return _signoff(p, who, False)
    if action == "edit_override":  return _edit_override(p, who)
    if action == "add_override":   return _add_override(p, who)
    if action == "edit_pin":       return _edit_pin(p, who)
    if action == "statement":      return write_statement(p, who)
    if action == "retire":         return retire(p.get("id"), p.get("reason") or "", who)
    raise EditError(f"unknown action: {action}")


def _need(p, *keys):
    """Missing, not falsy. The first override in the file has id 0, and a truth test
    rejected it as absent -- so the one decision an editor is most likely to open was
    the one it refused to save."""
    for k in keys:
        v = p.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise EditError(f"`{k}` is required")
    return [p[k] for k in keys]


def _signoff(p, who, approve):
    kind, ident = _need(p, "kind", "id")
    why, = _need(p, "rationale")
    if kind == "taxon":
        tb = _read(TAXON)
        hit = [x for x in tb["requires_signoff"] if x["class"] == ident]
        if not hit:
            raise EditError("not in the taxon review queue (already decided?)")
        item = hit[0]
        tb["requires_signoff"] = [x for x in tb["requires_signoff"] if x["class"] != ident]
        if approve:
            if not item.get("taxon"):
                raise EditError("this candidate has no taxon to bridge to; FoodOn has no "
                                "class for it, so signing it off would assert nothing")
            tb["signed_off"].append({**{k: v for k, v in item.items() if k != "question"},
                                     "evidence": why, "signed_off_by": who,
                                     "signed_off_date": TODAY()})
        else:
            tb["declined"].append({"class": item["class"], "class_label": item.get("class_label"),
                                   "reason": why, "declined_by": who, "declined_date": TODAY()})
        _write(TAXON, tb)
        return [TAXON]
    if kind == "mined":
        sg = _read(MINED_SIGNOFF)
        sg["decisions"][ident] = {"apply": bool(approve),
                                  "confidence": p.get("confidence") or "medium",
                                  "label": p.get("label"), "rationale": why}
        sg["reviewed_by"] = who; sg["reviewed_date"] = TODAY()
        _write(MINED_SIGNOFF, sg)
        return [MINED_SIGNOFF, MINED_CLASSIFIED]
    raise EditError(f"`{kind}` has no review queue")


EDITABLE = {"claim", "reason", "confidence", "source", "review_note", "type"}


def _edit_override(p, who):
    i, = _need(p, "id")
    d = _read(OVERRIDES)
    try:
        o = d["overrides"][int(i)]
    except (IndexError, ValueError):
        raise EditError("no such override")
    fields = p.get("fields") or {}
    unknown = set(fields) - EDITABLE
    if unknown:
        raise EditError(f"not editable here: {', '.join(sorted(unknown))}. Target and "
                        f"query roots are the identity of a claim -- retire it and add "
                        f"a new one rather than repointing it, so the trail survives.")
    if "claim" in fields and fields["claim"] not in d["claim_types"]:
        raise EditError(f"`{fields['claim']}` is not a declared claim type")
    if "type" in fields and fields["type"] not in d["entry_types"]:
        raise EditError(f"`{fields['type']}` is not a declared entry type")
    o.update(fields)
    o["reviewed_by"] = who; o["reviewed_date"] = TODAY()
    _write(OVERRIDES, d)
    return [OVERRIDES]


def _add_override(p, who):
    tgt, claim, reason = _need(p, "target_class", "claim", "reason")
    roots = p.get("query_roots") or []
    if not roots:
        raise EditError("a claim needs at least one query root: it is a statement about "
                        "what a particular query should return")
    d = _read(OVERRIDES)
    if claim not in d["claim_types"]:
        raise EditError(f"`{claim}` is not a declared claim type")
    g = Graph()
    if tgt not in g.N:
        raise EditError(f"{tgt} is not a class in this FoodOn release")
    for r in roots:
        if r not in g.N:
            raise EditError(f"root {r} is not a class in this FoodOn release")
    L = lambda i: (g.N.get(i, {}) or {}).get("l") or i
    d["overrides"].append({
        "type": p.get("type", "add"), "claim": claim, "status": "REVIEWED",
        "query_class": p.get("query_class") or L(roots[0]),
        "query_roots": roots, "query_root_labels": [L(r) for r in roots],
        "target_label": L(tgt), "target_class": tgt, "in_foodon": True,
        "confidence": p.get("confidence", "medium"), "reason": reason,
        "source": p.get("source"), "reviewed_by": who, "reviewed_date": TODAY(),
        "review_note": p.get("review_note")})
    _write(OVERRIDES, d)
    return [OVERRIDES]


PIN_EDITABLE = {"rationale", "note", "confidence", "root_labels", "aliases"}


def _edit_pin(p, who):
    q, = _need(p, "query")
    spec = _read(PINS)
    hit = [x for x in spec["pins"] if x["query"] == q]
    if not hit:
        raise EditError(f"no pin for `{q}`")
    fields = p.get("fields") or {}
    unknown = set(fields) - PIN_EDITABLE
    if unknown:
        raise EditError(f"not editable: {', '.join(sorted(unknown))}")
    if "root_labels" in fields:
        from resolve import Resolver
        ix = Resolver(store=None).label_ix
        missing = [x for x in fields["root_labels"] if x.lower() not in ix]
        if missing:
            raise EditError(f"no FoodOn class labelled: {', '.join(missing)}")
        if not fields["root_labels"]:
            raise EditError("a pin with no roots resolves to nothing; delete it instead")
    hit[0].update(fields)
    hit[0]["reviewed_by"] = who; hit[0]["reviewed_date"] = TODAY()
    _write(PINS, spec)
    return [PINS, STORE]


def regenerate(files):
    """Re-derive whatever the touched files feed. Returns (log, sparql_stale)."""
    steps, log = [], []
    if PINS in files or STORE in files:
        steps.append(["python3", "build/build_resolution_store.py"])
    if MINED_SIGNOFF in files or MINED_CLASSIFIED in files:
        steps.append(["python3", "build/classify_mined.py"])
    steps.append(["python3", "build/emit_patches.py"])
    for cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True)
        log.append({"cmd": " ".join(cmd), "ok": r.returncode == 0,
                    "out": (r.stdout or r.stderr or "").strip()[-1200:]})
        if r.returncode != 0:
            return log, True
    return log, True


# ===========================================================================
# The statement layer
# ===========================================================================
# Six files, six field vocabularies, and a reviewer who wants to say one thing:
# "tahini derives from sesame plant". The audit UI's first edit form asked which of
# `reason`, `review_note` and `confidence` to change -- prose about a relationship it
# gave no way to state. This is that missing vocabulary.
#
# Every decision in the layer is SUBJECT - PREDICATE - OBJECT. The predicate decides
# which file the statement lands in, so a reviewer never picks a file, and the shape of
# `config/mined-signoff.json` stops being something anyone has to know.
#
# `enters` is the property that matters for safety: a statement that enters the closure
# changes what a diner is told to avoid, and one that does not is reported beside the
# graph. It is carried here rather than inferred at each call site because getting it
# wrong in either direction is the failure this project exists to prevent.

PREDICATES = {
    "derives from": dict(
        label="derives from", enters=True, obo="RO:0001000", lands=OVERRIDES,
        claim="contains", subject="the product", object="the source it is made from",
        help="Avoidance travels source to product: a query for the OBJECT will reach "
             "the SUBJECT. FoodOn omits this on 62% of its `<X> food product` classes."),
    "is a": dict(
        label="is a", enters=True, obo="rdfs:subClassOf", lands=MINED_SIGNOFF,
        claim="is a", subject="the narrower class", object="its parent",
        help="A missing subsumption. Use only where FoodOn's own definition states it; "
             "a wrong parent widens every query that passes through."),
    "in taxon": dict(
        label="in taxon", enters=True, obo="RO:0002162", lands=TAXON,
        claim="in taxon", subject="the FoodOn class", object="its species-rank taxon",
        help="The route FoodOn itself uses to tie a plant to the taxonomy. The object "
             "must be a binomial: a genus or family would silently widen the query."),
    "may derive from": dict(
        label="may derive from", enters=False, obo="local:mayDeriveFrom", lands=OVERRIDES,
        claim="may_contain", subject="the substance", object="the query it may come from",
        help="Feedstock is a producer's choice, not a property of the substance. "
             "Reported beside the graph, never in it."),
    "shares compound with": dict(
        label="shares compound with", enters=False, obo="local:sharesCompoundWith",
        lands=OVERRIDES, claim="shared_compound", subject="the compound",
        object="the ingredient it shares it with",
        help="The same molecule reached another way. For an INTOLERANCE, where the "
             "response is to the molecule and its origin does not matter."),
    "cross reactive with": dict(
        label="cross reactive with", enters=False, obo="local:crossReactiveWith",
        lands=OVERRIDES, claim="cross_reactive", subject="the food",
        object="the allergen it is related to",
        help="Immunologically related, allergen protein NOT present. As containment "
             "this is wrong in the direction that needlessly excludes safe food."),
    "disputed for": dict(
        label="disputed for", enters=False, obo="local:disputedAvoidance", lands=OVERRIDES,
        claim="disputed", subject="the food", object="the avoidance it appears under",
        help="On avoidance lists without an established containment basis. Recorded so "
             "the claim is visible and auditable."),
    "not relevant for": dict(
        label="not relevant for", enters=False, obo="local:notAvoidanceRelevantFor",
        lands=OVERRIDES, claim="not_avoidance_relevant", entry_type="remove",
        subject="the class to suppress", object="the query it should not appear in",
        help="OWL cannot retract, so an upstream axiom that is defensible and wrong for "
             "avoidance is suppressed declaratively. The largest edits in this layer are "
             "these -- check them hardest."),
}


def vocabulary():
    g = Graph()
    return dict(predicates=PREDICATES,
                claim_types=_read(OVERRIDES).get("claim_types", {}),
                classes=len(g.N), ontology=g.meta["version"])


def lookup(q, limit=12, graph=None):
    """Find a class by what a person would type. Labels first, then synonyms.

    Pasting an IRI was the only way to name a class in the first editor, which is a
    reasonable thing to ask of a script and not of a reviewer. Closure size rides along
    because it is the number that decides whether a candidate is the right grain:
    FoodOn's own `tree nut` class looks perfect and reaches 2 classes.
    """
    from resolve import Resolver
    r = Resolver(graph=graph, store=None)
    g = r.g
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    hits, seen = [], set()

    def push(iri, how):
        if iri in seen or iri not in g.N or g.N[iri].get("dep"):
            return
        seen.add(iri)
        hits.append(dict(iri=iri, label=g.label(iri), how=how,
                         curie=iri.rsplit("/", 1)[-1].replace("_", ":", 1),
                         excluded=iri in g.excluded))

    if q in r.label_ix:
        push(r.label_ix[q], "exact label")
    for lab, iri in r.label_ix.items():
        if len(hits) >= limit * 3: break
        if lab.startswith(q): push(iri, "label")
    for lab, iri in r.label_ix.items():
        if len(hits) >= limit * 3: break
        if q in lab: push(iri, "label contains")
    for syn, iris in r.syn_ix.items():
        if len(hits) >= limit * 3: break
        if q in syn:
            for i in iris[:2]: push(i, f"synonym: {syn}")
    hits = hits[:limit]
    for h in hits:
        h["closure"] = len(g.closure([h["iri"]])[0])
    return hits


def _candidate_graph(stmt, g):
    """A graph with the statement applied, without writing anything.

    The same mutations traverse.py makes when it loads a decision file, so a preview
    cannot drift from what saving would do -- a preview computed a second way is a
    second implementation to keep honest.
    """
    import copy as _c
    h = _c.copy(g)
    h.derive = _c.deepcopy(g.derive); h.children = _c.deepcopy(g.children)
    h.suppress = _c.deepcopy(g.suppress)
    p = PREDICATES[stmt["predicate"]]
    s, o = stmt["subject"], stmt["object"]
    if p["claim"] == "contains":
        h.derive[o].append((s, "http://purl.obolibrary.org/obo/RO_0001000", "override", "high"))
    elif p["claim"] == "is a":
        h.children[o].append((s, "isa", "isa", "high"))
    elif p["claim"] == "in taxon":
        h.derive[o].append((s, "http://purl.obolibrary.org/obo/RO_0002162", "rel", "high"))
    elif p["claim"] == "not_avoidance_relevant":
        h.suppress[o].add(s)
    return h


def preview(stmt, graph=None):
    """Which pinned ingredients does this statement change, and by how much?

    The question a reviewer actually has before signing anything, and the one the
    decision files answer only after a rebuild. A weak claim reports no closure change
    because that is precisely what it means.
    """
    g = graph or Graph()
    L = lambda i: (g.N.get(i, {}) or {}).get("l") or i
    p = PREDICATES.get(stmt.get("predicate"))
    if not p:
        raise EditError(f"unknown predicate: {stmt.get('predicate')}")
    for side in ("subject", "object"):
        if not stmt.get(side):
            raise EditError(f"`{side}` is required: a statement needs both ends")
        if stmt[side] not in g.N:
            raise EditError(f"{stmt[side]} is not a class in this FoodOn release")
    if p["claim"] == "in taxon":
        import re as _re
        if not _re.match(r"^[A-Z][a-z]+(?: x)? [a-z][a-z-]+", L(stmt["object"])):
            raise EditError(f"`{L(stmt['object'])}` is not a species-rank binomial; a "
                            f"genus or family here silently widens every query that "
                            f"reaches it")
    out = dict(enters=p["enters"], changes=[], note=None)
    # A suppression does not ENTER the closure and very much CHANGES it -- the two
    # largest edits in this layer are suppressions. Reporting "no closure changes" for
    # the only decisions that remove food from an avoidance list would have been the
    # worst thing this preview could say.
    suppresses = p["claim"] == "not_avoidance_relevant"
    if not p["enters"] and not suppresses:
        out["note"] = ("Reported beside the graph, never in it, so no closure changes. "
                       "It will appear under `Reported, not traversed` for "
                       + L(stmt["object"]) + ".")
        return out
    # Already in force? Then "nothing changes" is true and misleading -- the reviewer
    # is looking at a decision whose effect the card above already shows.
    already = False
    s_, o_ = stmt["subject"], stmt["object"]
    if suppresses:
        already = s_ in (g.suppress.get(o_) or set())
    elif p["claim"] == "is a":
        already = any(c[0] == s_ for c in g.children.get(o_, ()))
    else:
        already = any(c[0] == s_ for c in g.derive.get(o_, ()))
    if already:
        out["note"] = ("This statement is already in force, so nothing moves. The card "
                       "above shows what it does today.")
        out["already"] = True
        return out

    h = _candidate_graph(stmt, g)
    store = _read(STORE)["entries"]
    groups = {}
    for q, e in store.items():
        if e.get("status") == "resolved":
            groups.setdefault(tuple(e["roots"]), []).append(q)
    for roots, qs in groups.items():
        rs = list(roots)
        before = set(g.closure(rs)[0]); after = set(h.closure(rs)[0])
        gained, lost = after - before, before - after
        if gained or lost:
            out["changes"].append(dict(
                ingredient=min(qs, key=len), gained=len(gained), lost=len(lost),
                sample=sorted(L(x) for x in (gained or lost))[:6]))
    out["changes"].sort(key=lambda c: -(c["gained"] + c["lost"]))
    if not out["changes"]:
        out["note"] = ("No pinned ingredient's answer changes. The statement is still "
                       "recorded -- it may matter to a query that is not pinned, or to "
                       "a later one -- but nothing a diner asks for today moves.")
    return out


def write_statement(st, who="Matt"):
    """Record a statement in whichever file its predicate belongs to.

    The reviewer names a relationship; the storage is derived. Before this, adding a
    bridge meant knowing that a `derives from` goes in overrides.json as claim
    `contains` while an `in taxon` goes in taxon-bridges.json under `signed_off` -- six
    file shapes to hold what is, in the end, eight kinds of sentence.
    """
    p = PREDICATES.get(st.get("predicate"))
    if not p:
        raise EditError(f"unknown predicate: {st.get('predicate')}")
    why, = _need(st, "reason")
    preview(st)                      # validates both ends, rank guard, class existence
    g = Graph()
    L = lambda i: (g.N.get(i, {}) or {}).get("l") or i
    subj, obj = st["subject"], st["object"]
    conf = st.get("confidence", "medium")

    if p["lands"] == TAXON:
        d = _read(TAXON)
        if any(x["class"] == subj for x in d["signed_off"]):
            raise EditError(f"`{L(subj)}` already has a signed taxon link; edit that one")
        d["requires_signoff"] = [x for x in d["requires_signoff"] if x["class"] != subj]
        d["signed_off"].append(dict(**{"class": subj, "class_label": L(subj),
            "taxon": obj, "taxon_label": L(obj), "confidence": conf, "evidence": why,
            "signed_off_by": who, "signed_off_date": TODAY()}))
        _write(TAXON, d)
        return [TAXON]

    if p["lands"] == MINED_SIGNOFF:
        d = _read(MINED_SIGNOFF)
        d["decisions"][subj] = {"apply": True, "confidence": conf,
                                "label": f"{L(subj)} -> {L(obj)}", "rationale": why}
        d["reviewed_by"] = who; d["reviewed_date"] = TODAY()
        _write(MINED_SIGNOFF, d)
        return [MINED_SIGNOFF, MINED_CLASSIFIED]

    d = _read(OVERRIDES)
    d["overrides"].append({
        "type": p.get("entry_type", "add"), "claim": p["claim"], "status": "REVIEWED",
        "query_class": L(obj), "query_roots": [obj], "query_root_labels": [L(obj)],
        "target_label": L(subj), "target_class": subj, "in_foodon": True,
        "confidence": conf, "reason": why, "source": st.get("source"),
        "reviewed_by": who, "reviewed_date": TODAY(),
        "review_note": st.get("review_note")})
    _write(OVERRIDES, d)
    return [OVERRIDES]


def retire(ident, why, who="Matt"):
    """Mark an override superseded rather than deleting it.

    This is how a relationship gets REPOINTED. Editing target or roots in place would
    rewrite history: the entry would claim to have always said the new thing, and
    test/override_run.py would still pass. Retiring and restating leaves both halves on
    the record, which is the only version an audit can check.
    """
    d = _read(OVERRIDES)
    try:
        o = d["overrides"][int(ident)]
    except (IndexError, ValueError):
        raise EditError("no such override")
    if o.get("type") == "superseded":
        raise EditError("already retired")
    o["type"] = "superseded"
    o["superseded_reason"] = why
    o["reviewed_by"] = who; o["reviewed_date"] = TODAY()
    _write(OVERRIDES, d)
    return [OVERRIDES]

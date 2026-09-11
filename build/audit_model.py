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

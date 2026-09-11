#!/usr/bin/env python3
"""Overrides must actually reach the graph when signed, and must not when not.

Exists because they did not: `add` entries were indexed on the query LABEL rather
than on the resolved root IRIs, so every one of them was inert. A signed override
that silently does nothing is the worst failure mode this file has, since the
reviewer believes a safety claim is in force when it is not.
"""
import json, sys, collections
sys.path.insert(0, "build")
from resolve import Resolver

r = Resolver(); g = r.g
ov = json.load(open("config/overrides.json"))
fails, checks = [], 0

annotation = [o for o in ov["overrides"] if o.get("annotation_only")]
declined = [o for o in ov["overrides"] if o.get("type") == "declined"]
# `superseded`: was correct and signed, and is now carried by structure. Inert, and
# excluded from `active` so it is not reported as merely redundant -- redundant means
# "this entry is doing no work and nobody has decided that", retired means someone
# has. Check 5 below is what keeps the retirement honest.
superseded = [o for o in ov["overrides"] if o.get("type") == "superseded"]
active   = [o for o in ov["overrides"] if o.get("reviewed_by")
            and o.get("type") not in ("declined", "superseded")
            and not o.get("annotation_only")]
held     = [o for o in ov["overrides"] if o.get("status") == "HELD"]
pending  = [o for o in ov["overrides"] if not o.get("reviewed_by") and o.get("status") != "HELD"]
signed   = active

print(f"{len(ov['overrides'])} overrides: {len(active)} active, {len(annotation)} annotation-only, "
      f"{len(held)} held, {len(declined)} declined, {len(superseded)} superseded, "
      f"{len(pending)} unreviewed\n")

# 1. every add override names roots that resolve, or it can never fire
for o in ov["overrides"]:
    if o.get("type") != "add": continue
    checks += 1
    if not o.get("query_roots"):
        fails.append(f"{o['query_class']} -> {o['target_label']}: no resolvable query "
                     f"root, so this entry would be inert even if signed")

# 2. What a signed add override must do depends on its CLAIM, because the closure
#    means exactly one thing: treat this as containing the query.
#
#    claim `contains`  -> must put its target in the graph. It need not be the edge
#                         that does so: `sodium caseinate is_a casein`, so once the
#                         casein override fires, sodium caseinate arrives by ordinary
#                         descent. That makes its own entry REDUNDANT, worth
#                         reporting but not a failure.
#    any other claim   -> must NOT reach the graph by an override edge. `may_contain`
#                         is a producer's feedstock choice and `cross_reactive`
#                         explicitly says the allergen protein is absent; drawing
#                         either as containment is a false claim, and for
#                         cross_reactive it is false in the direction that needlessly
#                         excludes safe food. These are carried as reported claims
#                         instead — asserted by check 2b.
redundant = []
for o in signed:
    if o.get("type") != "add": continue
    if not o.get("target_class"): continue
    checks += 1
    nodes, edges = g.closure(o["query_roots"])
    direct = any(e["provenance"] == "override" and e["target"] == o["target_class"]
                 for e in edges)
    if o.get("claim") != "contains":
        if direct:
            fails.append(f"claim `{o.get('claim')}` drawn as CONTAINMENT: "
                         f"{o['query_class']} -> {o['target_label']}")
        continue
    if o["target_class"] not in nodes:
        fails.append(f"SIGNED but absent from the graph: {o['query_class']} -> {o['target_label']}")
        continue
    if not direct:
        redundant.append(f"{o['query_class']} -> {o['target_label']}: reached by ordinary "
                         f"traversal once other overrides applied; this entry adds nothing")

# 2a-0. ONE spelling for the query root. `remove` entries used to carry `query_root`
#     (singular) while `add` entries carried `query_roots`, and every consumer had to
#     remember the fallback. The two that forgot lost peanut/tree-nut and beef/dairy --
#     the largest suppressions in the layer -- from output that looked complete.
for o in ov["overrides"]:
    checks += 1
    if o.get("query_root") or o.get("query_root_label"):
        fails.append(f"{o.get('target_label')} uses the singular `query_root`; the field "
                     f"is `query_roots` so one read reaches every entry")

# 2a-i. every claim used must be DECLARED. The claim vocabulary is what decides
#     whether an entry enters the closure, and a typo (`may contain`, `shared-compound`)
#     would silently fall through the not-`contains` branch and be reported instead of
#     drawn -- safe by luck, not by design. It also keeps the UI honest: web/app.js and
#     the patch emitter both key off these names, so an undeclared claim reaches the
#     reader with no explanation of what it means.
declared = set(ov.get("claim_types") or {}) | {"not_avoidance_relevant"}
for o in ov["overrides"]:
    c = o.get("claim")
    if not c: continue
    checks += 1
    if c not in declared:
        fails.append(f"claim `{c}` is used by {o.get('target_label')} but not declared "
                     f"in claim_types; declared are {sorted(declared)}")

# 2b. ...and a weaker claim must still be REPORTED, or removing it from the closure
#     would have quietly deleted a safety note the reviewer signed.
for o in signed:
    if o.get("type") != "add" or o.get("annotation_only"): continue
    if o.get("claim") == "contains" or not o.get("target_class"): continue
    checks += 1
    key = (o.get("query_class"), o.get("target_class"))
    reported = any((w.get("query_class"), w.get("target_class")) == key
                   for root in o["query_roots"]
                   for w in g.weak_claims.get(root, ()))
    if not reported:
        fails.append(f"claim `{o.get('claim')}` neither drawn nor reported, so it is "
                     f"silently lost: {o['query_class']} -> {o['target_label']}")

# 3. anything not active -- pending, held or declined -- must NOT affect the graph
for o in pending + held + declined + annotation + superseded:
    if o.get("type") not in ("add", "declined", "superseded") \
       or not o.get("target_class") or not o.get("query_roots"):
        continue
    checks += 1
    nodes, edges = g.closure(o["query_roots"])
    if any(e["provenance"] == "override" and e["target"] == o["target_class"] for e in edges):
        fails.append(f"{o.get('status','PENDING')} but already applied: "
                     f"{o['query_class']} -> {o['target_label']}")

# 3b. an annotation must have no FoodOn class -- if one appears, it should be
#     promoted to a real edge rather than left as text
for o in annotation:
    checks += 1
    if o.get("target_class"):
        fails.append(f"ANNOTATION but a FoodOn class now exists for "
                     f"{o['target_label']}: promote it to a real override")

# 3c. RETIREMENT MUST NOT LOSE COVERAGE. A superseded entry was a real containment
#     claim; retiring it is only safe while something else still reaches the target.
#     If the structural route that replaced it ever breaks -- a FoodOn re-parenting,
#     an un-signed bridge -- this fails and names the entry to reinstate. Without
#     this check, retiring an override is an untested deletion of a safety claim.
for o in superseded:
    if not o.get("target_class") or not o.get("query_roots"):
        continue
    checks += 1
    nodes, edges = g.closure(o["query_roots"])
    if o["target_class"] not in nodes:
        fails.append(f"SUPERSEDED but no longer reached at all: {o['query_class']} -> "
                     f"{o['target_label']}. The route named in `superseded_by` is gone; "
                     f"reinstate this entry (set type back to `add`) or restore that route")
        continue
    via = sorted({e["provenance"] for e in edges if e["target"] == o["target_class"]})
    if via == ["override"]:
        fails.append(f"SUPERSEDED but still reached only by an override: "
                     f"{o['query_class']} -> {o['target_label']}")
    else:
        print(f"  retired safely: {o['query_class']} -> {o['target_label']} "
              f"now reached via {', '.join(via)}")

# 4. signed remove overrides must actually suppress
for o in signed:
    if o.get("type") != "remove": continue
    checks += 1
    _roots = o.get("query_roots") or ([o["query_root"]] if o.get("query_root") else [])
    nodes, _ = g.closure(_roots)
    if o["target_class"] in nodes:
        _rl = (o.get("query_root_labels") or [o.get("query_root_label")])[0]
        fails.append(f"SIGNED remove had no effect: {_rl} still reaches "
                     f"{o['target_label']}")

by = collections.Counter(o["claim"] for o in ov["overrides"])
print("by claim:", dict(by))
print(f"targets absent from FoodOn: "
      f"{sum(1 for o in ov['overrides'] if o.get('in_foodon') is False)}")
if redundant:
    print(f"\n{len(redundant)} REDUNDANT (safe, but the entry is doing no work):")
    for x in redundant: print("   -", x)
if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails: print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

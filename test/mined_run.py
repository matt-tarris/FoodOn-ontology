#!/usr/bin/env python3
"""Mined bridges must be inert until signed, and the guards must keep their catches.

The failure mode this file exists for: a candidate generated from an English
sentence quietly becoming an axiom. `data/mined-classified.json` is a proposal
document, and the traversal must read only its `signed_off` list. The second half
pins the three guards against the specific traps that motivated them, so a later
tweak to the regexes cannot silently re-admit them.
"""
import json, sys, collections

sys.path.insert(0, "build")
from traverse import Graph

g = Graph()
mined = json.load(open("data/mined-classified.json"))
sign = json.load(open("config/mined-signoff.json"))
fails, checks = [], 0

queue = mined["requires_signoff"]
signed = mined["signed_off"]
rejected = mined["rejected_by_guard"]
declined = mined["declined"]

print(f"{len(queue) + len(signed) + len(declined) + len(rejected)} candidates: "
      f"{len(signed)} signed, {len(queue)} awaiting review, "
      f"{len(declined)} declined, {len(rejected)} rejected by a guard\n")

# 1. NOTHING awaiting review may appear in any answer.
for c in queue:
    checks += 1
    nodes, edges = g.closure([c["source"]])
    if any(e["provenance"] == "mined" and e["target"] == c["product"] for e in edges):
        fails.append(f"UNSIGNED but applied: {c['product_label']} -> {c['source_label']}")

# 2. ...and neither may anything a reviewer declined.
for c in declined:
    checks += 1
    nodes, edges = g.closure([c["source"]])
    if any(e["provenance"] == "mined" and e["target"] == c["product"] for e in edges):
        fails.append(f"DECLINED but applied: {c['product_label']} -> {c['source_label']}")

# 3. A signed bridge must actually reach the graph, or the reviewer believes a
#    safety claim is in force when it is not. Same reasoning as override_run.py.
for c in signed:
    checks += 1
    nodes, _ = g.closure([c["source"]])
    if c["product"] not in nodes:
        fails.append(f"SIGNED but absent: {c['product_label']} -> {c['source_label']}")

# 3b. A signed bridge whose product is already reachable WITHOUT its own edge is
#     redundant. Safe, but the entry is doing no work and a reviewer should know
#     which of their signatures are load-bearing. `white tahini is_a tahini`, so
#     once the tahini bridge fires it arrives by ordinary descent. Reported, never
#     a failure -- same treatment as the sodium caseinate override.
redundant = []
for c in signed:
    checks += 1
    nodes, edges = g.closure([c["source"]])
    direct = any(e["provenance"] == "mined" and e["target"] == c["product"]
                 for e in edges)
    if c["product"] in nodes and not direct:
        redundant.append(f"{c['product_label']} -> {c['source_label']}: reached by "
                         f"ordinary traversal once the other signed bridges applied")

# 4. The queue is only meaningful if the sign-off file is keyed the way the
#    classifier reads it. An entry naming a product that is not a candidate is a
#    typo that would silently never apply.
known = {c["product"] for c in queue + signed + declined + rejected}
for iri in sign.get("decisions", {}):
    checks += 1
    if iri not in known:
        fails.append(f"sign-off names a product that is not a candidate: {iri}")

# 5. Guard regression pins. Each of these was a real false positive found while
#    measuring the rules; the guard named must still be the one that rejects it.
PINS = {
    "pear tomato plant":  "product is itself an organism",
    "food milling":       "product is a process class",
    "enzyme supplement":  "definition lists examples",
    "chocolate (imitation)": "marks an analog or an exclusion",
}
byproduct = collections.defaultdict(list)
for c in rejected:
    byproduct[c["product_label"]].append(c["rejected_by"])
for label, expect in PINS.items():
    checks += 1
    got = byproduct.get(label)
    if not got:
        fails.append(f"guard pin lost: `{label}` is no longer rejected at all")
    elif not any(expect in r for r in got):
        fails.append(f"guard pin changed: `{label}` rejected by {got!r}, expected {expect!r}")

# 6. The rules that were measured and REJECTED must stay out. `<X> syrup` and
#    `<X> sauce` name the dish, not the source: `pancake syrup -> pancake`.
for c in queue + signed:
    checks += 1
    if c["rule"].startswith("C:"):
        fails.append(f"product-form rule C was measured at ~50% precision and is "
                     f"deliberately not implemented: {c['product_label']}")

# 7. Every queued candidate must carry its impact, and the one candidate measured
#    to pull in a contradiction must keep saying so. A dry run of
#    `pasta food product -> wheat plant` grew a gluten query by 135 classes and
#    reached `gluten-free pasta`; if that flag ever disappears, a reviewer would
#    approve it believing it were clean.
for c in queue:
    checks += 1
    if "would_add_classes" not in c:
        fails.append(f"queued without an impact estimate: {c['product_label']}")
checks += 1
pasta = [c for c in queue if c["product_label"] == "pasta food product"]
if pasta and not pasta[0].get("conflicts"):
    fails.append("`pasta food product -> wheat plant` no longer reports its conflict "
                 "with gluten-free pasta")

byrule = collections.Counter(c["rule"].split(":")[0] for c in queue)
print("awaiting sign-off by rule:", dict(byrule))
print("rejected by guard:")
for gname, n in collections.Counter(
        c["rejected_by"].split(":")[0] for c in rejected).most_common():
    print(f"   {n:>4}  {gname}")

if not sign.get("reviewed_by"):
    print(f"\n{len(queue)} candidates are UNREVIEWED, so they change no answer. "
          f"Set reviewed_by in config/mined-signoff.json and add a decision per "
          f"product IRI to apply any of them.")

if redundant:
    print(f"\n{len(redundant)} REDUNDANT (safe, but the entry is doing no work):")
    for x in redundant:
        print("   -", x)

if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print(f"\nPASS - {checks} assertions")

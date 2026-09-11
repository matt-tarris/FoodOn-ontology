#!/usr/bin/env python3
"""Attach LLM proposals to the ingredient review queue, under contract.

    python3 build/propose_ingredient_map.py proposals.json

THE CONTRACT. The model proposes a TERM; build/resolve.py must then find it. A proposal
the resolver cannot find is REFUSED and recorded as such -- it never reaches the queue
as a recommendation. This is the guard that matters: asked to pick FoodOn classes
directly, a model in this project's own blind test invented `game meat food product`,
which does not exist, and resolved `white fish` to all 3,173 fish. Asked to name a food
and made to prove the name resolves, it cannot do either.

Abstention is a first-class answer. `null` means "FoodOn has nothing for this", and
`{"decline": reason}` means "this is not an ingredient" -- equipment, a stray adjective,
a line the parser should never have produced. Both are more useful than a guess.

Nothing here signs anything off. Proposals land next to the queue entry for a human to
approve in batches; build/ingest.py still reads only `signed_off_by`.
"""
import json, sys, os, collections

sys.path.insert(0, "build")
from resolve import Resolver
from ingest import MAP_FILE

src = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
proposals = json.load(open(src))
spec = json.load(open(MAP_FILE))
r = Resolver()
g = r.g

queue = {e["term"]: e for e in spec["requires_signoff"]}
stat = collections.Counter()
refused = []

for term, p in proposals.items():
    e = queue.get(term)
    if e is None:
        stat["not in queue"] += 1
        continue
    e.pop("proposed", None); e.pop("proposed_roots", None)
    e.pop("proposed_closure", None); e.pop("declined_reason", None)
    if p is None:
        e["proposed"] = None
        e["proposed_by"] = "Claude (offline pass)"
        e["proposed_note"] = "FoodOn has no class for this; the ingredient will quarantine its recipe"
        stat["abstained"] += 1
        continue
    if isinstance(p, dict) and p.get("decline"):
        e["proposed"] = None
        e["proposed_by"] = "Claude (offline pass)"
        e["declined_reason"] = p["decline"]
        stat["declined as not an ingredient"] += 1
        continue
    res = r.resolve(p)
    if res["status"] != "resolved":
        refused.append((term, p, res["status"]))
        e["proposed"] = None
        e["proposed_by"] = "Claude (offline pass)"
        e["proposed_note"] = f"REFUSED: proposed `{p}`, which the resolver returns as {res['status']}"
        stat["refused by the resolver"] += 1
        continue
    e["proposed"] = p
    e["proposed_roots"] = res["root_labels"]
    e["proposed_closure"] = len(g.closure(res["roots"])[0])
    e["proposed_by"] = "Claude (offline pass)"
    stat["proposed"] += 1

json.dump(spec, open(MAP_FILE, "w"), indent=2)
total = len(spec["requires_signoff"])
covered = sum(1 for e in spec["requires_signoff"] if "proposed_by" in e)
print(f"queue {total} terms, {covered} now carry a proposal\n")
for k, v in stat.most_common():
    print(f"   {k:<32} {v}")
if refused:
    print(f"\nREFUSED BY THE RESOLVER ({len(refused)}) -- the model named something FoodOn does not have:")
    for t, p, why in refused[:20]:
        print(f"   {t[:34]:<36} -> {p!r} ({why})")
uses_prop = sum(e["uses"] for e in spec["requires_signoff"] if e.get("proposed"))
uses_all = sum(e["uses"] for e in spec["requires_signoff"])
print(f"\nif every proposal were approved: {uses_prop:,} of {uses_all:,} queued uses "
      f"({100*uses_prop/uses_all:.0f}%) would map")

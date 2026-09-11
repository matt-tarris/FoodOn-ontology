#!/usr/bin/env python3
"""Build the ingredient-mapping review queue from a recipe corpus.

    python3 build/seed_ingredient_map.py path/to/recipes.json [top_n]

Writes config/ingredient-map.json. NOTHING it writes is active: proposals land in
`requires_signoff`, and build/ingest.py reads only entries carrying `signed_off_by`.
A pipeline that applied its own suggestions would make the review theatre.

The queue is ordered by USE, not alphabetically, because the vocabulary is steeply
headed -- on 5,000 real recipes the top 500 terms carry 80% of the corpus. Each
proposal arrives with candidate targets already resolved, so a reviewer is answering
"is `red pepper flakes` chili pepper?" rather than going to look it up.

CANDIDATES ARE OFFERED, NOT APPLIED, and the risky ones say so. Dropping the last word
is how `chili oil` becomes oil and `goat cheese` becomes cheese -- the modifier was
carrying the food. Those candidates are still shown, because sometimes the head noun is
right (`bread flour` is flour), but they are flagged and they are never the only option.
"""
import json, re, sys, collections, os

sys.path.insert(0, "build")
from ingest import normalise, strip_qualifiers, lines_from, MAP_FILE
from resolve import Resolver

VEHICLE = {"oil", "powder", "sauce", "broth", "stock", "juice", "butter", "flour",
           "sugar", "cheese", "milk", "vinegar", "extract", "paste", "syrup", "salt",
           "water", "wine", "cream", "seeds", "leaves"}

corpus = sys.argv[1] if len(sys.argv) > 1 else None
TOP = int(sys.argv[2]) if len(sys.argv) > 2 else 500
if not corpus:
    sys.exit(__doc__)

r = Resolver()
g = r.g
cache = {}
def res(t):
    if t not in cache:
        cache[t] = r.resolve(t)
    return cache[t]

uses = collections.Counter()
for _rec, lines in lines_from(corpus):
    for l in lines:
        t = normalise(l)
        if t:
            uses[t] += 1
total = sum(uses.values())

# what the deterministic stages already handle, and what is left to decide
todo = collections.Counter()
for term, n in uses.items():
    if res(term)["status"] == "resolved":
        continue
    q = strip_qualifiers(term)
    if q and q != term and res(q)["status"] == "resolved":
        continue
    todo[term] = n

def candidates(term):
    """Plausible targets, most conservative first."""
    out, seen = [], set()
    words = strip_qualifiers(term).split() or term.split()
    forms = []
    for i in range(len(words)):                 # drop leading words
        forms.append(" ".join(words[i:]))
    for i in range(len(words) - 1, 0, -1):      # drop trailing words
        forms.append(" ".join(words[:i]))
    for f in forms:
        if not f or f in seen:
            continue
        seen.add(f)
        a = res(f)
        if a["status"] != "resolved":
            continue
        dropped = [w for w in words if w not in f.split()]
        risky = (len(f.split()) == 1 and f in VEHICLE
                 and any(w not in VEHICLE for w in dropped))
        out.append(dict(term=f, roots=a["root_labels"],
                        closure=len(g.closure(a["roots"])[0]),
                        dropped=" ".join(dropped) or None,
                        risky=risky,
                        warning=("dropping `" + " ".join(dropped) + "` loses the food: "
                                 "`" + f + "` is a vehicle, not an ingredient")
                                 if risky else None))
        if len(out) >= 4:
            break
    return out

queue = []
for term, n in todo.most_common(TOP):
    queue.append(dict(term=term, uses=n, share=round(100 * n / total, 3),
                      candidates=candidates(term)))

spec = dict(
    version="2026-09-11",
    note=("Recipe ingredient term -> a term build/resolve.py can find. Seeded from a "
          "corpus by build/seed_ingredient_map.py; NOTHING here takes effect until an "
          "entry carries `signed_off_by`, which build/ingest.py is the only reader of.\n\n"
          "Kept separate from data/resolution-store.json on purpose. That file pins what "
          "a DINER means by a word, 53 entries carrying long arguments about allergen "
          "scope. This one records what a RECIPE WRITER means, runs to hundreds of "
          "mostly-mechanical entries, and wants a different review burden. Merging them "
          "would bury the reasoned decisions in the routine ones."),
    corpus=os.path.basename(corpus),
    corpus_lines=total,
    corpus_terms=len(uses),
    deterministic_share=round(100 * (total - sum(todo.values())) / total, 1),
    mappings=[],
    requires_signoff=queue,
)
old = {}
if os.path.exists(MAP_FILE):
    prev = json.load(open(MAP_FILE))
    spec["mappings"] = prev.get("mappings", [])
    old = {m["term"] for m in spec["mappings"]}
    spec["requires_signoff"] = [q for q in queue if q["term"] not in old]
json.dump(spec, open(MAP_FILE, "w"), indent=2)

covered = sum(q["uses"] for q in spec["requires_signoff"])
withcand = sum(1 for q in spec["requires_signoff"] if q["candidates"])
risky = sum(1 for q in spec["requires_signoff"]
            if q["candidates"] and all(c["risky"] for c in q["candidates"]))
print(f"corpus                : {os.path.basename(corpus)}  "
      f"{total:,} ingredient uses, {len(uses):,} distinct terms")
print(f"deterministic already : {spec['deterministic_share']}% of uses")
print(f"queued for sign-off   : {len(spec['requires_signoff'])} terms, {covered:,} uses "
      f"({100*covered/total:.1f}% of the corpus)")
print(f"  with a candidate    : {withcand}")
print(f"  ONLY risky candidates: {risky}  (head-noun collapses; these need a human answer)")
print(f"  no candidate at all : {len(spec['requires_signoff'])-withcand}")
print(f"\nwrote {MAP_FILE} -- signed entries: {len(spec['mappings'])}")

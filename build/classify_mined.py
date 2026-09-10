#!/usr/bin/env python3
"""Classify bridge candidates that the label-convention repair pass cannot find.

`build/repair_derives.py` keys on FoodOn's `<X> food product` -> `<X> plant` naming
convention and finds 76 bridges. This file covers what that convention misses, from
three further sources, and puts every one of them in a REVIEW QUEUE. It writes no
edges: only an entry signed in `config/mined-signoff.json` is applied, and the
traversal reads the signed list, never this file's candidates.

Why a queue and not auto-apply. The label-convention rule earns its automation from
FoodOn's own structure — the same suffix, the same organism branch, a unique source.
These three rules rest on weaker evidence: an English sentence, or a naming pattern
that is one word away from a trap. Measured precision before the guards below was
21/24; the guards exist to close that gap, and sign-off exists because a guard set
tuned on 24 examples is not a warrant for changing what a diner is told.

RULE E - definition mining (the large one)
    `data/definition-mining.json` extracts origin phrasing from FoodOn's own prose.
    Paprika's definition says it is "derived from the dried fruit of several
    varieties of Capsicum annuum L." while the class asserts nothing; the same is
    true of `pasta`, whose definition reads "unleavened dough of wheat flour" and
    which no gluten query currently reaches. 126 candidates are for classes nothing
    can reach; 102 of those are EFSA/GS1 code-list entries and are dropped.

RULE B - interior qualifier
    `<X> <qualifier> food product` -> `<X> <source>`, for the qualifiers FoodOn
    interposes (`refined`, `sweetener`, `vegetable`...). The base rule only strips
    the `food product` suffix, so `sugar maple sweetener food product` misses.

RULE D - preparation-state twin  (relation `is a`, NOT `derives from`)
    `<X> (state)` where a connected `<X>` exists and the variant never got an is_a
    to it. This is a missing subclass edge, so it is emitted as one.

Deliberately NOT implemented: product-FORM suffixes (`<X> oil`, `<X> sauce`,
`<X> syrup`). Measured 8 candidates at ~50% precision — `pancake syrup -> pancake`,
`malt syrup -> malt root` (it is barley), `feather meal -> feather`. `<X> sauce` and
`<X> syrup` name the dish, not the source, and no guard separates the two cases.
Definition mining gets `malt syrup -> barley plant` right from the prose instead.
"""
import json, re, collections

ix = json.load(open("data/index.json"))
N, E = ix["nodes"], ix["edges"]
DERIVES = "http://purl.obolibrary.org/obo/RO_0001000"
PROCESS = "http://purl.obolibrary.org/obo/BFO_0000015"
lbl  = lambda i: (N.get(i, {}) or {}).get("l") or ""
live = lambda i: not (N.get(i, {}) or {}).get("dep")

pol = json.load(open("config/relation_policy.json"))
PROP = {r["property"] for r in pol["propagating_relations"]}

parents, children = collections.defaultdict(list), collections.defaultdict(list)
src_of = collections.defaultdict(set)
for e in E:
    if e["p"] == "isa":
        parents[e["s"]].append(e["o"]); children[e["o"]].append(e["s"])
    if e["p"] in PROP:
        src_of[e["s"]].add(e["o"])
# repairs already accepted count as connectivity, or their products would be
# re-proposed here as though nothing reached them
for a in json.load(open("data/repairs-classified.json"))["auto_apply"]:
    src_of[a["product"]].add(a["source"])


def ancestors(i, cap=4000):
    seen, st = set(), [i]
    while st and len(seen) < cap:
        x = st.pop()
        for p in parents.get(x, ()):
            if p not in seen:
                seen.add(p); st.append(p)
    return seen


def subtree(root):
    seen, st = set(), [root]
    while st:
        x = st.pop()
        for c in children.get(x, ()):
            if c not in seen:
                seen.add(c); st.append(c)
    return seen


ORG_MATERIAL = next(i for i in N if lbl(i).lower() == "organism material" and live(i))
ORG_ALL = subtree(ORG_MATERIAL) | {ORG_MATERIAL}
PROC_ALL = subtree(PROCESS) | {PROCESS} if PROCESS in N else set()
KINGDOMS = {k: subtree(k) for k in children.get(ORG_MATERIAL, ())}
KINGDOMS = {k: v for k, v in KINGDOMS.items() if lbl(k).lower() != "organism piece"}

bylabel = collections.defaultdict(list)
for i in N:
    if live(i) and lbl(i):
        bylabel[lbl(i).lower()].append(i)


def branches(i):
    a = ancestors(i) | {i}
    return {k for k, m in KINGDOMS.items() if a & m}


def connected(i):
    return bool(src_of.get(i)) or any(src_of.get(a) for a in ancestors(i))


CODELIST = re.compile(r"\((efsa foodex2|gs1 gpc|us cfr|codex|langual|eurofir)\)"
                      r"|^\s*\d{4,}\s*-\s")
# "such as", "like X and Y", "e.g." -- the sentence is listing examples, so the
# first organism named is not THE origin. Caught `enzyme supplement -> pineapple
# plant`, whose definition reads "plants like pineapple and papaya".
EXAMPLE_PHRASE = re.compile(r"\b(such as|like|e\.?g\.?|including|for example|"
                            r"among (?:them|others)|and others)\b", re.I)


def guard(product, source, phrase=None):
    """Return None if the candidate is acceptable, else the guard that rejects it."""
    if not live(product) or not live(source):
        return "deprecated class"
    if CODELIST.search(lbl(product).lower()):
        return "code-list entry: an external vocabulary row, not a FoodOn food class"
    if connected(product):
        return "already reachable: the bridge would add nothing"
    if source not in ORG_ALL:
        return "source is not an organism or organism material"
    # G3 - the product must not itself be an organism. `pear tomato plant` is a
    # tomato whose NAME contains "pear"; bridging it to `pear plant` is the classic
    # lexical trap, and a plant does not derive from another plant.
    #
    # Tested on the NAME and the namespace, not on `organism material` ancestry:
    # `acorn flour` is under `flour` which is under organism material, so an
    # ancestry test rejected it and every other plant-derived material with it,
    # while `pear tomato plant` sits under NCBITaxon `Solanum lycopersicum` and
    # escaped entirely. The naming convention is the reliable signal here, and it
    # is the same one the rest of the pipeline keys on.
    if is_organism_named(product):
        return "product is itself an organism: a lexical name collision, not an origin"
    # G4 - a process has no origin. `food milling` is defined as "the process of
    # milling grain into flour", which names grain without being made of it.
    if product in PROC_ALL:
        return "product is a process class, which cannot derive from an organism"
    # G5 - example lists. Applied to the MATCHED PHRASE, not the whole definition:
    # pasta's definition ends "sometimes with other ingredients such as eggs and
    # vegetable extracts", and that `such as` is about other ingredients, not about
    # the origin clause the miner actually matched.
    if phrase and EXAMPLE_PHRASE.search(phrase):
        return "definition lists examples rather than naming one origin"
    # G1 - organism-branch compatibility, same guard as build/repair_derives.py
    pb, sb = branches(product), branches(source)
    if pb and sb and not (pb & sb):
        return "organism-branch conflict"
    return None


ORGANISM_SUFFIX = ("plant", "tree", "animal", "cultivar", "plant variety", "bush",
                   "vine", "shrub", "species", "subspecies", "breed", "cultivar group")


def is_organism_named(i):
    l = lbl(i).lower()
    return (i.rsplit("/", 1)[-1].startswith("NCBITaxon_")
            or any(l == s or l.endswith(" " + s) for s in ORGANISM_SUFFIX))


candidates = []

# ---- rule E: definition mining -------------------------------------------------
for c in json.load(open("data/definition-mining.json"))["candidates"]:
    p, s = c["class"], c["source"]
    if p not in N or s not in N:
        continue
    why = guard(p, s, c.get("phrase") or "")
    candidates.append({
        "product": p, "product_label": lbl(p),
        "source": s, "source_label": lbl(s),
        "relation": "derives from", "rule": "E: definition mining",
        "evidence": (c.get("definition") or "")[:240],
        "matched_phrase": c.get("phrase"),
        "rejected_by": why,
    })

# ---- rule B: interior qualifier ------------------------------------------------
FP = re.compile(r"^(.*) food product$")
SOURCE_SUFFIXES = ["plant", "tree", "animal", "cultivar", "plant variety",
                   "bush", "vine", "shrub"]
QUALIFIERS = ("refined", "vegetable", "sweetener", "cereal", "custard", "bakery",
              "based bakery", "pickle", "juice", "oil", "prepared", "dried",
              "canned", "fermented", "snack", "dairy", "meat", "beverage")
for i in sorted(N, key=lbl):
    if not live(i) or connected(i):
        continue
    m = FP.match(lbl(i).lower())
    if not m:
        continue
    stem = m.group(1)
    for q in QUALIFIERS:
        if not stem.endswith(" " + q):
            continue
        base = stem[: -len(q) - 1]
        cands = sorted({c for suf in SOURCE_SUFFIXES
                        for c in bylabel.get(f"{base} {suf}", [])}, key=lbl)
        cands = [c for c in cands if c != i]
        # uniqueness, same guard as the base rule: an ambiguous stem is not evidence
        ok = [c for c in cands if not guard(i, c)]
        if len(ok) == 1:
            candidates.append({
                "product": i, "product_label": lbl(i),
                "source": ok[0], "source_label": lbl(ok[0]),
                "relation": "derives from",
                "rule": f"B: `<X> {q} food product` -> `<X> <source>`",
                "evidence": f"qualifier `{q}` stripped; unique source for stem `{base}`",
                "rejected_by": None,
            })
        elif len(cands) > 1:
            candidates.append({
                "product": i, "product_label": lbl(i),
                "source": cands[0], "source_label": lbl(cands[0]),
                "relation": "derives from", "rule": f"B: `<X> {q} food product`",
                "evidence": f"stem `{base}`",
                "rejected_by": f"ambiguous: {len(cands)} candidate sources",
            })
        break

# ---- rule D: preparation-state twin (is a) -------------------------------------
PREP = re.compile(r"^(.+?)\s*\(([^)]+)\)$")
# An analog is DEFINED by not containing the thing it imitates; FoodOn models this
# with `has food substance analog`, which config/relation_policy.json already marks
# non-propagating. An is_a here would tell a cocoa-avoider that imitation chocolate
# contains cocoa. Same for a "-free" variant, which names what it excludes.
ANALOG = re.compile(r"\b(imitation|analog(?:ue)?|substitute|mock|artificial|"
                    r"free|less|without|non[- ])", re.I)
for i in sorted(N, key=lbl):
    if not live(i) or connected(i) or CODELIST.search(lbl(i).lower()):
        continue
    m = PREP.match(lbl(i).lower())
    if not m:
        continue
    base, state = m.group(1).strip(), m.group(2)
    twins = [t for t in bylabel.get(base, []) if t != i and live(t) and connected(t)]
    if len(twins) != 1:
        continue
    why = None
    if ANALOG.search(state):
        why = (f"`{state}` marks an analog or an exclusion: the variant is defined by "
               f"NOT containing what the base contains")
    candidates.append({
        "product": i, "product_label": lbl(i),
        "source": twins[0], "source_label": lbl(twins[0]),
        "relation": "is a", "rule": "D: `<X> (state)` -> `<X>`",
        "evidence": f"preparation state `{state}`; base class is already reachable",
        "rejected_by": why,
    })

# ---- impact preview ------------------------------------------------------------
# A queue entry is only reviewable if it says what it would DO. Dry-running
# `pasta food product -> wheat plant` grew a gluten query by 135 classes and pulled
# in `gluten-free pasta` and `corn pasta`, because `pasta food product` is a shape,
# not a grain. That is a decline-or-narrow decision, and a reviewer can only make it
# with the number and the conflicts in front of them.
DERIVES_ONLY = collections.defaultdict(set)
for e in E:
    if e["p"] == DERIVES:
        DERIVES_ONLY[e["s"]].add(e["o"])

FREE_OF = re.compile(r"\b(free|less|without|substitute|imitation|analog(?:ue)?)\b", re.I)


def related(a, b):
    """Same organism, or one subsumes the other."""
    return a == b or a in ancestors(b) or b in ancestors(a)


def impact(product, source):
    added = [x for x in subtree(product) | {product}
             if live(x) and not connected(x)]
    conflicts = []
    # An exclusion word only conflicts if the SOURCE does not carry it too:
    # `imitation lemon juice (dried) is_a imitation lemon juice` is perfectly sound,
    # and flagging it would train the reviewer to skim past the flags that matter.
    source_excludes = bool(FREE_OF.search(lbl(source)))
    for x in added:
        l = lbl(x)
        if FREE_OF.search(l) and not source_excludes:
            conflicts.append({"class": lbl(x),
                              "why": "names an exclusion, so the bridge would assert "
                                     "containment of the very thing it excludes"})
            continue
        for other in DERIVES_ONLY.get(x, ()):
            if not related(other, source):
                conflicts.append({"class": lbl(x),
                                  "why": f"already derives from `{lbl(other)}`, "
                                         f"not from `{lbl(source)}`"})
                break
    return len(added), conflicts[:8]


for c in candidates:
    if c["rejected_by"]:
        continue
    n, conf = impact(c["product"], c["source"])
    c["would_add_classes"] = n
    if conf:
        c["conflicts"] = conf

# ---- apply human decisions -----------------------------------------------------
try:
    SIGN = json.load(open("config/mined-signoff.json"))
except FileNotFoundError:
    SIGN = {"reviewed_by": None, "decisions": {}}
DEC = SIGN.get("decisions", {})

signed, queue, declined, rejected = [], [], [], []
for c in candidates:
    if c["rejected_by"]:
        rejected.append(c); continue
    d = DEC.get(c["product"])
    if d is None:
        queue.append(c)
    elif d.get("apply"):
        signed.append(dict(c, confidence=d.get("confidence", "medium"),
                           signed_off_by=SIGN.get("reviewed_by"),
                           rationale=d.get("rationale")))
    else:
        declined.append(dict(c, rationale=d.get("rationale")))

json.dump({"version": "2026-09-09",
           "ontology_version": ix["meta"]["version"],
           "generated_by": "build/classify_mined.py",
           "note": "Only `signed_off` is read by the traversal. Everything else is a "
                   "proposal; nothing here changes an answer until it is signed in "
                   "config/mined-signoff.json.",
           "signed_off": signed, "requires_signoff": queue,
           "declined": declined, "rejected_by_guard": rejected},
          open("data/mined-classified.json", "w"), indent=2)

byrule = collections.Counter(c["rule"].split(":")[0] for c in queue)
print(f"signed off and APPLIED : {len(signed)}")
print(f"awaiting sign-off      : {len(queue)}   by rule: {dict(byrule)}")
print(f"declined at review     : {len(declined)}")
print(f"rejected by a guard    : {len(rejected)}")
print()
byguard = collections.Counter(c["rejected_by"].split(":")[0] for c in rejected)
for g, n in byguard.most_common():
    print(f"   {n:>5}  {g}")
flagged = [c for c in queue if c.get("conflicts")]
print(f"\nawaiting sign-off  ({len(flagged)} carry a conflict a reviewer must see):")
for c in sorted(queue, key=lambda x: (-len(x.get("conflicts") or []),
                                      -x["would_add_classes"], x["product_label"])):
    mark = "!" if c.get("conflicts") else " "
    print(f" {mark} {c['product_label'][:38]:<38} --{c['relation']:<12}--> "
          f"{c['source_label'][:22]:<22} +{c['would_add_classes']:<4} [{c['rule'].split(':')[0]}]")
    for x in (c.get("conflicts") or [])[:3]:
        print(f"       conflict: {x['class'][:34]:<34} {x['why']}")

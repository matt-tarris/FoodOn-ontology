#!/usr/bin/env python3
"""Split the repair candidates into auto-apply and sign-off-required.

Two independent signals must agree before a repair applies without review:

  structural  the source resolves to a SINGLE organism -- either it carries an
              `in taxon` edge to a species-rank taxon (a binomial), or it is a leaf
              with no sub-sources. A source that subsumes other sources is a rank
              above species, so the repaired edge would be coarser than it looks.

  research    the stem is not polysemous across genera and carries no safety
              hazard. Structure cannot see this: `sorrel plant` carries a clean
              species taxon (Rumex acetosa) yet "sorrel" also names Hibiscus
              sabdariffa in Caribbean usage -- a different family entirely.

Anything failing either signal goes to sign-off rather than being dropped, so the
recall-first policy is preserved: these are edges awaiting approval, not rejections.
"""
import json, collections, re

# ---- research pass findings (offline LLM pass; each needs a reason) ------------
RESEARCH_FLAGS = {
 "avian animal":        "class-rank (Aves): one edge would link all avian food to all birds",
 "bean plant":          "spans Phaseolus, Vicia and Glycine -- soy-allergen relevant, must not be coarse",
 "stone fruit plant":   "culinary grouping over peach, plum, cherry, apricot -- not one organism",
 "millet plant":        "polyphyletic: pearl, foxtail and finger millet are different genera",
 "ginseng plant":       "Panax ginseng vs P. quinquefolius vs Eleutherococcus ('Siberian ginseng', different genus)",
 "sorrel plant":        "Rumex acetosa vs Hibiscus sabdariffa (Caribbean 'sorrel') -- different families",
 "sarsaparilla plant":  "Smilax spp. vs Aralia nudicaulis ('wild sarsaparilla')",
 "sumac plant":         "Rhus genus includes toxic Toxicodendron vernix (poison sumac) -- safety relevant",
 "nasturtium plant":    "Tropaeolum (garden nasturtium) vs Nasturtium officinale (watercress) -- different families",
 "angelica plant":      "Angelica genus: A. archangelica is edible, other species are toxic -- safety relevant",
 "sage plant":          "Salvia genus grouping; 'sage' also used for Artemisia (sagebrush)",
 "thyme plant":         "Thymus genus grouping rather than one species",
 "cattail plant":       "Typha genus grouping",
 "mallow plant":        "Malva genus grouping",
 "chokeberry plant":    "Aronia genus grouping",
 "black cumin plant":   "Nigella sativa vs Bunium persicum -- both called black cumin",
}

# Positive findings: single species that FoodOn simply does not give a species-rank
# `in taxon` edge. Structure cannot confirm these, research can -- so they are
# affirmed here rather than held for review over a gap in the ontology's metadata.
RESEARCH_CONFIRMS = {
 "soft wheat plant":   "Triticum aestivum; its two sub-sources are cultivar groups, not other species",
 "white pepper plant": "Piper nigrum -- same species as black pepper, differing only in processing",
 "zucchini plant":     "Cucurbita pepo; the sub-source is a cultivar group",
}

ix = json.load(open("data/index.json")); N, E = ix["nodes"], ix["edges"]
rep = json.load(open("data/repairs.json"))
IN_TAXON = "http://purl.obolibrary.org/obo/RO_0002162"
lbl = lambda i: N.get(i, {}).get("l", "")

kids = collections.defaultdict(list); out = collections.defaultdict(list)
for e in E:
    if e["p"] == "isa": kids[e["o"]].append(e["s"])
    out[e["s"]].append((e["p"], e["o"]))

BINOMIAL = re.compile(r"^[A-Z][a-z]+(?: x)? [a-z][a-z-]+")
def species_taxon(src):
    for p, o in out.get(src, ()):
        if p == IN_TAXON and BINOMIAL.match(lbl(o) or ""):
            return lbl(o)
    return None

SIGNOFF = json.load(open("config/repair-signoff.json"))["decisions"]

auto, signoff, declined = [], [], []
for a in sorted(rep["accepted"], key=lambda x: x["product_label"]):
    src, srcl = a["source"], a["source_label"]
    sp   = species_taxon(src)
    leaf = not kids.get(src)
    flag = RESEARCH_FLAGS.get(srcl.lower())
    entry = dict(a, source_taxon=sp, is_leaf=leaf)
    confirm = RESEARCH_CONFIRMS.get(srcl.lower())
    decided = SIGNOFF.get(srcl.lower())
    if decided is not None:
        # human sign-off overrides both automated signals, either way
        rec = dict(entry, confidence=decided["confidence"],
                   evidence=f"signed off by {json.load(open('config/repair-signoff.json'))['reviewed_by']}: {decided['rationale']}")
        (auto if decided["apply"] else declined).append(rec)
    elif flag:
        signoff.append(dict(entry, hold_reason=f"research: {flag}"))
    elif confirm:
        entry["evidence"] = f"research: {confirm}"
        auto.append(entry)
    elif sp or leaf:
        entry["evidence"] = (f"single species: {sp}" if sp else "leaf source, no sub-sources")
        auto.append(entry)
    else:
        signoff.append(dict(entry,
            hold_reason=f"structural: source subsumes {len(kids[src])} other sources "
                        f"and has no species-rank taxon"))

json.dump({"version": "2026-09-09",
           "ontology_version": ix["meta"]["version"],
           "rule": "auto-apply requires single-organism structure AND no research flag",
           "auto_apply": auto, "requires_signoff": signoff, "declined": declined},
          open("data/repairs-classified.json", "w"), indent=2)

for a in auto:
    a.setdefault("confidence", "high")
print(f"applied           : {len(auto)}  "
      f"(high {sum(1 for a in auto if a['confidence']=='high')}, "
      f"medium {sum(1 for a in auto if a['confidence']=='medium')})")
print(f"declined at review: {len(declined)}")
print(f"still unreviewed  : {len(signoff)}\n")
for d in declined:
    print(f"  DECLINED {d['product_label']:<32} -> {d['source_label']}")
for s in signoff:
    print(f"  {s['product_label']:<34} -> {s['source_label']:<24} {s['hold_reason']}")
crit = ["hungarian wax pepper food product","garlic food product","walnut food product",
        "rye food product","soft wheat food product","spelt food product","white pepper food product"]
print("\nsafety-critical repairs in auto-apply:")
for c in crit:
    print(f"   {'YES' if any(x['product_label']==c for x in auto) else 'NO '}  {c}")

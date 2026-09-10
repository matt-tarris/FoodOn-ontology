#!/usr/bin/env python3
"""Measure what a definition-mining pass could recover.

Found via the allergen coverage test: FoodOn parents processed ingredients by
FUNCTION (`tahini is_a condiment`, `casein is_a protein extract`) and asserts no
source at all. Label convention cannot fix this -- "tahini" does not contain
"sesame" -- but the definition text often states the source outright:

    tahini  "A condiment made from toasted ground hulled sesame."
    casein  "...the predominant protein of milk."

This script only MEASURES the opportunity. It writes no edges.
"""
import json, re, collections

ix = json.load(open("data/index.json")); N, E = ix["nodes"], ix["edges"]
DERIVES = "http://purl.obolibrary.org/obo/RO_0001000"
lbl  = lambda i: N.get(i, {}).get("l", "") or ""
live = lambda i: not N.get(i, {}).get("dep")

has_source = {e["s"] for e in E if e["p"] == DERIVES}

# source vocabulary: FoodOn's own organism/product class names, plus their synonyms
# Source vocabulary must be ORGANISMS, not arbitrary nouns. An earlier version
# admitted any single-word label, which turned "lake", "water" and "Niger" (from
# "aspergillus niger") into sources. Only `<X> plant|tree|animal` classes qualify,
# plus their synonyms, and only where X is not itself a chemical or generic noun.
GENERIC = {"food","plant","animal","water","starch","pectin","hemicellulose","sugar",
           "protein","oil","fat","acid","fibre","fiber","juice","extract",
           "powder","flour","seed","fruit","leaf","root","whole","other","material"}
source_terms = {}
for i in N:
    if not live(i): continue
    l = lbl(i).lower()
    m = re.match(r"^(.*) (?:plant|tree|animal)$", l)
    if m and len(m.group(1)) >= 3 and m.group(1) not in GENERIC:
        source_terms.setdefault(m.group(1), i)
        for syn in N[i].get("syn", []):
            sl = syn.lower().strip()
            if len(sl) >= 3 and sl not in GENERIC:
                source_terms.setdefault(sl, i)

CUE = re.compile(
    r"\b(?:made|derived|obtained|produced|prepared|extracted|pressed|milled|ground|rendered)"
    r"\s+(?:in\s+part\s+)?from\s+(?:the\s+)?([a-z][a-z \-']{2,60})", re.I)
# bounded at a word boundary: an earlier 40-char cap truncated "material entity"
# to "mate", which then matched yerba mate across ~300 CDNO concentration classes
CUE2 = re.compile(r"\bthe (?:predominant |principal |main )?[a-z]+ of ((?:[a-z][a-z\-']*)(?: [a-z][a-z\-']*){0,3})\b", re.I)
STOP = {"which","that","this","these","those","a","an","the","it","them","other","various","any"}

hits, unmatched = [], collections.Counter()
for i in N:
    if not live(i): continue
    # CDNO models "concentration of X in material entity"; these are measurements,
    # not foods, and can never be a derivation target
    if N[i].get("ns") in ("CDNO", "CHEBI", "PATO", "OBI", "IAO", "BFO"): continue
    d = N[i].get("def")
    if not d: continue
    if i in has_source: continue                 # already has a source
    phrase = None
    for pat in (CUE, CUE2):
        m = pat.search(d)
        if m: phrase = m.group(1).lower().strip(" .,;"); break
    if not phrase: continue
    toks = [t for t in re.findall(r"[a-z']+", phrase) if t not in STOP]
    src = None
    # longest matching span wins, so "sweet potato" beats "potato"
    for n in range(min(4, len(toks)), 0, -1):
        for st in range(len(toks) - n + 1):
            cand = " ".join(toks[st:st+n])
            if cand in source_terms:
                src = source_terms[cand]; break
        if src: break
    if src and src != i:
        hits.append({"class": i, "label": lbl(i), "source": src,
                     "source_label": lbl(src), "phrase": phrase[:50],
                     "definition": d[:150]})
    elif phrase:
        unmatched[phrase[:40]] += 1

json.dump({"version": "2026-09-09", "status": "MEASUREMENT ONLY - writes no edges",
           "candidates": sorted(hits, key=lambda h: h["label"])},
          open("data/definition-mining.json", "w"), indent=2)

defs = sum(1 for i in N if live(i) and N[i].get("def"))
nosrc = sum(1 for i in N if live(i) and N[i].get("def") and i not in has_source)
print(f"live classes with a definition        : {defs:,}")
print(f"  ...of those, with no derives-from   : {nosrc:,}")
print(f"  ...where the definition names a source we can resolve : {len(hits):,}")
print(f"  ...cue phrase found but source unresolved             : {sum(unmatched.values()):,}")
print("\nsample recoveries:")
for h in hits[:18]:
    print(f"  {h['label']:<34} -> {h['source_label']:<26} \"{h['phrase']}\"")

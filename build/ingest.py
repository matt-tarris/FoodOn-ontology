#!/usr/bin/env python3
"""Recipe ingredient line -> FoodOn class, deterministically or not at all.

Measured on 5,000 real recipes (54,123 ingredient lines, 10,383 distinct terms after
normalisation):

    normalise  quantity, unit, parenthetical, preparation   48.4% of uses
  + qualifiers grade and state words FoodOn does not label   64.1%
  + head noun  the last word of whatever is left            89.7%  -- REMOVED

THE HEAD-NOUN STAGE IS DELIBERATELY ABSENT, and it is the only stage that would have
taken this past 90%. It reached that number by dropping the modifier that carried the
food: `chili oil` -> oil, `ancho chile powder` -> powder, `goat cheese` -> cheese,
`squeezed lemon juice` -> juice. 1,921 ingredient uses collapse that way. For a filter
whose job is to keep food off a plate, that trade is the wrong way round -- an
unresolved ingredient QUARANTINES a recipe, and a wrongly resolved one PASSES it. 64%
that abstains is worth more than 90% that guesses.

What is left is the judgement queue: 8,894 terms, 36% of uses, headed by `red pepper
flakes`, `flaky sea salt`, `parmesan`, `dijon mustard`. Those are decisions, not
lookups, and they go in config/ingredient-map.json where a person signs them off.
"""
import json, re, os, ast, collections, sys, unicodedata

sys.path.insert(0, "build")

MAP_FILE = "config/ingredient-map.json"

FRAC = r"¼-¾⅐-⅞"
UNIT = (r"tsp|teaspoons?|tbsp|tablespoons?|cups?|oz|ounces?|lb|lbs|pounds?|g|gr|kg|ml|l|"
        r"liters?|litres?|quarts?|pints?|gallons?|cloves?|sprigs?|stalks?|heads?|"
        r"bunch(?:es)?|cans?|jars?|packages?|pkg|pinch(?:es)?|dash(?:es)?|slices?|"
        r"pieces?|sticks?|ears?|fillets?|large|medium|small|whole|scant|generous")
# preparation: how it was cut or treated. Never changes what the ingredient IS.
PREP = (r"fresh(?:ly)?|dried|ground|chopped|minced|sliced|diced|grated|shredded|crushed|"
        r"melted|softened|toasted|roasted|peeled|seeded|cored|halved|quartered|trimmed|"
        r"rinsed|drained|divided|julienned|cubed|stemmed|pitted|zested|juiced|beaten|"
        r"room temperature|cold|warm|hot|thinly|roughly|finely|coarsely|lightly|well|"
        r"plus more|for serving|for garnish|optional|such as|preferably|about|packed|sifted")
# culinary QUALIFIERS: grade, seasoning state, fat level, colour, provenance. FoodOn does
# not carry these in its labels, and none of them changes the avoidance answer: kosher
# salt is salt. `sea` is here too -- FoodOn has no `sea salt` class.
QUAL = (r"kosher|unsalted|salted|extra-?virgin|virgin|all-?purpose|granulated|powdered|"
        r"confectioners?|superfine|caster|light|dark|pure|unsweetened|sweetened|"
        r"low-?sodium|reduced-?sodium|no-?salt-?added|nonstick|flaky|fine|coarse|table|"
        r"sea|full-?fat|low-?fat|nonfat|skim|heavy|double|single|chilled|boneless|"
        r"skinless|bone-?in|lean|raw|organic|free-?range|unbleached|bleached|instant|"
        r"quick-?cooking|old-?fashioned|store-?bought|homemade|good|best|quality|plain|"
        r"natural|creamy|crunchy|smooth|seasoned|unseasoned|dry|wet|day-?old|ripe|unripe")
STOP = r"of|and|the|a|an|into|for|with|to|plus|each|any|more"
# `or` is NOT a stop word. Removing it welded alternatives together: "sherry vinegar or
# red wine vinegar" became `sherry vinegar red wine vinegar`, "kosher salt or sea salt"
# became `kosher salt sea salt`. Alternatives are split instead, and BOTH are returned:
# the cook may use either, so an avoidance filter has to consider either.
ALT = re.compile(r"\bor\b|\bplus\b|/")

_qual_re = re.compile(r"\b(?:" + QUAL + r")\b")


def normalise(line):
    """A cookbook line down to a food term. Deterministic, and lossy on purpose."""
    s = str(line).lower()
    # Fold accents rather than delete them. The first cut stripped every non-ASCII
    # character, which turned jalape\u00f1o into `jalape o`, cr\u00e8me fra\u00eeche into
    # `cr me fra che` and chiles de \u00e1rbol into `chiles de rbol` -- three real
    # ingredients arriving in the review queue as nonsense that no reviewer could map.
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"\([^)]*\)", " ", s)                       # (about 3 lb. total)
    s = re.sub(r"^[\s\d" + FRAC + r"/\.\-–]+", "", s)  # 1 1/2
    s = s.split(",")[0]                                     # ", finely chopped"
    # Units ANYWHERE, not only leading. "2 Tbsp. kosher salt, plus 1 tsp" leaves a
    # second `tsp` mid-string once the comma clause is cut, and `tsp kosher salt`
    # then resolves to nothing and arrives in the review queue looking like a new
    # ingredient rather than one already handled.
    s = re.sub(r"\b(?:" + UNIT + r")\b\.?", " ", s)
    s = re.sub(r"[\s\d" + FRAC + r"/]+", " ", s)
    # A hyphenated compound goes WHOLE when either half is a preparation word.
    # Stripping only the matching half left the other one welded to the food:
    # `oil-packed anchovies` became `oil anchovies`, `fire-roasted tomatoes` became
    # `fire tomatoes`, `ice-cold water` became `ice water`. `half-and-half` and
    # `bread-and-butter pickles` survive, because neither half of either is a
    # preparation word -- which is why the rule tests the parts rather than the hyphen.
    s = re.sub(r"\b[a-z]+-(?:" + PREP + r")\b", " ", s)
    s = re.sub(r"\b(?:" + PREP + r")-[a-z]+\b", " ", s)
    for _ in range(4):
        s = re.sub(r"\b(?:" + PREP + r")\b", " ", s)
    # Stop words, but NOT inside a hyphenated compound: `half-and-half` and
    # `bread-and-butter pickles` are food names, and stripping the `and` out of them
    # left `half -half`, which names nothing. The lookarounds exclude a hyphen on
    # either side, so a free-standing `and` still goes.
    s = re.sub(r"(?<![-\w])(?:" + STOP + r")(?![-\w])", " ", s)
    s = re.sub(r"[^a-z\s\-']", " ", s)
    # A hyphenated compound loses one half to the preparation list and leaves the
    # hyphen: `oil-packed anchovies` becomes `oil- anchovies`, `fire-roasted tomatoes`
    # becomes `fire- tomatoes`, `half-and-half` becomes `half- -half`. 251 terms and 391
    # uses arrived in the review queue looking like new ingredients. Same defect as the
    # one fixed in strip_qualifiers; this is the other stripping pass.
    s = re.sub(r"(?:^|\s)-+(?:\s|$)", " ", s)
    s = re.sub(r"(\w)-+(\s|$)", r"\1\2", s)
    return re.sub(r"\s+", " ", s).strip()


def terms(line):
    """One line may name more than one ingredient. Returns every alternative.

    "sherry vinegar or red wine vinegar" is two, and a filter must consider both --
    the cook picks one and the diner does not know which. Recall-first, the same rule
    the traversal uses.
    """
    raw = str(line).split(",")[0]
    parts = [p for p in ALT.split(raw) if p and p.strip()]
    out = []
    for p in parts:
        t = normalise(p)
        if t and t not in out:
            out.append(t)
    return out or ([normalise(line)] if normalise(line) else [])


def strip_qualifiers(term):
    """Grade and state words off, repeatedly -- `fine flaky sea salt` needs three."""
    prev = None
    while prev != term:
        prev = term
        term = _qual_re.sub(" ", term)
        # a hyphenated qualifier loses both halves and leaves the hyphen behind:
        # `good-quality` -> ` - `, and `loaf - sturdy white bread` matches nothing
        term = re.sub(r"(?:^|\s)-+(?:\s|$)", " ", term)
        term = re.sub(r"\s+", " ", term).strip(" -")
    return term


def load_map(path=MAP_FILE):
    """ONLY signed entries. A proposal is not a decision, and an ingestion pipeline
    that silently applied its own suggestions would make the review theatre."""
    try:
        spec = json.load(open(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {e["term"]: e for e in spec.get("mappings", []) if e.get("signed_off_by")}


class Ingestor:
    def __init__(self, resolver=None, mapping=None):
        from resolve import Resolver
        self.r = resolver or Resolver()
        self.map = load_map() if mapping is None else mapping
        self._cache = {}

    def _resolve(self, term):
        if term not in self._cache:
            self._cache[term] = self.r.resolve(term)
        return self._cache[term]

    def line(self, raw):
        """{raw, term, stage, status, roots, root_labels}.

        `status` is resolved | unresolved | ambiguous. There is no fourth outcome and
        no best guess: a caller that cannot tell "I do not know" from "it is fine" has
        no way to be safe.
        """
        term = normalise(raw)
        out = dict(raw=raw, term=term, stage=None, status="unresolved",
                   roots=[], root_labels=[])
        if not term:
            out["stage"] = "empty"
            return out
        # 1. a signed human decision always wins
        m = self.map.get(term) or self.map.get(strip_qualifiers(term))
        if m:
            # An id chosen off the shortlist is used AS IS. Re-resolving its label
            # would put the resolver's scoring back in the path and could land
            # somewhere else -- the point of choosing a class is that the choice sticks.
            if m.get("maps_to_iri"):
                return dict(out, stage="signed map", status="resolved",
                            term=m.get("maps_to") or m["maps_to_iri"],
                            roots=[m["maps_to_iri"]],
                            root_labels=m.get("root_labels") or [m.get("maps_to")])
            res = self._resolve(m["maps_to"])
            if res["status"] == "resolved":
                return dict(out, stage="signed map", status="resolved",
                            term=m["maps_to"], roots=res["roots"],
                            root_labels=res["root_labels"])
        # 2. as normalised
        res = self._resolve(term)
        if res["status"] == "resolved":
            return dict(out, stage="normalised", status="resolved",
                        roots=res["roots"], root_labels=res["root_labels"])
        # 3. minus culinary qualifiers
        q = strip_qualifiers(term)
        if q and q != term:
            res2 = self._resolve(q)
            if res2["status"] == "resolved":
                return dict(out, stage="qualifier-stripped", status="resolved",
                            term=q, roots=res2["roots"], root_labels=res2["root_labels"])
        # 4. nothing. NOT a head-noun guess -- see the module docstring.
        return dict(out, status=res.get("status", "unresolved"), stage="unresolved")

    def recipe(self, lines):
        """A recipe is only as trustworthy as its least-known ingredient."""
        got = [self.line(x) for x in lines]
        unknown = [g for g in got if g["status"] != "resolved"]
        return dict(ingredients=got, resolved=len(got) - len(unknown),
                    unresolved=[g["raw"] for g in unknown],
                    usable=not unknown)


def lines_from(path):
    """Ingredient lines out of a recipe export, whatever shape it arrived in."""
    recs = json.load(open(path))
    if isinstance(recs, dict):
        recs = recs.get("recipes") or next(iter(recs.values()))
    for rec in recs:
        out = []
        for ing in rec.get("ingredients") or []:
            v = ing.get("name") if isinstance(ing, dict) else ing
            if isinstance(v, str) and v.startswith("["):
                try:
                    out += [str(x) for x in ast.literal_eval(v)]
                    continue
                except (ValueError, SyntaxError):
                    pass
            if v:
                out.append(str(v))
        yield rec, out

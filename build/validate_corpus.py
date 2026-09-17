#!/usr/bin/env python3
"""Validate the mapping layer against a corpus this project did not curate.

Two questions, and only the second is new:

  coverage   what fraction of ingredient lines resolve to a FoodOn class, and what is
             in the long tail that does not
  oracle     where the source declares which allergens a product contains, does our
             avoidance traversal agree with the label

The oracle is the point. A corpus of our own choosing can only tell us what we failed
to map; a corpus that carries allergen labels can tell us what we got WRONG, which is
the thing no amount of internal review surfaces.

The distinction that makes the oracle honest:

  a label says milk, we find no dairy ingredient, and every ingredient resolved
      -> a real traversal failure. Something that should reach milk does not.
  a label says milk, we find no dairy ingredient, and something did not resolve
      -> explained by the coverage gap we already know about. Not a traversal claim.

Reporting the second as a traversal failure would overstate the problem, and reporting
it as nothing would hide it, so they are counted separately and both are printed.

The reverse direction -- we find an allergen the label omits -- is reported but weighted
lower on purpose. Open Food Facts allergen tags are contributor-entered and frequently
incomplete, so our finding an allergen the label misses is as likely to be the label's
fault as ours. It is a lead, not a defect.

  python3 build/validate_corpus.py file /path/to/recipes.json --limit 500
  python3 build/validate_corpus.py themealdb --limit 200
  python3 build/validate_corpus.py openfoodfacts --limit 300 --category en:biscuits

Responses are cached under data/validation-cache/ so a run is repeatable and a second
run costs the remote service nothing.
"""
import argparse, collections, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import ingest                                                    # noqa: E402
from resolve import Resolver                                     # noqa: E402

CACHE = "data/validation-cache"
UA = "FoodOnAvoidanceValidator/1.0"        # no contact details: this identifies the
                                           # tool, and the user's address is not the
                                           # tool's to hand to a third party

# Open Food Facts allergen tag -> the term our resolver answers to. Every one of these
# was checked to resolve before being listed; a tag whose term stops resolving shows up
# as "cannot test" in the report rather than as silent agreement.
ALLERGENS = {
    "en:milk": "milk",
    "en:gluten": "gluten",
    "en:eggs": "egg",
    "en:nuts": "tree nut",
    "en:peanuts": "peanut",
    "en:soybeans": "soybean",
    "en:fish": "fish",
    "en:crustaceans": "crustacean",
    "en:molluscs": "mollusc",
    "en:celery": "celery",
    "en:mustard": "mustard",
    "en:sesame-seeds": "sesame",
    "en:sulphur-dioxide-and-sulphites": "sulfite",
    "en:lupin": "lupin",
}


def fetch(url, cache_key):
    """GET with a cache. One second between live calls: these are free services."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._-]", "_", cache_key) + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    json.dump(body, open(path, "w"))
    time.sleep(1.0)
    return body


# ---- sources -----------------------------------------------------------------------
# Each yields (identifier, title, [ingredient lines], {labelled allergen tags} or None).
# None means the source does not label allergens, so only coverage can be reported.

def from_file(path, limit):
    for i, (rec, lines) in enumerate(ingest.lines_from(path)):
        if i >= limit:
            return
        yield rec.get("recipe_id") or str(i), rec.get("title", ""), lines, None


def from_themealdb(limit, area=None):
    """Free, no key, ~669 meals -- but faceted by cuisine, which is the whole reason to
    use it. A Western corpus cannot tell us whether gochujang or asafoetida resolve."""
    areas = [area] if area else [
        a["strArea"] for a in fetch(
            "https://www.themealdb.com/api/json/v1/1/list.php?a=list",
            "themealdb-areas")["meals"]]
    n = 0
    for ar in areas:
        q = urllib.parse.quote(ar)
        meals = fetch(f"https://www.themealdb.com/api/json/v1/1/filter.php?a={q}",
                      f"themealdb-area-{ar}").get("meals") or []
        for m in meals:
            if n >= limit:
                return
            full = fetch(
                "https://www.themealdb.com/api/json/v1/1/lookup.php?i=" + m["idMeal"],
                f"themealdb-meal-{m['idMeal']}")["meals"][0]
            lines = []
            for k in range(1, 21):
                ing = (full.get(f"strIngredient{k}") or "").strip()
                mea = (full.get(f"strMeasure{k}") or "").strip()
                if ing:
                    lines.append(f"{mea} {ing}".strip())
            n += 1
            yield full["idMeal"], f"{full['strMeal']} ({ar})", lines, None


def from_openfoodfacts(limit, category=None):
    """4M+ products under ODbL, carrying label ingredient lists AND allergen tags.

    Packaged food is where this project's known worst gap lives -- soy lecithin, whey
    protein concentrate, modified starch: words that barely occur in home recipes and
    occur on nearly every wrapper.
    """
    fields = ("code,product_name,ingredients_text_en,ingredients_text,"
              "allergens_tags,categories_tags")
    n, page = 0, 1
    while n < limit:
        url = ("https://world.openfoodfacts.org/api/v2/search"
               f"?fields={fields}&page_size=100&page={page}&countries_tags=en:united-states")
        if category:
            url += "&categories_tags=" + urllib.parse.quote(category)
        body = fetch(url, f"off-{category or 'all'}-p{page}")
        prods = body.get("products") or []
        if not prods:
            return
        for p in prods:
            text = p.get("ingredients_text_en") or p.get("ingredients_text") or ""
            if not text.strip():
                continue                       # nothing to map; not a failure to report
            if n >= limit:
                return
            n += 1
            yield (p.get("code", ""), p.get("product_name", ""),
                   split_label(text), set(p.get("allergens_tags") or []))
        page += 1


def verdict(iris, complete, labels, closures):
    """Classify one item against its own allergen labels.

    Pulled out of the run loop so it can be tested without a network, a corpus, or the
    ontology: the classification is the part with a rule in it, and the rule -- that a
    miss only counts when everything resolved -- is the one thing here worth a test.

    Returns {tag: "agree" | "miss_real" | "miss_explained" | "over"}, omitting tags the
    item neither declares nor reaches.
    """
    out = {}
    for tag, clo in closures.items():
        found = bool(iris & clo)
        said = tag in labels
        if said and found:
            out[tag] = "agree"
        elif said:
            out[tag] = "miss_real" if complete else "miss_explained"
        elif found:
            out[tag] = "over"
    return out


def split_label(text):
    """A label is one run-on string, not lines. Split it into nameable things.

    Sub-ingredients in brackets are split out rather than kept with their parent:
    "chocolate (sugar, cocoa butter, milk)" should contribute milk on its own, which is
    exactly the containment the parent name hides.
    """
    text = re.sub(r"\b(?:contains|may contain|ingredients?)\b\s*:?", " ",
                  text, flags=re.I)
    parts = re.split(r"[,;()\[\]*]+|\.\s", text)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip(" .:-•")
        if 1 < len(p) <= 60:
            out.append(p)
    return out


# ---- the run -----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["file", "themealdb", "openfoodfacts"])
    ap.add_argument("path", nargs="?", help="for source=file")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--area", help="themealdb cuisine, e.g. Japanese")
    ap.add_argument("--category", help="openfoodfacts category tag")
    ap.add_argument("--tail", type=int, default=25)
    ap.add_argument("--json", help="write the full report here")
    a = ap.parse_args()

    ing = ingest.Ingestor()
    R = Resolver()
    G = R.g

    closures, untestable = {}, []
    for tag, term in ALLERGENS.items():
        r = R.resolve(term)
        if r.get("status") != "resolved" or not r.get("roots"):
            untestable.append((tag, term))
            continue
        closures[tag] = set(G.closure(r["roots"])[0])

    if a.source == "file":
        if not a.path:
            ap.error("source=file needs a path")
        items = from_file(a.path, a.limit)
    elif a.source == "themealdb":
        items = from_themealdb(a.limit, a.area)
    else:
        items = from_openfoodfacts(a.limit, a.category)

    tail = collections.Counter()
    n_items = n_lines = n_res = n_complete = 0
    labelled_items = 0
    # per allergen: agree / miss_real / miss_explained / over
    score = {t: collections.Counter() for t in ALLERGENS}
    misses, overs = [], []

    for ident, title, lines, labels in items:
        if not lines:
            continue
        n_items += 1
        iris, complete = set(), True
        for L in lines:
            n_lines += 1
            r = ing.line(L)
            if r["status"] == "resolved":
                n_res += 1
                iris.update(r.get("roots") or ())
            else:
                complete = False
                tail[(r.get("term") or r["raw"]).strip().lower()[:44]] += 1
        n_complete += complete

        if labels is None:
            continue
        labelled_items += 1
        for tag, v in verdict(iris, complete, labels, closures).items():
            score[tag][v] += 1
            if v == "miss_real":
                misses.append({"id": ident, "title": title, "allergen": tag,
                               "ingredients": lines[:14]})
            elif v == "over":
                overs.append({"id": ident, "title": title, "allergen": tag})

    # ---- report --------------------------------------------------------------------
    src = a.path if a.source == "file" else a.source
    print(f"\n  source            {src}"
          f"{'  area=' + a.area if a.area else ''}"
          f"{'  category=' + a.category if a.category else ''}")
    print(f"  items             {n_items:,}")
    print(f"  ingredient lines  {n_lines:,}")
    if n_lines:
        print(f"  lines resolved    {n_res:,}  ({100*n_res/n_lines:.1f}%)")
        print(f"  fully mapped      {n_complete:,}  ({100*n_complete/n_items:.1f}%)"
              "   <- the number that matters: one unmapped ingredient and the item"
              " cannot be cleared")

    if tail:
        print(f"\n  unresolved long tail  ({len(tail):,} distinct)")
        for t, c in tail.most_common(a.tail):
            print(f"    {c:5}  {t}")

    if untestable:
        print("\n  allergens that CANNOT be tested (term no longer resolves):")
        for tag, term in untestable:
            print(f"    {tag:36} {term}")

    if labelled_items:
        print(f"\n  oracle: our verdict vs the source's own allergen labels"
              f"  ({labelled_items:,} labelled items)")
        print(f"    {'allergen':34} {'agree':>6} {'MISSED':>7} {'(unmapped)':>11}"
              f" {'we-say-more':>12}")
        for tag in ALLERGENS:
            s = score[tag]
            if not sum(s.values()):
                continue
            print(f"    {tag:34} {s['agree']:6} {s['miss_real']:7}"
                  f" {s['miss_explained']:11} {s['over']:12}")
        print("\n    MISSED      the label declares it, every ingredient resolved, and"
              " the traversal still\n                did not reach it. These are real"
              " defects -- start here.")
        print("    (unmapped)  the label declares it but an ingredient did not resolve."
              " Explained by\n                the coverage gap, not a traversal claim.")
        print("    we-say-more we reach it and the label does not. Open Food Facts"
              " allergen tags are\n                contributor-entered and often"
              " incomplete, so these are leads, not defects.")

        if misses:
            print(f"\n  the {min(len(misses), 10)} of {len(misses)} real misses to look"
                  " at first")
            for m in misses[:10]:
                print(f"    [{m['allergen']}] {m['title'] or m['id']}")
                print(f"        {', '.join(m['ingredients'][:8])}")

    if a.json:
        json.dump({"source": src, "items": n_items, "lines": n_lines,
                   "resolved": n_res, "complete": n_complete,
                   "tail": tail.most_common(500),
                   "score": {k: dict(v) for k, v in score.items()},
                   "misses": misses, "overs": overs[:500],
                   "untestable": untestable},
                  open(a.json, "w"), indent=2)
        print(f"\n  report -> {a.json}")
    print()


if __name__ == "__main__":
    main()

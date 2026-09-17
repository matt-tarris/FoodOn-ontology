#!/usr/bin/env python3
"""Put a term the validation harness found into the sign-off queue.

    python3 build/queue_terms.py --source openfoodfacts \
        "flax seeds=linseed:FoodOn carries this as flaxseed, reached by its synonym"

The harness reads corpora this project did not curate, so it finds terms the seed
corpus never contained. Those belong in the same queue as everything else -- reviewed
one at a time, against a shortlist, by a person -- and not in a side channel that grows
its own rules.

Two things are recorded that a seed-corpus entry does not carry:

  source   which corpus produced it. `uses` from Open Food Facts is not comparable with
           `uses` from the 5,000 recipes, and a reviewer reading a count needs to know
           which population it is out of.
  note     why this term was proposed for that one. These arrive singly, out of a
           specific finding, and the finding is the most useful thing on the screen.

A proposal must RESOLVE or it is not written. The model proposes a term and the
resolver has to find it; a proposal naming something FoodOn does not have is a refusal
to record, not a suggestion to show someone.
"""
import argparse, json, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import MAP_FILE, strip_qualifiers, normalise      # noqa: E402
from resolve import Resolver                                  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="+",
                    help="term[=proposed[:note]] -- the term as the map is keyed, "
                         "normalised and qualifier-stripped")
    ap.add_argument("--source", required=True, help="which corpus found it")
    ap.add_argument("--uses", type=int, default=0, help="occurrences in that corpus")
    a = ap.parse_args()

    spec = json.load(open(MAP_FILE))
    queue = spec.setdefault("requires_signoff", [])
    decided = ({m["term"] for m in spec.get("mappings", [])}
               | {d["term"] for d in spec.get("declined", [])})
    queued = {e["term"] for e in queue}

    R = Resolver()
    G = R.g
    added = skipped = refused = 0

    for spec_str in a.terms:
        term, _, rest = spec_str.partition("=")
        proposed, _, note = rest.partition(":")
        term = strip_qualifiers(normalise(term)) or term.strip().lower()
        if term in decided:
            print(f"  skip     {term}  already decided")
            skipped += 1
            continue
        if term in queued:
            print(f"  skip     {term}  already queued")
            skipped += 1
            continue

        entry = {"term": term, "uses": a.uses, "source": a.source}
        if proposed:
            r = R.resolve(proposed)
            if r.get("status") != "resolved" or not r.get("roots"):
                # the contract: a proposal the resolver cannot find is not a proposal
                print(f"  REFUSED  {term} -> {proposed!r} does not resolve; queued bare")
                refused += 1
            else:
                entry.update(proposed=proposed,
                             proposed_by="Claude (validation harness)",
                             proposed_roots=r.get("root_labels") or [],
                             proposed_closure=len(G.closure(r["roots"])[0]),
                             proposed_note=note.strip() or None)
        queue.append(entry)
        queued.add(term)
        added += 1
        print(f"  queued   {term}"
              + (f"  -> {proposed} ({entry.get('proposed_closure')} classes)"
                 if entry.get("proposed") else "  (no proposal)"))

    json.dump(spec, open(MAP_FILE, "w"), indent=2)
    print(f"\n{added} queued, {skipped} skipped, {refused} proposals refused. "
          f"Queue is now {len(queue)}.")
    print("Run build/shortlist_ingredients.py to attach the class shortlists.")


if __name__ == "__main__":
    main()

# One-off discovery scripts

These produced the findings in `audit/01-structural-audit.md` and are kept as its
provenance, not as pipeline. Nothing in the build or the tests calls them, and they
are not expected to run again unless a FoodOn release changes shape enough to be
worth re-auditing.

| script | what it established |
|---|---|
| `audit_properties.py` | the object-property inventory that became `config/relation_policy.json` — 32 properties, each needing a direction ruling |
| `audit_reconcile.py` | that obographs silently drops ~10% of restrictions (F2), including 449 `derives from` — which is why extraction goes through SPARQL instead |
| `audit_naming.py` | FoodOn's label conventions, which the repair rule and the mined-bridge guards both key on |
| `probe.py` | how the spec's motivating cases actually connect, which is how F6 (paprika has no `derives from` at all) was found |

They read `data/index.json` and `data/foodon-asserted.obo.json` and write nothing.
Run from the project root, e.g. `python3 build/audit/probe.py`.

Not here, deliberately: `build/policy_sensitivity.py` stays in `build/` because it is
a verification harness rather than a one-off — `config/relation_policy.json` cites it
as the method behind each direction ruling, so it gets re-run when the policy changes.

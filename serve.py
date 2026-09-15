#!/usr/bin/env python3
"""Local server for the avoidance graph UI.

Python stdlib only, reusing the same Resolver and Graph the test suites run
against, so the UI can never disagree with the tests about what a query returns.

  /api/query?q=<term>   resolution + full graph
  /api/health           versions of every artefact in play
  /api/audit            what the local layer does to each ingredient
  /api/audit/edit       POST: write one decision, regenerate, hot-reload
  /api/audit/rebuild    POST: the ROBOT merge, for SPARQL parity
  /                     static files from web/

The audit endpoints write to the governed decision files and NEVER to the .ttl. The
.ttl is generated from those files, and test/patch_run.py fails on a hand-edit, so an
editor that wrote Turtle would be writing something the next build throws away.
"""
import json, os, sys, urllib.parse, http.server, socketserver, traceback, time, subprocess

sys.path.insert(0, "build")
from resolve import Resolver
import audit_model

print("loading ontology index...", flush=True)
_t = time.time()
RESOLVER = Resolver()
GRAPH = RESOLVER.g
print(f"ready in {time.time()-_t:.1f}s  "
      f"({len(GRAPH.N):,} classes, FoodOn {GRAPH.meta['version']})", flush=True)

# Explore-only: the shipped .app serves the graph and nothing that writes. The audit
# layer edits governed decision files, and a tester's copy has no review process behind
# it -- an edit there is a decision nobody signed. Gated at the server, not by hiding a
# link, because the audit page is reached by typing its URL and nothing else.
EXPLORE_ONLY = os.environ.get("FOODON_EXPLORE_ONLY") == "1"
_READ_ONLY = {"error": "This build is explore-only. The audit interface, which edits "
                       "the signed decision files, is not included.",
              "explore_only": True}

_cache = {}
_audit = {"data": None, "sparql_stale": False, "log": []}


def reload_graph():
    """Re-read every decision file into a fresh Graph, in place.

    An edit that does not reach the running server is an edit the user cannot see the
    effect of, and this app exists to show effects. Cheap enough to do on every write:
    the index is already on disk, so this is 0.1s, not the 19s ROBOT merge -- which is
    a separate button because it is a separate cost.
    """
    global RESOLVER, GRAPH
    RESOLVER = Resolver()
    GRAPH = RESOLVER.g
    _cache.clear()
    _audit["data"] = None


def audit_data():
    if _audit["data"] is None:
        _audit["data"] = audit_model.build(full=GRAPH)
    return dict(_audit["data"], sparql_stale=_audit["sparql_stale"], log=_audit["log"])

def annotations_for(roots):
    """Signed claims that are deliberately NOT edges in the graph.

    Two kinds, and the distinction is worth showing:

      no FoodOn class   `annotation_only`. There is nothing to point an edge at.
      weaker than
      containment       `may_contain`, `shared_compound`, `cross_reactive`,
                        `disputed`. A FoodOn class
                        exists, but the closure means "treat this as containing the
                        query" and none of these claims say that — `may_contain` is a
                        producer's feedstock choice, and `cross_reactive` states the
                        allergen protein is absent. Drawing them as edges asserted a
                        containment nobody signed; they belong here, with the claim
                        and the reason attached, so the weaker basis stays visible.

    Matched on resolved root IRIs rather than on the query string, so `soy`,
    `soya` and `soybean` all pick up the same soy annotations.
    """
    rs = set(roots)
    out = []
    for o in GRAPH.overrides.get("overrides", []):
        if o.get("type") != "add" or not o.get("reviewed_by"):
            continue
        weak = o.get("claim") != "contains"
        if not o.get("annotation_only") and not weak:
            continue
        if not (rs & set(o.get("query_roots") or [])):
            continue
        out.append({"term": o["target_label"], "claim": o.get("claim"),
                    "reason": o.get("reason"), "query": o.get("query_class"),
                    "in_foodon": bool(o.get("target_class")),
                    "curie": _curie(o.get("target_class")),
                    "iri": o.get("target_class"),
                    "source": o.get("source")})
    # containment-adjacent first, then alphabetically, so the ordering is stable
    order = {"may_contain": 0, "shared_compound": 1, "disputed": 2,
             "cross_reactive": 3}
    out.sort(key=lambda a: (order.get(a["claim"], 3), a["term"]))
    return out


def _curie(iri):
    if not iri:
        return None
    tail = iri.rsplit("/", 1)[-1]
    return tail.replace("_", ":", 1) if "_" in tail else tail

def query(q):
    key = q.strip().lower()
    if key in _cache:
        return _cache[key]
    res = RESOLVER.resolve(q)
    if res.get("status") != "resolved" or not res.get("roots"):
        out = {"resolution": res, "graph": None}
        _cache[key] = out
        return out
    roots = res["roots"]
    nodes, edges = GRAPH.closure(roots)
    # roots after expansion: a parallel-hierarchy twin is a root too, and the UI
    # should draw it as one rather than as an anonymous child
    graph = GRAPH.to_json_graph(q, GRAPH.last_roots, nodes, edges)
    graph["suppressed"] = len(getattr(GRAPH, "last_suppressed", ()) or ())
    out = {"resolution": {k: v for k, v in res.items() if k != "candidates"},
           "candidates": res.get("candidates", [])[:4],
           "annotations": annotations_for(roots),
           "graph": graph}
    _cache[key] = out
    return out


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory="web", **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  %s\n" % (fmt % args))

    def end_headers(self):
        # dev server: never let a stale app.js survive an edit
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if EXPLORE_ONLY:
            return self._send(_READ_ONLY, 403)
        if parsed.path == "/api/audit/preview":
            # accepts either shape: a statement (subject/predicate/object) or an
            # override (target_class/claim/query_roots). The second is the one that
            # had no preview, and is where a wrong IRI used to land in silence.
            try:
                p = self._body()
                if p.get("predicate"):
                    return self._send(audit_model.preview(p, graph=GRAPH))
                return self._send(audit_model.preview_override(p, graph=GRAPH))
            except audit_model.EditError as e:
                return self._send({"error": str(e)}, 400)
        if parsed.path == "/api/audit/edit":
            try:
                p = self._body()
                files = audit_model.apply_edit(p.get("action"), p.get("payload") or {},
                                               who=p.get("who") or "Matt")
            except audit_model.EditError as e:
                return self._send({"error": str(e)}, 400)
            except Exception:
                traceback.print_exc()
                return self._send({"error": "edit failed; see the server log"}, 500)
            impact = (audit_model.impact_of(p.get("payload") or {})
                      if p.get("action") in ("add_override", "edit_override") else None)
            log, stale = audit_model.regenerate(files)
            _audit["log"] = log
            if not all(x["ok"] for x in log):
                return self._send({"error": "the decision was written but regenerating "
                                            "failed; the app still shows the old graph",
                                   "files": files, "log": log}, 500)
            _audit["sparql_stale"] = stale
            reload_graph()
            return self._send({"ok": True, "files": files, "log": log,
                               "impact": impact, "audit": audit_data()})
        if parsed.path == "/api/audit/ingredients/review":
            try:
                p = self._body()
                out = audit_model.review_ingredients(
                    p.get("terms") or [], p.get("action"), who=p.get("who") or "Matt",
                    target=p.get("target"), reason=p.get("reason"),
                    choices=p.get("choices"))
            except audit_model.EditError as e:
                return self._send({"error": str(e)}, 400)
            except Exception:
                traceback.print_exc()
                return self._send({"error": "review failed; see the server log"}, 500)
            # no .ttl regeneration: the ingredient map feeds build/ingest.py, not the
            # patch layer, so nothing about the merged ontology changes here
            return self._send({"ok": True, **out,
                               "ingredients": audit_model.ingredients()})
        if parsed.path == "/api/audit/rebuild":
            r = subprocess.run(["./tools/apply_patches.sh"], capture_output=True, text=True)
            ok = r.returncode == 0
            if ok:
                _audit["sparql_stale"] = False
            return self._send({"ok": ok, "out": (r.stdout or r.stderr)[-4000:]},
                              200 if ok else 500)
        return self._send({"error": "not found"}, 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if EXPLORE_ONLY and (parsed.path.startswith("/api/audit")
                             or parsed.path.lstrip("/").startswith("audit.")):
            return self._send(_READ_ONLY, 403)
        if parsed.path == "/api/audit/lookup":
            qs = urllib.parse.parse_qs(parsed.query)
            return self._send({"hits": audit_model.lookup((qs.get("q") or [""])[0],
                                                          graph=GRAPH)})
        if parsed.path == "/api/audit/ingredients":
            return self._send(audit_model.ingredients())
        if parsed.path == "/api/audit/vocabulary":
            return self._send(audit_model.vocabulary())
        if parsed.path == "/api/audit":
            return self._send(audit_data())
        if parsed.path == "/api/health":
            return self._send({
                "ok": True,
                "classes": len(GRAPH.N),
                "foodon_version": GRAPH.meta["version"],
                "claim_types": GRAPH.overrides.get("claim_types") or {},
                "entry_types": GRAPH.overrides.get("entry_types") or {},
                "relation_policy": GRAPH.policy["version"],
                "policy_status": GRAPH.policy.get("status"),
                "store_entries": len(RESOLVER.store.get("entries", {})),
                "overrides": len(GRAPH.overrides.get("overrides", [])),
                # `superseded` counts as inactive alongside `declined`: it is a
                # retired entry carried by structure now, and reporting it as active
                # would overstate how much of the answer rests on curation
                "overrides_active": sum(
                    1 for o in GRAPH.overrides.get("overrides", [])
                    if o.get("reviewed_by")
                    and o.get("type") not in ("declined", "superseded")
                    and not o.get("annotation_only")),
                "overrides_superseded": sum(1 for o in GRAPH.overrides.get("overrides", [])
                                            if o.get("type") == "superseded"),
                "overrides_annotation": sum(1 for o in GRAPH.overrides.get("overrides", [])
                                            if o.get("annotation_only")),
                "overrides_declined": sum(1 for o in GRAPH.overrides.get("overrides", [])
                                          if o.get("type") == "declined"),
            })
        if parsed.path == "/api/query":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q") or [""])[0]
            if not q.strip():
                return self._send({"error": "empty query"}, 400)
            try:
                return self._send(query(q))
            except Exception:
                traceback.print_exc()
                return self._send({"error": "traversal failed"}, 500)
        return super().do_GET()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"\n  http://localhost:{port}/\n", flush=True)
        httpd.serve_forever()

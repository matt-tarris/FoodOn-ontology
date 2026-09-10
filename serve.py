#!/usr/bin/env python3
"""Local server for the avoidance graph UI.

Python stdlib only, reusing the same Resolver and Graph the test suites run
against, so the UI can never disagree with the tests about what a query returns.

  /api/query?q=<term>   resolution + full graph
  /api/health           versions of every artefact in play
  /                     static files from web/
"""
import json, sys, urllib.parse, http.server, socketserver, traceback, time

sys.path.insert(0, "build")
from resolve import Resolver

print("loading ontology index...", flush=True)
_t = time.time()
RESOLVER = Resolver()
GRAPH = RESOLVER.g
print(f"ready in {time.time()-_t:.1f}s  "
      f"({len(GRAPH.N):,} classes, FoodOn {GRAPH.meta['version']})", flush=True)

_cache = {}

def annotations_for(roots):
    """Signed claims that are deliberately NOT edges in the graph.

    Two kinds, and the distinction is worth showing:

      no FoodOn class   `annotation_only`. There is nothing to point an edge at.
      weaker than
      containment       `may_contain`, `cross_reactive`, `disputed`. A FoodOn class
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
    order = {"may_contain": 0, "disputed": 1, "cross_reactive": 2}
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            return self._send({
                "ok": True,
                "classes": len(GRAPH.N),
                "foodon_version": GRAPH.meta["version"],
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

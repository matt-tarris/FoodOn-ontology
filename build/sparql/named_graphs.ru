# Named-graph management for a SPARQL 1.1 Update endpoint (GraphDB, Jena/Fuseki,
# Stardog, Blazegraph). OPTIONAL: the ROBOT merge in tools/apply_patches.sh needs
# none of this, and is the recommended path because it adds no infrastructure. Use
# these when you want a live endpoint other services can query.
#
# Run the blocks one at a time -- most endpoints reject a multi-request body.
# Substitute your endpoint and file locations.
#
# WHY NAMED GRAPHS BUY SOMETHING THE MERGE DOES NOT
# A merged file loses the seam: an axiom we supplied is indistinguishable from one
# FoodOn shipped. Keeping the vendor ontology in its own graph preserves that
# distinction, which makes the upstream-fix check a single query (block 5) instead
# of the two-step comparison in build/check_upstream_fixes.py.

# --- 1. ingest the vendor ontology into its own graph -------------------------
# The base graph is treated as read-only from here on. Nothing but block 3 writes
# to it, so it can be replaced wholesale on an upstream release.
LOAD <file:///ABSOLUTE/PATH/ontology/foodon.owl>
  INTO GRAPH <https://fluxon.com/graphs/foodon-base> ;

# --- 2. ingest the local patch layer into its own graph -----------------------
LOAD <file:///ABSOLUTE/PATH/ontology/foodon-local-patches.ttl>
  INTO GRAPH <https://fluxon.com/graphs/foodon-local-patches> ;

# --- 3. upstream update: replace ONLY the base graph --------------------------
# This is the operation the whole layout exists for. DROP touches the base graph
# and nothing else, so the local layer survives an upstream release untouched and
# no patch has to be re-applied by hand.
#
# Order matters: DROP then LOAD, as one transaction if the endpoint supports it.
# If it does not, load into a staging graph first and MOVE it over, so a failed
# download cannot leave the endpoint with no base ontology at all.
DROP SILENT GRAPH <https://fluxon.com/graphs/foodon-base> ;
LOAD <file:///ABSOLUTE/PATH/ontology/foodon.owl>
  INTO GRAPH <https://fluxon.com/graphs/foodon-base> ;

# Safer variant for an endpoint without transactional updates:
#   LOAD <...> INTO GRAPH <https://fluxon.com/graphs/foodon-staging> ;
#   MOVE GRAPH <https://fluxon.com/graphs/foodon-staging>
#        TO GRAPH <https://fluxon.com/graphs/foodon-base> ;

# --- 4. materialise the avoidance relation into a third graph ------------------
# Same two relations build/sparql/patch_materialize_avoidance.rq produces, written
# to their own graph so they can be rebuilt without touching either input. Derived
# data: always safe to drop and regenerate.
DROP SILENT GRAPH <https://fluxon.com/graphs/foodon-avoidance> ;
INSERT {
  GRAPH <https://fluxon.com/graphs/foodon-avoidance> {
    ?source <https://fluxon.com/ns/foodon-local/propagatesTo> ?product .
  }
}
WHERE {
  {
    ?product <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?source .
    FILTER(isIRI(?source) && isIRI(?product))
  } UNION {
    ?product <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?r .
    ?r <http://www.w3.org/2002/07/owl#onProperty> ?p ;
       <http://www.w3.org/2002/07/owl#someValuesFrom> ?source .
    ?p <https://fluxon.com/ns/foodon-local/propagatesAvoidance> "inverse" .
    FILTER(isIRI(?source) && isIRI(?product))
  }
} ;

# --- 5. the upstream-fix check, as ONE query ----------------------------------
# Only possible with named graphs, because only here is the vendor graph still
# separate. A patch record whose axiom is also asserted in the BASE graph is
# redundant: upstream has fixed it and the local entry can be retired.
#
# Change to a SELECT to inspect before acting. Nothing here deletes anything --
# retiring a patch is a reviewed decision, not a cleanup.
SELECT ?patch ?target ?value
WHERE {
  GRAPH <https://fluxon.com/graphs/foodon-local-patches> {
    ?patch a <https://fluxon.com/ns/foodon-local/Patch> ;
           <https://fluxon.com/ns/foodon-local/patchTarget>   ?target ;
           <https://fluxon.com/ns/foodon-local/patchProperty> ?prop ;
           <https://fluxon.com/ns/foodon-local/patchValue>    ?value .
  }
  GRAPH <https://fluxon.com/graphs/foodon-base> {
    ?target <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?r .
    ?r <http://www.w3.org/2002/07/owl#onProperty> ?prop ;
       <http://www.w3.org/2002/07/owl#someValuesFrom> ?value .
  }
}

#!/usr/bin/env bash
# Reclaim regenerable disk. Nothing here is source: every file this removes is
# derived from the vendor ontology plus the governed decision files, and the command
# to rebuild it is printed on the way out.
#
#   ./tools/clean.sh                 what would go, and what it costs to rebuild
#   ./tools/clean.sh --sparql --yes  the SPARQL products      ~89 MB, 19s to rebuild
#   ./tools/clean.sh --build  --yes  extraction intermediates ~58 MB, 12s to rebuild
#   ./tools/clean.sh --all    --yes  both                     ~147 MB
#
# Dry run by default. Nothing is deleted without --yes.
#
# TWO THINGS IT WILL NOT REMOVE, and the reasons are different:
#
#   the vendor files      ontology/foodon.owl and tools/robot.jar are downloads, not
#                         derivations. Re-fetching them is a network round trip and a
#                         hash check, not a build step, so they are on an explicit
#                         deny list rather than merely absent from the target lists.
#
#   anything git tracks   the real guard. data/repairs-classified.json and
#                         data/mined-classified.json look like intermediates and are
#                         read by the traversal at startup; data/resolution-store.json
#                         is a governed decision file. Rather than trusting the path
#                         lists below to be right forever, every candidate is checked
#                         against the index and skipped if it is tracked. A typo here
#                         cannot destroy a reviewed decision.
set -uo pipefail
cd "$(dirname "$0")/.."

SPARQL=(
  ontology/foodon-queryable.owl        # largest derived file in the project
  ontology/foodon-merged.owl
  ontology/foodon-avoidance.ttl
  data/native-axioms.csv
)
BUILD=(
  data/foodon-asserted.obo.json
  data/structure.csv
  data/restrictions.csv
  data/diag.csv
  data/index.json                      # the app reads this; rebuilt by build_index.py
)
NEVER=(ontology/foodon.owl tools/robot.jar)

want_sparql=0; want_build=0; go=0
for a in "$@"; do
  case "$a" in
    --sparql) want_sparql=1 ;;
    --build)  want_build=1 ;;
    --all)    want_sparql=1; want_build=1 ;;
    --yes|-y) go=1 ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a  (try --help)"; exit 2 ;;
  esac
done
if [ $want_sparql -eq 0 ] && [ $want_build -eq 0 ]; then want_sparql=1; want_build=1; fi

targets=()
[ $want_sparql -eq 1 ] && targets+=("${SPARQL[@]}")
[ $want_build  -eq 1 ] && targets+=("${BUILD[@]}")

tracked=0; total=0; doomed=()
for f in "${targets[@]}"; do
  for n in "${NEVER[@]}"; do
    [ "$f" = "$n" ] && { echo "  REFUSING  $f  (vendor download, not derived)"; continue 2; }
  done
  [ -e "$f" ] || continue
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
     && git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "  SKIP      $f  (git tracks this -- not derived data, leaving it alone)"
    tracked=$((tracked+1)); continue
  fi
  s=$(stat -f%z "$f" 2>/dev/null || echo 0)
  total=$((total+s)); doomed+=("$f")
  printf "  %-9s %8.2f MB  %s\n" "$([ $go -eq 1 ] && echo remove || echo would)" \
         "$(echo "$s/1048576" | bc -l)" "$f"
done

if [ ${#doomed[@]} -eq 0 ]; then
  echo; echo "nothing to reclaim -- already clean."
  exit 0
fi

echo
printf "%s %.0f MB across %d files" \
  "$([ $go -eq 1 ] && echo 'reclaiming' || echo 'would reclaim')" \
  "$(echo "$total/1048576" | bc -l)" "${#doomed[@]}"
[ $tracked -gt 0 ] && printf ", %d skipped as tracked" "$tracked"
echo

if [ $go -eq 0 ]; then
  echo
  echo "dry run. add --yes to actually delete."
  exit 0
fi

for f in "${doomed[@]}"; do rm -f "$f"; done
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
echo

echo "to rebuild:"
if [ $want_build -eq 1 ]; then
  cat <<'REBUILD'
  # extraction intermediates and the index the app reads  (~12s)
  java -Xmx10g -jar tools/robot.jar convert -i ontology/foodon.owl --format json \
       -o data/foodon-asserted.obo.json
  java -Xmx12g -jar tools/robot.jar query -i ontology/foodon.owl \
       --query build/sparql/structure.rq data/structure.csv
  java -Xmx12g -jar tools/robot.jar query -i ontology/foodon.owl \
       --query build/sparql/diag.rq data/diag.csv
  python3 build/extract_edges.py
  python3 build/verify_extraction.py
  python3 build/build_index.py
REBUILD
fi
if [ $want_sparql -eq 1 ]; then
  cat <<'REBUILD'
  # the SPARQL products  (~19s)
  ./tools/apply_patches.sh
  java -Xmx10g -jar tools/robot.jar query --input ontology/foodon.owl \
       --query build/sparql/patch_native_axioms.rq data/native-axioms.csv
REBUILD
fi
[ $want_build -eq 1 ] && echo "
The app will not start until data/index.json is rebuilt."

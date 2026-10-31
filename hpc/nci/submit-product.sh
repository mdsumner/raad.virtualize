#!/usr/bin/env bash
# Submit build and publish jobs for every dataset of a product (one row of
# products/<name>/datasets.tsv each), the publish held on its build.
#
#   bash hpc/nci/submit-product.sh products/bluelink [DATASET ...]
#
# Run from the repository root on a Gadi login node. Without DATASET names,
# every row is submitted. Needs PROJECT and ST (the -l storage list), and the
# bucket keys (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) exported for the
# publish jobs; SIF is optional (the jobs default to the sif_lib image).
# DRY_RUN=1 prints the qsub commands instead of running them.
set -euo pipefail
[ $# -ge 1 ] || { sed -n '2,11p' "$0"; exit 1; }
TSV="$1/datasets.tsv"; shift
[ -f "$TSV" ] || { echo "no $TSV"; exit 1; }
: "${PROJECT:?set PROJECT}" "${ST:?set ST, for example gdata/gb6+gdata/jk72+scratch/jk72}"
if [ "${DRY_RUN:-0}" != 1 ]; then
  : "${AWS_ACCESS_KEY_ID:?export the bucket keys}" "${AWS_SECRET_ACCESS_KEY:?export the bucket keys}"
fi
run() { if [ "${DRY_RUN:-0}" = 1 ]; then echo "$*" >&2; echo DRYRUN; else "$@"; fi; }
want=" $* "
grep -v '^#' "$TSV" | tail -n +2 | while IFS=$'\t' read -r dataset config env title; do
  [ -n "$dataset" ] || continue
  [ $# -eq 0 ] || [[ $want == *" $dataset "* ]] || continue
  # the row's name must be the one the config gives, or the catalog points
  # at a directory the jobs never write
  got=$(env ${env//,/ } bash -c 'source "$1"; echo "$DATASET"' _ "$config")
  [ "$got" = "$dataset" ] || { echo "$dataset: $config with $env gives $got" >&2; exit 1; }
  v="CONFIG=$config,$env${SIF:+,SIF=$SIF}"
  job=$(run qsub -P "$PROJECT" -l storage="$ST" -v "$v" hpc/nci/bran-build.pbs)
  pub=$(run qsub -P "$PROJECT" -l storage="$ST" -W depend=afterok:"$job" \
          -v "$v,AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY" hpc/nci/bran-publish.pbs)
  echo "$dataset build $job publish $pub"
done

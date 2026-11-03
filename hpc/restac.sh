#!/usr/bin/env bash
# Rebuild and republish the STAC render (stac/, thumbnail.png) of every
# dataset of a product group whose other forms are already published, then
# the group catalog (README previews). Each dataset's work directory
# (store.sqlite, plan.vrt, out/) must still exist.
#
#   bash hpc/restac.sh GROUP [DATASET ...]
#
# GROUP is a directory under products/ (bluelink, ghrsst, oisst, seaice,
# oceancolour, bedmap, ibcso). DATASET names limit the run to those rows.
#   RUNNER     command that runs a repository script, default "bash";
#              "bash hpc/vm/docker-run.sh" on the Nectar VM,
#              "bash hpc/pawsey/singularity-run.sh" on Setonix, or
#              "singularity exec -B /g/data,/scratch $SIF bash" on Gadi
#   WORK_ROOT  directory holding the dataset work directories (E2E_WORK is
#              WORK_ROOT/<dataset>); default ./work
#   PUBLISH_CONFIG  default config/source-coop.sh; production products
#              (bedmap, ibcso) need SOURCECOOP_REPO and SOURCECOOP_PRODUCTION=1
#   ROOT_README=1  also copy the group catalog's README (previews, links) to
#              the product root as its landing page (production products,
#              as hpc/vm/bedmap3-publish.sh does)
# Needs the publish target's keys exported (source.coop: one hour).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
[ $# -ge 1 ] || { sed -n '2,22p' "$0"; exit 1; }
GROUP=$1; shift
TSV=products/$GROUP/datasets.tsv
[ -f "$TSV" ] || { echo "restac: no $TSV" >&2; exit 1; }
RUNNER=${RUNNER:-bash}
WORK_ROOT=${WORK_ROOT:-$HERE/work}
PUBLISH_CONFIG=${PUBLISH_CONFIG:-config/source-coop.sh}
grep -v '^#' "$TSV" | tail -n +2 | tr '\t' '\037' | while IFS=$'\037' read -r dataset config env title; do
  [ -n "$dataset" ] || continue
  if [ $# -gt 0 ] && [[ " $* " != *" $dataset "* ]]; then continue; fi
  [ -f "$WORK_ROOT/$dataset/store.sqlite" ] || { echo "restac: $dataset: no $WORK_ROOT/$dataset/store.sqlite" >&2; exit 1; }
  echo "== restac $dataset"
  # the row's settings as environment (comma separated, as qsub -v takes them)
  env ${env//,/ } E2E_WORK="$WORK_ROOT/$dataset" $RUNNER run.sh "$config" "$PUBLISH_CONFIG" stac publish-stac < /dev/null
done
$RUNNER catalog.sh "products/$GROUP" "$PUBLISH_CONFIG" check publish
if [ "${ROOT_README:-0}" = 1 ]; then
  cat > work/restac-readme.sh <<INNER
set -euo pipefail
DATASET=; PRODUCT_GROUP=; source config/source-coop.sh
python py/s3_sync.py work/$GROUP/catalog/README.md "\$PUBLISH_ROOT/README.md"
INNER
  $RUNNER work/restac-readme.sh
fi

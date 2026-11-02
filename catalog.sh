#!/usr/bin/env bash
# STAC catalog of a product group (products/<group>/): one child per dataset
# in its datasets.tsv, beside the dataset directories that run.sh publishes.
# Given products/ itself (product.json + groups.tsv), the root catalog: one
# child per group, written at the publish target's PUBLISH_ROOT.
#
#   bash catalog.sh products/bluelink                                  build only
#   bash catalog.sh products/bluelink config/aadc-transfer.sh check publish
#   bash catalog.sh products/bluelink config/source-coop.sh check publish
#   bash catalog.sh products config/source-coop.sh check publish     root
#
# On source.coop scratch a group publishes under <product>/<group>/ and its
# catalog links up to the root (../catalog.json); publish every group's
# catalog before the root's check.
#
# A leading *.sh argument after the product directory is a publish target,
# as for run.sh. Steps:
#   build    py/catalog.py into work/<product>/catalog/ (default)
#   check    build, reading every dataset's collection.json from the publish
#            prefix; fails when one is missing (completeness before publish)
#   publish  copy catalog.json, datasets.json, datasets.tsv, product.json and
#            README.md (and any image beside it, e.g. banner.jpg) to the
#            publish prefix root
# Env: E2E_WORK (default ./work/<product>), PYTHON, CATALOG_BASE (public URL
#      of the publish prefix, for the self link; default STAC_BASE of the
#      publish target where it sets one).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -ge 1 ] || { sed -n '2,25p' "$0"; exit 1; }
PRODUCT_DIR=$1; shift
[ -f "$PRODUCT_DIR/product.json" ] || { echo "catalog: no product.json in $PRODUCT_DIR"; exit 1; }
PRODUCT_DIR=${PRODUCT_DIR%/}
PRODUCT=$(basename "$PRODUCT_DIR")
ROOT_MODE=0; [ -f "$PRODUCT_DIR/groups.tsv" ] && ROOT_MODE=1
# publish targets build per-dataset paths from DATASET; the catalog sits one
# level up, at the group prefix. The group is the product directory's name
# (the scratch prefix on source.coop); the root has none.
DATASET=
if [ $ROOT_MODE = 1 ]; then PRODUCT_GROUP=; PRODUCT=_root; else PRODUCT_GROUP=$PRODUCT; fi
while [ $# -ge 1 ] && [[ $1 == *.sh ]]; do source "$1"; shift; done
STEPS=${*:-build}
PYTHON=${PYTHON:-python}
WORK=${E2E_WORK:-$HERE/work/$PRODUCT}
OUT="$WORK/catalog"
BASE=${CATALOG_BASE:-${STAC_BASE:-}}
BASE=${BASE%/}
PARENT=
if [ $ROOT_MODE = 1 ]; then
  if [ -n "${PUBLISH:-}" ]; then
    [ -n "${PUBLISH_ROOT:-}" ] || { echo "catalog: this publish target has no groups (no PUBLISH_ROOT)"; exit 1; }
    PUBLISH=$PUBLISH_ROOT
  fi
  BASE=${CATALOG_BASE:-${PUBLISH_ROOT_BASE:-}}
  BASE=${BASE%/}
elif [ -n "${PUBLISH_ROOT:-}" ] && [ "${PUBLISH%/}" != "${PUBLISH_ROOT%/}" ]; then
  # one ../ per path level between the group and the product root
  rel=${PUBLISH#"${PUBLISH_ROOT%/}"/}
  PARENT=$(echo "${rel%/}" | awk -F/ '{for (i = 1; i <= NF; i++) printf "../"}')catalog.json
fi
# every row's config must put its dataset in this group, or run.sh publishes
# it somewhere the catalog does not look
if [ $ROOT_MODE = 0 ]; then
  grep -v '^#' "$PRODUCT_DIR/datasets.tsv" | tail -n +2 | while IFS=$'\t' read -r dataset config env title; do
    [ -n "$dataset" ] || continue
    got=$(cd "$HERE" && env ${env//,/ } HERE="$HERE" bash -c 'source "$1"; echo "${PRODUCT_GROUP:-}"' _ "$config")
    [ "$got" = "$PRODUCT_GROUP" ] || { echo "catalog: $dataset: $config gives PRODUCT_GROUP '$got', not $PRODUCT_GROUP" >&2; exit 1; }
  done
fi
for s in $STEPS; do
  case $s in
    build)
      "$PYTHON" "$HERE/py/catalog.py" "$PRODUCT_DIR" "$OUT" ${BASE:+--base "$BASE"} \
        ${PARENT:+--parent "$PARENT"} ;;
    check)
      [ -n "${PUBLISH:-}" ] || { echo "check: source a publish config"; exit 1; }
      # obstore targets (source.coop) are public and their proxy rejects
      # GDAL's request signing: read the collections back anonymously
      anon=; [ "${PUBLISH_WITH:-gdal}" = obstore ] && anon=AWS_NO_SIGN_REQUEST=YES
      env $anon "$PYTHON" "$HERE/py/catalog.py" "$PRODUCT_DIR" "$OUT" --published "$PUBLISH" --check \
        ${BASE:+--base "$BASE"} ${PARENT:+--parent "$PARENT"} ;;
    publish)
      [ -n "${PUBLISH:-}" ] || { echo "publish: source a publish config"; exit 1; }
      [ -f "$OUT/catalog.json" ] || { echo "publish: run build or check first"; exit 1; }
      for f in "$OUT"/*; do
        if [ "${PUBLISH_WITH:-gdal}" = obstore ]; then
          "$PYTHON" "$HERE/py/s3_sync.py" "$f" "${PUBLISH%/}/$(basename "$f")"
        else
          "${GDAL:-gdal}" vsi copy "$f" "${PUBLISH%/}/$(basename "$f")"
        fi
      done ;;
    *) echo "unknown step $s"; exit 1 ;;
  esac
done

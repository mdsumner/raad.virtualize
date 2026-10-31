#!/usr/bin/env bash
# Root STAC catalog of a product (products/<name>/): one child per dataset in
# its datasets.tsv, beside the dataset directories that run.sh publishes.
#
#   bash catalog.sh products/bluelink                                  build only
#   bash catalog.sh products/bluelink config/aadc-transfer.sh check publish
#
# A leading *.sh argument after the product directory is a publish target,
# as for run.sh. Steps:
#   build    py/catalog.py into work/<product>/catalog/ (default)
#   check    build, reading every dataset's collection.json from the publish
#            prefix; fails when one is missing (completeness before publish)
#   publish  copy catalog.json, datasets.json, datasets.tsv, product.json and
#            README.md to the publish prefix root
# Env: E2E_WORK (default ./work/<product>), PYTHON, CATALOG_BASE (public URL
#      of the publish prefix, for the self link; default STAC_BASE of the
#      publish target where it sets one).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -ge 1 ] || { sed -n '2,17p' "$0"; exit 1; }
PRODUCT_DIR=$1; shift
[ -f "$PRODUCT_DIR/product.json" ] || { echo "catalog: no product.json in $PRODUCT_DIR"; exit 1; }
PRODUCT=$(basename "$PRODUCT_DIR")
# publish targets build per-dataset paths from DATASET; the catalog sits one
# level up, at the prefix root
DATASET=
while [ $# -ge 1 ] && [[ $1 == *.sh ]]; do source "$1"; shift; done
STEPS=${*:-build}
PYTHON=${PYTHON:-python}
WORK=${E2E_WORK:-$HERE/work/$PRODUCT}
OUT="$WORK/catalog"
BASE=${CATALOG_BASE:-${STAC_BASE:-}}
BASE=${BASE%/}
for s in $STEPS; do
  case $s in
    build)
      "$PYTHON" "$HERE/py/catalog.py" "$PRODUCT_DIR" "$OUT" ${BASE:+--base "$BASE"} ;;
    check)
      [ -n "${PUBLISH:-}" ] || { echo "check: source a publish config"; exit 1; }
      "$PYTHON" "$HERE/py/catalog.py" "$PRODUCT_DIR" "$OUT" --published "$PUBLISH" --check \
        ${BASE:+--base "$BASE"} ;;
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

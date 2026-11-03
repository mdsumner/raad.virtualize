# IBCSO (Dorschel et al. 2022, doi:10.1594/PANGAEA.937574, CC BY 4.0): static
# 500 m grids in EPSG:9354, 19200 x 19200, Int16, nodata -32768. One array per
# COG, dimensions (y, x), with no time axis; each release is its own prefix
# and dataset.
#
#   IBCSO_RELEASE  v2 (default, PANGAEA), 2024 or 2025 (annual releases; see
#                  py/ibcso_cog.py for the origin correction)
#
# The sources are COGs written by py/ibcso_cog.py in IBCSO_COG and published to
# IBCSO_COG_URL. The harvest reads the local COGs; remap rules give every
# form the public URL.
#
#   IBCSO_RAW      the release files and fetch.tsv (default work/ibcso-raw for
#                  v2, work/ibcso-<release>-raw otherwise)
#   IBCSO_COG      local COG directory (default work/ibcso-<prefix>-cog)
#   IBCSO_COG_URL  public URL of the COGs
#   IBCSO_LOCAL    1: forms reference the local COGs (see below)
#   IBCSO_OVERVIEWS 1 (default): every overview level of the COGs is an
#                  array of its own, <name>_x<factor> (py/plan_static.py
#                  --overviews; AVERAGE, NEAREST for rid and tid, as
#                  py/ibcso_cog.py writes them); 0: full resolution only
IBCSO_RELEASE=${IBCSO_RELEASE:-v2}
case $IBCSO_RELEASE in
  v2) IBCSO_PREFIX=v2; raw=ibcso-raw; released=2022-05-20T12:03:02Z ;;
  2024) IBCSO_PREFIX=annual-2024; raw=ibcso-2024-raw/unz; released=2024-08-08T08:18:00Z ;;
  2025) IBCSO_PREFIX=annual-2025; raw=ibcso-2025-raw; released=2025-09-19T08:56:06Z ;;
  *) echo "IBCSO_RELEASE must be v2, 2024 or 2025" >&2; exit 1 ;;
esac
DATASET=ibcso-$IBCSO_PREFIX
# product group (products/ibcso/); the prefix of the group catalog
PRODUCT_GROUP=ibcso
IBCSO_RAW=${IBCSO_RAW:-$HERE/work/$raw}
IBCSO_COG=${IBCSO_COG:-$HERE/work/ibcso-$IBCSO_PREFIX-cog}
IBCSO_COG_URL=${IBCSO_COG_URL:-https://data.source.coop/ausantarctic/ibcso/$IBCSO_PREFIX/cog}
ARRAYS="bed ice_surface rid tid"
prepare() { "$PYTHON" "$HERE/py/ibcso_cog.py" --release "$IBCSO_RELEASE" --raw "$IBCSO_RAW" --out "$IBCSO_COG"; }
sources() { for a in $ARRAYS; do echo "$IBCSO_COG/$a.tif"; done; }
make_plan() {
  "$PYTHON" "$HERE/py/plan_static.py" --sources "$WORK/sources.txt" \
    $([ "${IBCSO_OVERVIEWS:-1}" = 1 ] && echo --resampling AVERAGE --resampling rid=NEAREST --resampling tid=NEAREST) "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|$IBCSO_COG|$IBCSO_COG_URL" "gdal|$IBCSO_COG|/vsicurl/$IBCSO_COG_URL")
# IBCSO_LOCAL=1: the forms reference the local COGs, so verify passes before
# any upload; a separate work directory keeps the public build
if [ "${IBCSO_LOCAL:-0}" = 1 ]; then REMAPS=("public|$IBCSO_COG|file://$IBCSO_COG"); DATASET=$DATASET-local; fi
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-4}
# the grids are not temporal: the interval is the release date (v2: PANGAEA
# record; 2024: file times in the release zips; 2025: server Last-Modified)
export STAC_INTERVAL=${STAC_INTERVAL:-$released,$released}
export STAC_LICENSE=${STAC_LICENSE:-CC-BY-4.0}
case $IBCSO_RELEASE in
  v2) title="International Bathymetric Chart of the Southern Ocean Version 2" ;;
  *) title="International Bathymetric Chart of the Southern Ocean, $IBCSO_RELEASE annual release" ;;
esac
export STAC_TITLE=${STAC_TITLE:-$title}
# thumbnail: bed, blues below sea level and earth tones above
export STAC_THUMB_PALETTE=${STAC_THUMB_PALETTE:-topo}
# the grist catalog contract needs a date; a static grid has none
DEFAULT_STEPS="plan harvest collate render icechunk stac verify"

# GEBCO global grids (GEBCO Compilation Group, https://www.gebco.net/): static
# 15 arc-second elevation, 43200 x 86400, Int16, nodata -32767, EPSG:4326.
# One array, elevation, of dimensions (y, x), with no time axis; each release
# is its own dataset.
#
# No copy and no prepare: the sources are the COGs already published at
# ausantarctic/gebco (GEBCO_<year>.tif, made by
# github.com/AustralianAntarcticDivision/gebco), indexed in place as the
# GHRSST COGs are. DEFLATE 512 x 512 tiles; 2025 and 2026 use PREDICTOR=2,
# which maps to imagecodecs_delta: the kerchunk and Icechunk forms need
# imagecodecs in the reader and GDAL reads neither (the VRT form is
# unaffected). 2024 has no predictor.
#
#   GEBCO_YEAR      2024, 2025 or 2026 (default 2026)
#   GEBCO_COG_BASE  where the COGs are read from (default
#                   https://data.source.coop/ausantarctic/gebco); sources are
#                   recorded as /vsicurl/<base>/GEBCO_<year>.tif
#   GEBCO_OVERVIEWS 1 (default): every overview level of the COG is an array
#                   of its own, elevation_x<factor> (py/plan_static.py
#                   --overviews; resampling recorded as unknown, it is the
#                   COG writer's); 0: full resolution only
#
#   bash hpc/vm/docker-run.sh run.sh config/gebco.sh
#   SOURCECOOP_REPO=ausantarctic/gebco SOURCECOOP_PRODUCTION=1 \
#     bash hpc/vm/docker-run.sh run.sh config/gebco.sh config/source-coop.sh publish verify-published
GEBCO_YEAR=${GEBCO_YEAR:-2026}
case $GEBCO_YEAR in
  2024|2025|2026) ;;
  *) echo "GEBCO_YEAR must be 2024, 2025 or 2026" >&2; exit 1 ;;
esac
DATASET=gebco-$GEBCO_YEAR
# product group (products/gebco/); the prefix of the group catalog
PRODUCT_GROUP=gebco
GEBCO_COG_BASE=${GEBCO_COG_BASE:-https://data.source.coop/ausantarctic/gebco}
GEBCO_COG_BASE=${GEBCO_COG_BASE%/}
ARRAYS=elevation
# NAME<TAB>SOURCE: the array is elevation, not the file name
sources() { printf 'elevation\t/vsicurl/%s/GEBCO_%s.tif\n' "$GEBCO_COG_BASE" "$GEBCO_YEAR"; }
make_plan() {
  "$PYTHON" "$HERE/py/plan_static.py" --sources "$WORK/sources.txt" \
    $([ "${GEBCO_OVERVIEWS:-1}" = 1 ] && echo --overviews) "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=""
WORKERS=${WORKERS:-4}
# the grid is not temporal: the interval is the release year, as the
# GEBCO_<year>.stac-item.json beside the COG states it
export STAC_INTERVAL=${STAC_INTERVAL:-$GEBCO_YEAR-01-01T00:00:00Z,$GEBCO_YEAR-01-01T00:00:00Z}
# GEBCO terms of use: public domain, attribution requested (see README)
export STAC_LICENSE=${STAC_LICENSE:-other}
export STAC_TITLE=${STAC_TITLE:-GEBCO_$GEBCO_YEAR Grid, global 15 arc-second elevation}
# thumbnail: blues below sea level and earth tones above
export STAC_THUMB_PALETTE=${STAC_THUMB_PALETTE:-topo}
# the grist catalog contract needs a date; a static grid has none
DEFAULT_STEPS="plan harvest collate render icechunk stac verify"

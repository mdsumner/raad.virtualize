# Bedmap3 (Pritchard et al. 2024, UK Polar Data Centre,
# doi:10.5285/2d0e4791-8e20-46a3-80e4-f5f6716025d2, CC BY 4.0): static 500 m
# grids in EPSG:3031, 13334 x 13334, Int16, nodata -9999. One array per COG,
# dimensions (y, x), with no time axis.
#
# The sources are COGs written by py/bedmap3_cog.py from bedmap3.nc, in
# BEDMAP3_COG, and published to BEDMAP3_COG_URL. The harvest reads the local
# COGs; remap rules give every form the public URL.
#
#   BEDMAP3_RAW      the UK PDC files and fetch.tsv (default work/bedmap3-raw)
#   BEDMAP3_COG      local COG directory (default work/bedmap3-cog)
#   BEDMAP3_COG_URL  public URL of the COGs
#   BEDMAP3_LOCAL    1: forms reference the local COGs (see below)
#
#   bash hpc/vm/docker-run.sh run.sh config/bedmap3.sh prepare
#   SOURCECOOP_REPO=ausantarctic/bedmap SOURCECOOP_PRODUCTION=1 \
#     bash hpc/vm/docker-run.sh run.sh config/bedmap3.sh config/source-coop.sh
DATASET=bedmap3
# product group (products/bedmap/); the prefix of the group catalog
PRODUCT_GROUP=bedmap
BEDMAP3_RAW=${BEDMAP3_RAW:-$HERE/work/bedmap3-raw}
BEDMAP3_COG=${BEDMAP3_COG:-$HERE/work/bedmap3-cog}
BEDMAP3_COG_URL=${BEDMAP3_COG_URL:-https://data.source.coop/ausantarctic/bedmap/bedmap3/cog}
ARRAYS="bed_topography bed_uncertainty ice_thickness mask surface_topography thickness_survey_count thickness_uncertainty"
prepare() {
  "$PYTHON" "$HERE/py/bedmap3_cog.py" --nc "$BEDMAP3_RAW/bedmap3.nc" \
    --fetch "$BEDMAP3_RAW/fetch.tsv" --out "$BEDMAP3_COG"
}
sources() { for a in $ARRAYS; do echo "$BEDMAP3_COG/$a.tif"; done; }
make_plan() { "$PYTHON" "$HERE/py/plan_static.py" --sources "$WORK/sources.txt" "$WORK/plan.vrt"; }
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|$BEDMAP3_COG|$BEDMAP3_COG_URL" "gdal|$BEDMAP3_COG|/vsicurl/$BEDMAP3_COG_URL")
# BEDMAP3_LOCAL=1: the forms reference the local COGs and verify
# passes before any upload; a separate work directory keeps the public build
if [ "${BEDMAP3_LOCAL:-0}" = 1 ]; then REMAPS=("public|$BEDMAP3_COG|file://$BEDMAP3_COG"); DATASET=bedmap3-local; fi
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-4}
# time_coverage_start and time_coverage_end of bedmap3.nc
export STAC_INTERVAL=${STAC_INTERVAL:-1966-01-01T00:00:00Z,2024-11-01T00:00:00Z}
export STAC_LICENSE=${STAC_LICENSE:-CC-BY-4.0}
export STAC_TITLE=${STAC_TITLE:-Bedmap3 ice thickness, bed and surface elevation for Antarctica}
# thumbnail: bed_topography, blues below sea level and earth tones above
export STAC_THUMB_PALETTE=${STAC_THUMB_PALETTE:-topo}
# the grist catalog contract needs a date; a static grid has none
DEFAULT_STEPS="plan harvest collate render icechunk stac verify"

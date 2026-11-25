# BedMachine Antarctica (Morlighem, NSIDC-0756 Version 4, file V04.1,
# doi:10.5067/POJQI54A45HX): static 500 m grids in EPSG:3031, 13333 x 13333.
# Ten arrays of dimensions (y, x), with no time axis: Float32 bed, surface,
# thickness, firn and geoid, Int16 errbed (nodata -9999 on all six but
# geoid, which has none), and the Int8 class arrays mask, source, dataid and
# rgi (no nodata). Elevations are relative to the EIGEN-6C4 geoid, in ice
# equivalent.
#
# The sources are COGs written by py/bedmachine_cog.py from the NSIDC
# netCDF, in BEDMACHINE_COG, and published to BEDMACHINE_COG_URL, as for
# Bedmap3. NSIDC needs an Earthdata login and removes a retired version (v3
# on 2026-02-24), so the forms reference these copies, not the netCDF.
#
#   BEDMACHINE_RAW      the NSIDC netCDF and fetch.tsv (default work/bedmachine-raw)
#   BEDMACHINE_COG      local COG directory (default work/bedmachine-cog)
#   BEDMACHINE_COG_URL  public URL of the COGs
#   BEDMACHINE_LOCAL    1: forms reference the local COGs, so verify runs
#                       before any upload (a separate work directory)
#   BEDMACHINE_OVERVIEWS 1 (default): every overview level of the COGs is an
#                       array of its own, <name>_x<factor>; 0: full
#                       resolution only
#
# Fetch (docs/bedmachine-source-coop.md), then:
#   bash hpc/vm/docker-run.sh run.sh config/bedmachine.sh prepare
#   BEDMACHINE_LOCAL=1 bash hpc/vm/docker-run.sh run.sh config/bedmachine.sh
#   SOURCECOOP_REPO=ausantarctic/bedmachine SOURCECOOP_PRODUCTION=1 \
#     bash hpc/vm/docker-run.sh run.sh config/bedmachine.sh config/source-coop.sh
BEDMACHINE_VERSION=v4.1
BEDMACHINE_FILE=NSIDC-0756_BedMachineAntarctica_19700101-20191001_V04.1.nc
DATASET=bedmachine-$BEDMACHINE_VERSION
# product group (products/bedmachine/); the prefix of the group catalog
PRODUCT_GROUP=bedmachine
BEDMACHINE_RAW=${BEDMACHINE_RAW:-$HERE/work/bedmachine-raw}
BEDMACHINE_COG=${BEDMACHINE_COG:-$HERE/work/bedmachine-cog}
BEDMACHINE_COG_URL=${BEDMACHINE_COG_URL:-https://data.source.coop/ausantarctic/bedmachine/$BEDMACHINE_VERSION/cog}
# bed first: the thumbnail draws the first of ARRAYS
ARRAYS="bed dataid errbed firn geoid mask rgi source surface thickness"
prepare() {
  "$PYTHON" "$HERE/py/bedmachine_cog.py" --nc "$BEDMACHINE_RAW/$BEDMACHINE_FILE" \
    --fetch "$BEDMACHINE_RAW/fetch.tsv" --out "$BEDMACHINE_COG"
}
sources() { for a in $ARRAYS; do echo "$BEDMACHINE_COG/$a.tif"; done; }
make_plan() {
  "$PYTHON" "$HERE/py/plan_static.py" --sources "$WORK/sources.txt" \
    $([ "${BEDMACHINE_OVERVIEWS:-1}" = 1 ] && echo --overviews --resampling AVERAGE \
      --resampling mask=NEAREST --resampling source=NEAREST \
      --resampling dataid=NEAREST --resampling rgi=NEAREST) "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|$BEDMACHINE_COG|$BEDMACHINE_COG_URL" "gdal|$BEDMACHINE_COG|/vsicurl/$BEDMACHINE_COG_URL")
if [ "${BEDMACHINE_LOCAL:-0}" = 1 ]; then
  REMAPS=("public|$BEDMACHINE_COG|file://$BEDMACHINE_COG"); DATASET=$DATASET-local
fi
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-4}
# the data's temporal coverage (user guide 1.4.1): surveys 1970 to 2019-10-01
export STAC_INTERVAL=${STAC_INTERVAL:-1970-01-01T00:00:00Z,2019-10-01T00:00:00Z}
# NASA EOSDIS: free to use without restriction, with the citation (README)
export STAC_LICENSE=${STAC_LICENSE:-other}
export STAC_TITLE=${STAC_TITLE:-BedMachine Antarctica $BEDMACHINE_VERSION bed topography and ice thickness}
# thumbnail: bed, blues below sea level and earth tones above
export STAC_THUMB_PALETTE=${STAC_THUMB_PALETTE:-topo}
# the grist catalog contract needs a date; a static grid has none
DEFAULT_STEPS="plan harvest collate render icechunk stac verify"

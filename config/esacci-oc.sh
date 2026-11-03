# ESA Ocean Colour CCI v6.0 (https://climate.esa.int/en/projects/ocean-colour/),
# merged-sensor L3S, geographic 4 km (8640 x 4320, 1/24 degree, EPSG:4326),
# monthly, 5-day or daily from 1997-09. The sources are COGs written by py/esacci_cog.py from
# the netCDF files of www.oceancolour.org THREDDS (hpc/pawsey/esacci-cog.slurm),
# one per variable per month, Float32, NaN nodata, 512 x 512 tiles, ZSTD
# without a predictor, so GDAL reads every form. See docs/esacci-oc.md.
#
#   ESACCI_VAR       variable (COG name suffix), default chlor_a
#   ESACCI_CADENCE   monthly (default), 5day or daily: the THREDDS folder
#                    name; the plan's time axis is py/plan_cog.py --cadence
#                    month, 5day (calendar detected from the file dates) or day
#   ESACCI_COG_ROOT  COG root as py/esacci_cog.py writes it (the directory
#                    holding v6.0-release/), default $MYSCRATCH/esacci-oc/cog
#                    on Setonix. A local directory is listed with find; a
#                    /vsis3/ or /vsicurl/ root with gdal vsi ls -R.
#   ESACCI_COG_URL   public URL of the same root (default the Acacia bucket
#                    aad-derived/esacci-oc); the remap rules give every form
#                    this URL
#   ESACCI_YEARS     years to include (default all); the dataset name gets a
#                    -<years> suffix, so a subset never overwrites the series
#   ESACCI_MAX_MISSING  time steps between the first and last file allowed
#                    to have no file (default 0)
#
#   bash run.sh config/esacci-oc.sh
#   bash run.sh config/esacci-oc.sh config/source-coop.sh publish verify-published
ESACCI_VAR=${ESACCI_VAR:-chlor_a}
ESACCI_CADENCE=${ESACCI_CADENCE:-monthly}
ESACCI_COG_ROOT=${ESACCI_COG_ROOT:-${MYSCRATCH:-$HERE/work}/esacci-oc/cog}
ESACCI_COG_ROOT=${ESACCI_COG_ROOT%/}
ESACCI_COG_URL=${ESACCI_COG_URL:-https://projects.pawsey.org.au/aad-derived/esacci-oc}
ESACCI_COG_URL=${ESACCI_COG_URL%/}
case "$ESACCI_CADENCE" in
  monthly) ESACCI_STEP=month; ESACCI_DATE='[0-9]{6}' ;;
  5day)    ESACCI_STEP=5day;  ESACCI_DATE='[0-9]{8}' ;;
  daily)   ESACCI_STEP=day;   ESACCI_DATE='[0-9]{8}' ;;
  *) echo "esacci-oc.sh: ESACCI_CADENCE must be monthly, 5day or daily" >&2; exit 1 ;;
esac
ESACCI_DIR=v6.0-release/geographic/$ESACCI_CADENCE/$ESACCI_VAR
DATASET=esacci-oc-v6.0-$ESACCI_CADENCE-$ESACCI_VAR${ESACCI_YEARS:+-$(echo $ESACCI_YEARS | tr ' ' '-')}
# product group (products/oceancolour/): the scratch prefix on source.coop
PRODUCT_GROUP=oceancolour
ARRAYS=$ESACCI_VAR
# the cadence tag in the name (1M_MONTHLY, 5D_...) is not matched: the
# cadence is the folder
ESACCI_PATTERN="^ESACCI-OC-L3S-[A-Z0-9_]+-MERGED-[A-Z0-9_]+_4km_GEO_PML_[A-Za-z0-9]+-(${ESACCI_DATE})-fv6\.0_${ESACCI_VAR}\.tif\$"
sources() (
  root=$ESACCI_COG_ROOT/$ESACCI_DIR
  if [ -d "$root" ]; then
    find "$root" -name '*.tif'
  else
    "$GDAL" vsi ls -R "$root" | grep '\.tif$' | sed "s#^#$root/#"
  fi | while read -r f; do
    b=${f##*/}; [[ $b =~ $ESACCI_PATTERN ]] || continue
    [ -z "${ESACCI_YEARS:-}" ] || [[ " $ESACCI_YEARS " == *" ${BASH_REMATCH[1]:0:4} "* ]] || continue
    printf '%s\t%s\n' "$b" "$f"
  done | sort | cut -f2   # date order, by file name
)
make_plan() {
  "$PYTHON" "$HERE/py/plan_cog.py" --sources "$WORK/sources.txt" --array "$ESACCI_VAR" \
    --cadence "$ESACCI_STEP" --pattern "$ESACCI_PATTERN" \
    --max-missing "${ESACCI_MAX_MISSING:-0}" "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|$ESACCI_COG_ROOT|$ESACCI_COG_URL" "gdal|$ESACCI_COG_ROOT|/vsicurl/$ESACCI_COG_URL")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-8}
# one STAC item file per 5-day or daily step is thousands of uploads: keep
# the ndjson and stac-geoparquet item forms only (as OISST)
[ "$ESACCI_CADENCE" = monthly ] || export STAC_ITEM_FILES=${STAC_ITEM_FILES:-0}
export STAC_LICENSE=${STAC_LICENSE:-other}
export STAC_TITLE=${STAC_TITLE:-ESA Ocean Colour CCI v6.0 $ESACCI_CADENCE $ESACCI_VAR, merged sensors, 4 km}

# NOAA/NSIDC Climate Data Record of passive microwave sea ice concentration,
# G02202 Version 6 (https://nsidc.org/data/g02202/versions/6), 25 km polar
# stereographic grids: south pss25 (316 x 332), north psn25 (304 x 448).
# One netCDF4 file per day (from 1978-10-25) or month (from 1978-11), served
# anonymously over HTTPS from noaadata.apps.nsidc.org. The sensor in the file
# name changes over the record (n07, F08, F11, F13, F17, am2); the arrays in
# the root group are the same for every sensor (supplementary fields and the
# AMSR2 prototype are in subgroups, not indexed here).
#
# The file list is the aad-filelist collection cdr_sic_G02202_V6 (the raad
# mirror listing), not a crawl of the NSIDC server.
#
#   SEAICE_HEM=south          south or north (separate grids and SRS, so
#                             separate datasets)
#   SEAICE_FREQ=daily         daily or monthly
#   SEAICE_FIRST, SEAICE_LAST bounds on the file date, YYYYMMDD (daily) or
#                             YYYYMM (monthly), inclusive; for a smoke test
#   SEAICE_ARRAYS             default cdr_seaice_conc (daily) or
#                             cdr_seaice_conc_monthly (monthly), uint8,
#                             scale 0.01, fill 255; other root arrays (daily):
#                             cdr_seaice_conc_stdev, cdr_seaice_conc_qa_flag,
#                             cdr_seaice_conc_interp_spatial_flag,
#                             cdr_seaice_conc_interp_temporal_flag; (monthly)
#                             cdr_seaice_conc_monthly_stdev,
#                             cdr_seaice_conc_monthly_qa_flag
#   SEAICE_MIRROR             a local directory holding
#                             noaadata.apps.nsidc.org/NOAA/G02202_V6/ (the
#                             raad layout): sources are read from it and
#                             remapped to the NSIDC URLs at publish; files
#                             listed but missing from the mirror are skipped
#   SEAICE_FILELIST           the file list Parquet (URL or local path)
SEAICE_HEM=${SEAICE_HEM:-south}
SEAICE_FREQ=${SEAICE_FREQ:-daily}
case "$SEAICE_HEM" in south|north) ;; *) echo "SEAICE_HEM must be south or north" >&2; exit 1 ;; esac
case "$SEAICE_FREQ" in
  daily)   SEAICE_DATE='_([0-9]{8})_'; SEAICE_CONC=cdr_seaice_conc ;;
  monthly) SEAICE_DATE='_([0-9]{6})_'; SEAICE_CONC=cdr_seaice_conc_monthly ;;
  *) echo "SEAICE_FREQ must be daily or monthly" >&2; exit 1 ;;
esac
DATASET=g02202-v6-$SEAICE_FREQ-$SEAICE_HEM${SEAICE_FIRST:+-$SEAICE_FIRST}${SEAICE_LAST:+-$SEAICE_LAST}
# product group (products/seaice/): the scratch prefix on source.coop
PRODUCT_GROUP=seaice
ARRAYS=${SEAICE_ARRAYS:-$SEAICE_CONC}
SEAICE_FILELIST=${SEAICE_FILELIST:-https://github.com/mdsumner/aad-filelist/releases/download/latest/cdr_sic_G02202_V6.parquet}
if [ -n "${SEAICE_MIRROR:-}" ]; then SEAICE_ROOT="${SEAICE_MIRROR%/}/"
else SEAICE_ROOT=/vsicurl/https://; fi
sources() {
  "$PYTHON" "$HERE/py/filelist.py" --filelist "$SEAICE_FILELIST" --cache "$WORK/filelist.parquet" \
    --match "/G02202_V6/$SEAICE_HEM/$SEAICE_FREQ/" --date "$SEAICE_DATE" \
    ${SEAICE_FIRST:+--first "$SEAICE_FIRST"} ${SEAICE_LAST:+--last "$SEAICE_LAST"} \
    --prefix https:// "$SEAICE_ROOT" ${SEAICE_MIRROR:+--exists}
}
# Daily plan: py/plan_daily.py (from the OISST work) mosaics the first two
# files and extends the plan by date, so a missing day (2026-08-09/10) is a
# hole and the 17,500 files are not each opened at plan time. Monthly (575
# files) and checkouts without plan_daily.py use gdal mdim mosaic.
if [ "$SEAICE_FREQ" = daily ] && [ -f "$HERE/py/plan_daily.py" ]; then
  make_plan() {
    local arr=(); for a in $ARRAYS; do arr+=(--array "$a"); done
    "$PYTHON" "$HERE/py/plan_daily.py" --sources "$WORK/sources.txt" "${arr[@]}" \
      --pattern "$SEAICE_DATE" --check "${PLAN_CHECK:-8}" --gdal "$GDAL" "$WORK/plan.vrt"
  }
fi
# target|prefix|replacement, applied at publish only (sources stay verbatim);
# without SEAICE_MIRROR only the first rule matches
REMAPS=("public|/vsicurl/https://|https://")
if [ -n "${SEAICE_MIRROR:-}" ]; then
  REMAPS+=("public|$SEAICE_ROOT|https://" "gdal|$SEAICE_ROOT|/vsicurl/https://")
fi
# one STAC item file per day is 17,500 uploads: keep the ndjson and
# stac-geoparquet item forms only, so a publish fits the source.coop key hour
if [ "$SEAICE_FREQ" = daily ]; then export STAC_ITEM_FILES=${STAC_ITEM_FILES:-0}; fi
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-8}

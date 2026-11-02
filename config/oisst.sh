# NOAA OISST v2.1 AVHRR daily, 1/4 degree, 1981-09-01 onward: one netCDF4
# file per day on the public NOAA bucket (AWS us-east-1), four arrays
# (sst anom err ice), each one chunk of 1 x 1 x 720 x 1440 per file. Sources
# are listed from the bucket and recorded as /vsicurl/https URLs.
#
#   OISST_MONTHS       YYYYMM folders to include, space separated (default
#                      every folder in the bucket); the dataset name gets a
#                      -<months> suffix, so a subset never overwrites the full
#                      series. OISST_MONTHS=198109 is the 30-day dry run.
#   OISST_PRELIMINARY  0 (default): final files only. 1: add the
#                      preliminary file of each date that has no final file
#                      yet (the newest two weeks or so). NOAA keeps
#                      preliminary files in the bucket beside the final
#                      ones, so the references stay valid, but a rebuild
#                      then points those dates at the final files.
#   OISST_MIRROR       a local directory holding the same YYYYMM/ folders
#                      (the raad copy). A date whose local file has the
#                      bucket object's name and size is harvested from it
#                      and remapped to the bucket URL at publish; other
#                      dates are read from the bucket. OISST_MD5=1 also
#                      compares each local file's MD5 with the bucket ETag.
#
# The file list comes from py/oisst_sources.py (anonymous S3 listing).
# The plan is py/plan_daily.py: `gdal mdim mosaic` of the first two files,
# extended to every file (the mosaic opens every source, about 1 s each over
# /vsicurl/, hours for the full series). It opens a sample of files to check
# the time value and shapes.
OISST_URL=https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com/data/v2.1/avhrr
DATASET=oisst-v2.1-daily${OISST_MONTHS:+-$(echo $OISST_MONTHS | tr ' ' '-')}
# product group (products/oisst/): the scratch prefix on source.coop
PRODUCT_GROUP=oisst
ARRAYS="sst anom err ice"
OISST_PATTERN='oisst-avhrr-v02r01\.([0-9]{8})(_preliminary)?\.nc$'
[ -z "${OISST_MIRROR:-}" ] || OISST_MIRROR="${OISST_MIRROR%/}/"
sources() {
  local flags=()
  [ "${OISST_PRELIMINARY:-0}" = 1 ] && flags+=(--preliminary)
  [ -n "${OISST_MIRROR:-}" ] && flags+=(--mirror "$OISST_MIRROR")
  [ "${OISST_MD5:-0}" = 1 ] && flags+=(--md5)
  "$PYTHON" "$HERE/py/oisst_sources.py" --months "${OISST_MONTHS:-}" ${flags[@]+"${flags[@]}"}
}
make_plan() {
  arr=(); for a in $ARRAYS; do arr+=(--array "$a"); done
  "$PYTHON" "$HERE/py/plan_daily.py" --sources "$WORK/sources.txt" "${arr[@]}" \
    --pattern "$OISST_PATTERN" --gdal "$GDAL" "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim);
# without OISST_MIRROR only the first rule matches
REMAPS=("public|/vsicurl/https://|https://")
if [ -n "${OISST_MIRROR:-}" ]; then
  REMAPS+=("public|$OISST_MIRROR|$OISST_URL/" "gdal|$OISST_MIRROR|/vsicurl/$OISST_URL/")
fi
# one STAC item file per day is 16,500 uploads: keep the ndjson and
# stac-geoparquet item forms only, so a publish fits the source.coop key hour
export STAC_ITEM_FILES=${STAC_ITEM_FILES:-0}
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-16}

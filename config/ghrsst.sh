# GHRSST MUR v4.1 L4 daily (JPL), 0.01 degree global, from 2002-06-01:
# one file a day, analysed_sst and friends at 17999 x 36000, chunked
# 1 x 1023 x 2047 (about 324 chunks per array per file).
#
#   GHRSST_ROOT    directory holding the netCDF files, searched recursively
#                  (required; for example a raad mirror of
#                  .../ghrsst/data/GDS2/L4/GLOB/JPL/MUR/v4.1)
#   GHRSST_YEARS   years to include (default all found)
#   GHRSST_PUBLIC  "prefix|replacement" turning local paths into URLs readers
#                  can fetch, used for kerchunk and Icechunk; without it the
#                  published forms keep the local paths
#   GHRSST_ARRAYS  default "analysed_sst analysis_error mask sea_ice_fraction"
#                  (later files add sst_anomaly and dt_1km_data; earlier ones
#                  do not, so they are left out)
: "${GHRSST_ROOT:?set GHRSST_ROOT to the directory of MUR v4.1 netCDF files}"
DATASET=ghrsst-mur-v4.1${GHRSST_YEARS:+-$(echo $GHRSST_YEARS | tr ' ' '-')}
ARRAYS="${GHRSST_ARRAYS:-analysed_sst analysis_error mask sea_ice_fraction}"
sources() {
  local pat='*-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v4.1.nc'
  if [ -n "${GHRSST_YEARS:-}" ]; then
    for y in $GHRSST_YEARS; do find "$GHRSST_ROOT" -name "$y$pat"; done
  else
    find "$GHRSST_ROOT" -name "$pat"
  fi | awk -F/ '{print $NF "\t" $0}' | sort | cut -f2   # date order, by file name
}
if [ -n "${GHRSST_PUBLIC:-}" ]; then
  REMAPS=("public|$GHRSST_PUBLIC")
  KERCHUNK_TARGET=public
  ICECHUNK_TARGET=public
else
  REMAPS=()
  KERCHUNK_TARGET=""
  ICECHUNK_TARGET=""
fi
VRT_TARGET=""
WORKERS=${WORKERS:-8}

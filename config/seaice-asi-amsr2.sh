# University of Bremen ASI sea ice concentration from AMSR2, v5.4, daily,
# 3.125 km polar stereographic grid (https://seaice.uni-bremen.de/
# sea-ice-concentration/amsre-amsr2; Spreen et al. 2008,
# doi:10.1029/2005JC003384; Melsheimer and Spreen 2019,
# doi:10.1594/PANGAEA.898400). One netCDF4 file per day from 2012-08-01,
# served anonymously over HTTPS:
#
#   https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/s3125/netcdf/<year>/
#       asi-AMSR2-s3125-<YYYYMMDD>-v5.4.nc
#
# South grid 2528 x 2656 (x -3950000..3950000, y -3950000..4350000 m),
# Hughes 1980 ellipsoid (a 6378273, b 6356889.449), true scale at 70 S. Each
# file holds one 2D field (z, concentration 0..100) with no time dimension,
# so the plan is py/plan_lift.py, which stacks the files on a new time axis
# (the date in the file name); missing days (up to 3 in a row) are holes.
# z is float32, fill NaN, 0..100, in row chunks of 1 x 2528 with shuffle and
# deflate 9 (2656 chunks a file); x and y are contiguous float64.
#
#   SEAICE_HEM=south          south (s3125) or north (n3125); the raad
#                             collection holds south only (2026-11-02)
#   SEAICE_FIRST, SEAICE_LAST bounds on the file date, YYYYMMDD, inclusive;
#                             for a smoke test (the dataset name gets them)
#   SEAICE_ARRAYS             default z
#   SEAICE_MIRROR             the raad data root (as for seaice-g02202.sh),
#                             holding seaice.uni-bremen.de/data/amsr2/
#                             asi_daygrid_swath/<grid>/netcdf/<year>/. A date
#                             whose local file has the server file's name and
#                             size is harvested from it and remapped to the
#                             server URL at publish; any other date is read
#                             from the server. Bremen reprocessed the record
#                             on 2024-05-29 (and 2018 on 2026-04-25), so an
#                             old mirror file is not the published file.
#   SEAICE_OFFLINE=1          list the mirror only, no server check (refs
#                             are remapped unchecked; for a smoke test)
#   SEAICE_LIST=corpus        the file list and sizes come from the
#                             aad-filelist listing corpus (source
#                             amsr2_asi_s3125, south grid only); server:
#                             list the index and HEAD every file
#   SEAICE_SRS=file           the plan's SRS. Default file: the files' own
#                             label, EPSG:3976 (WGS 84 / NSIDC Sea Ice Polar
#                             Stereographic, WGS 84 ellipsoid). Any other
#                             value (PROJ string, EPSG:n, WKT) overrides it;
#                             hughes gives the Hughes 1980 form raadtools has
#                             long used (a 6378273), which is wrong for v5.4.
SEAICE_HEM=${SEAICE_HEM:-south}
case "$SEAICE_HEM" in
  south) ASI_GRID=s3125
         ASI_SRS='+proj=stere +lat_0=-90 +lat_ts=-70 +lon_0=0 +x_0=0 +y_0=0 +a=6378273 +b=6356889.449 +units=m +no_defs' ;;
  north) ASI_GRID=n3125
         ASI_SRS='+proj=stere +lat_0=90 +lat_ts=70 +lon_0=-45 +x_0=0 +y_0=0 +a=6378273 +b=6356889.449 +units=m +no_defs' ;;
  *) echo "SEAICE_HEM must be south or north" >&2; exit 1 ;;
esac
SEAICE_SRS=${SEAICE_SRS:-file}
if [ "$SEAICE_SRS" = hughes ]; then SEAICE_SRS=$ASI_SRS; fi
ASI_URL=https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/$ASI_GRID/netcdf
DATASET=asi-amsr2-v5.4-daily-$SEAICE_HEM${SEAICE_FIRST:+-$SEAICE_FIRST}${SEAICE_LAST:+-$SEAICE_LAST}
# product group (products/seaice/): the scratch prefix on source.coop
PRODUCT_GROUP=seaice
ARRAYS=${SEAICE_ARRAYS:-z}
ASI_PATTERN='-([0-9]{8})-v[0-9.]+\.nc$'
ASI_MIRROR=
if [ -n "${SEAICE_MIRROR:-}" ]; then
  ASI_MIRROR="${SEAICE_MIRROR%/}/seaice.uni-bremen.de/data/amsr2/asi_daygrid_swath/$ASI_GRID/netcdf/"
fi
sources() {
  local flags=()
  [ -n "$ASI_MIRROR" ] && flags+=(--mirror "$ASI_MIRROR")
  [ "${SEAICE_OFFLINE:-0}" = 1 ] && flags+=(--offline)
  # the listing corpus lists the south grid (source amsr2_asi_s3125);
  # SEAICE_LIST=server lists the index and HEADs every file instead
  [ "${SEAICE_LIST:-corpus}" = corpus ] && [ "$ASI_GRID" = s3125 ] && flags+=(--corpus amsr2_asi_s3125)
  "$PYTHON" "$HERE/py/bremen_sources.py" --base "$ASI_URL" --meta "$WORK/sources.meta.tsv" --meta-source "amsr2_asi_$ASI_GRID" \
    ${SEAICE_FIRST:+--first "$SEAICE_FIRST"} ${SEAICE_LAST:+--last "$SEAICE_LAST"} \
    ${flags[@]+"${flags[@]}"}
}
make_plan() {
  local a srs=()
  [ "$SEAICE_SRS" = file ] || srs=(--srs "$SEAICE_SRS" --srs-override)
  for a in $ARRAYS; do
    # one plan per array would need a merge; the product has one array
    "$PYTHON" "$HERE/py/plan_lift.py" --sources "$WORK/sources.txt" --array "$a" \
      --pattern="$ASI_PATTERN" ${srs[@]+"${srs[@]}"} --check "${PLAN_CHECK:-8}" "$WORK/plan.vrt"
    break
  done
}
# target|prefix|replacement, applied at publish only (sources stay verbatim);
# without SEAICE_MIRROR only the first rule matches
REMAPS=("public|/vsicurl/https://|https://")
if [ -n "$ASI_MIRROR" ]; then
  REMAPS+=("public|$ASI_MIRROR|$ASI_URL/" "gdal|$ASI_MIRROR|/vsicurl/$ASI_URL/")
fi
# one STAC item file per day is 5,000+ uploads: keep the ndjson and
# stac-geoparquet item forms only
export STAC_ITEM_FILES=${STAC_ITEM_FILES:-0}
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-8}
# thumbnail: concentration, dark blue (open water) to white
export STAC_THUMB_PALETTE=${STAC_THUMB_PALETTE:-ice}

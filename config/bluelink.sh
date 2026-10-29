# Bluelink daily or monthly: BRAN2020 before BRAN2023, one array across both reanalysis
# versions (the coalescing in mdsumner/bluelink). Both versions share grid
# (51 x 1500 x 3600), chunking (1 x 1 x 300 x 300), codecs (shuffle + zlib 1)
# and packing (scale 0.00778222, offset 245, fill -32768) for temp, so one
# Zarr array holds both; collate stops if the packing of a source differs.
#
#   BRAN_VAR=temp             variable (file pattern ocean_<var>[_mth]_YYYY_MM.nc)
#   BLUELINK_FREQ=daily       daily or month: the gb6 folder, and _mth in the
#                             monthly file names; the dataset is
#                             bluelink-<freq>-<var>
#   BLUELINK_FIRST=1993       first year (BRAN2020 starts in 1993)
#   BLUELINK_SWITCH=2010      first year taken from BRAN2023 (it starts in 2010;
#                             BRAN2020 covers to 2023 and is used before this)
#   BLUELINK_LAST=2026_07     last month, YYYY_MM; with BRAN_ROOT=gdata the
#                             default is the last BRAN2023 file on disk
#   BRAN_ROOT=thredds|gdata   as in config/bran.sh
case "${BLUELINK_FREQ:-daily}" in
  daily) FREQ_DIR=daily; FREQ_TAG= ;;
  month) FREQ_DIR=month; FREQ_TAG=_mth ;;
  *) echo "BLUELINK_FREQ must be daily or month" >&2; exit 1 ;;
esac
DATASET=bluelink-${BLUELINK_FREQ:-daily}-${BRAN_VAR:-temp}
ARRAYS="${BRAN_VAR:-temp}"
THREDDS="https://thredds.nci.org.au/thredds/fileServer/gb6/BRAN"
case "${BRAN_ROOT:-thredds}" in
  thredds) BASE="/vsicurl/$THREDDS" ;;
  gdata)   BASE="/g/data/gb6/BRAN" ;;
  *)       BASE="$BRAN_ROOT" ;;
esac
sources() {
  local v=${BRAN_VAR:-temp} first=${BLUELINK_FIRST:-1993} switch=${BLUELINK_SWITCH:-2010}
  local last=${BLUELINK_LAST:-}
  if [ -z "$last" ] && [ -d "$BASE/BRAN2023/$FREQ_DIR" ]; then
    last=$(ls "$BASE/BRAN2023/$FREQ_DIR" | grep -E "^ocean_${v}${FREQ_TAG}_[0-9]{4}_[0-9]{2}\.nc$" | sort | tail -1 |
           sed -E "s/^ocean_${v}${FREQ_TAG}_([0-9]{4}_[0-9]{2})\.nc$/\1/")
  fi
  : "${last:?set BLUELINK_LAST=YYYY_MM (the last BRAN2023 month)}"
  local y m
  for y in $(seq "$first" "${last%_*}"); do
    for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
      [[ "${y}_$m" > "$last" ]] && break
      if [ "$y" -lt "$switch" ]; then echo "$BASE/BRAN2020/$FREQ_DIR/ocean_${v}${FREQ_TAG}_${y}_${m}.nc"
      else echo "$BASE/BRAN2023/$FREQ_DIR/ocean_${v}${FREQ_TAG}_${y}_${m}.nc"; fi
    done
  done
}
REMAPS=("public|/vsicurl/https://|https://"
        "public|/g/data/gb6/|https://thredds.nci.org.au/thredds/fileServer/gb6/"
        "gdal|/g/data/gb6/|/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-8}

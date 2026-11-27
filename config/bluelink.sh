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
#   GDATA_LISTINGS=DIR        with BRAN_ROOT=gdata: select the files from the
#                             /g/data listing of source gdata_gb6_bran in DIR
#                             (py/gdata_listing.py, kept by the standing job,
#                             hpc/nci/standing.pbs) instead of ls, and write
#                             the build record $WORK/sources.meta.tsv, so the
#                             store can be stale-checked and collected
case "${BLUELINK_FREQ:-daily}" in
  daily) FREQ_DIR=daily; FREQ_TAG= ;;
  month) FREQ_DIR=month; FREQ_TAG=_mth ;;
  *) echo "BLUELINK_FREQ must be daily or month" >&2; exit 1 ;;
esac
DATASET=bluelink-${BLUELINK_FREQ:-daily}-${BRAN_VAR:-temp}
# product group (products/bluelink/): the scratch prefix on source.coop
PRODUCT_GROUP=bluelink
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
  if [ -n "${GDATA_LISTINGS:-}" ]; then
    [ "${BRAN_ROOT:-thredds}" = gdata ] || { echo "GDATA_LISTINGS needs BRAN_ROOT=gdata" >&2; return 1; }
    # one corpus.py call per reanalysis version: both hold 2010-2023, so a
    # single call would see two files for one month
    local re="_([0-9]{4}_[0-9]{2})\\.nc\$" m20="$WORK/sources.meta.bran2020.tsv" m23="$WORK/sources.meta.bran2023.tsv"
    "$PYTHON" "$HERE/py/corpus.py" --corpus "$GDATA_LISTINGS" --source gdata_gb6_bran \
      --match "/BRAN2020/$FREQ_DIR/ocean_${v}${FREQ_TAG}_[0-9]{4}_[0-9]{2}\\.nc\$" --date "$re" \
      --first "${first}_01" --last "$((switch - 1))_12" --meta "$m20" || return 1
    "$PYTHON" "$HERE/py/corpus.py" --corpus "$GDATA_LISTINGS" --source gdata_gb6_bran \
      --match "/BRAN2023/$FREQ_DIR/ocean_${v}${FREQ_TAG}_[0-9]{4}_[0-9]{2}\\.nc\$" --date "$re" \
      --first "${switch}_01" ${last:+--last "$last"} --meta "$m23" || return 1
    { cat "$m20"; tail -n +2 "$m23"; } > "$WORK/sources.meta.tsv"
    rm -f "$m20" "$m23"
    return 0
  fi
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
        "public|/g/data/gb6/|https://thredds.nci.org.au/thredds/fileServer/gb6/|bran2023"
        "gdal|/g/data/gb6/|/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/|bran2023")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
# verify reads the plan's sources (/g/data paths, built on NCI) through
# THREDDS, as the gdal target does, where /g/data/gb6 is not mounted
[ -d /g/data/gb6 ] ||
  VERIFY_PLAN_REMAP=${VERIFY_PLAN_REMAP-/g/data/gb6/=/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/}
WORKERS=${WORKERS:-8}

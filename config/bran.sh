# BRAN2023 daily `temp` (CSIRO Bluelink reanalysis): the heavy run.
# Monthly files ocean_temp_YYYY_MM.nc, 28-31 days x 51 depths x 1500 x 3600,
# chunked 1 x 1 x 300 x 300 int16 (shuffle + zlib): 3060 chunks per day,
# ~95k per file, ~1.1M per year. Start with one year.
#
#   BRAN_YEARS="2010"             years to include (space separated)
#   BRAN_MONTHS="01"              months to include (default all 12); a subset
#                                 gets its own DATASET name, for smoke tests
#   BRAN_ROOT=thredds (default)   scan over /vsicurl/ from NCI THREDDS
#   BRAN_ROOT=gdata               scan in situ on NCI (/g/data/gb6, gadi or ARE)
#   BRAN_VAR=temp                 also salt, eta_t, ... (same file pattern
#                                 ocean_<var>_YYYY_MM.nc; u/v are on another grid)
DATASET=bran2023-daily-${BRAN_VAR:-temp}${BRAN_MONTHS:+-smoke}
ARRAYS="${BRAN_VAR:-temp}"
THREDDS="https://thredds.nci.org.au/thredds/fileServer/gb6/BRAN/BRAN2023/daily"
case "${BRAN_ROOT:-thredds}" in
  thredds) BASE="/vsicurl/$THREDDS" ;;
  gdata)   BASE="/g/data/gb6/BRAN/BRAN2023/daily" ;;
  *)       BASE="$BRAN_ROOT" ;;
esac
sources() {
  for y in ${BRAN_YEARS:-2010}; do
    for m in ${BRAN_MONTHS:-01 02 03 04 05 06 07 08 09 10 11 12}; do
      echo "$BASE/ocean_${BRAN_VAR:-temp}_${y}_${m}.nc"
    done
  done
}
# public: plain https for kerchunk / Icechunk; gdal: /vsicurl/ for a VRT
# anyone can open. Both cover the THREDDS and the in-situ /g/data sources.
REMAPS=("public|/vsicurl/https://|https://"
        "public|/g/data/gb6/|https://thredds.nci.org.au/thredds/fileServer/gb6/"
        "gdal|/g/data/gb6/|/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=gdal
WORKERS=${WORKERS:-8}

# OISST v2.1, September 1981 (30 days, 4 arrays, one chunk per file):
# the dry run. Sources over HTTPS from the public NOAA bucket.
DATASET=noaa-oisst-avhrr-v2.1-198109
ARRAYS="sst anom err ice"
BASE="/vsicurl/https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.amazonaws.com/data/v2.1/avhrr"
sources() {
  for d in $(seq -w 1 30); do echo "$BASE/198109/oisst-avhrr-v02r01.198109$d.nc"; done
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=""
WORKERS=${WORKERS:-4}

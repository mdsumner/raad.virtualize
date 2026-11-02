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
#
# The plan is py/plan_daily.py: `gdal mdim mosaic` of the first two files,
# extended to every file (the mosaic opens every source, about 1 s each over
# /vsicurl/, hours for the full series). It opens a sample of files to check
# the time value and shapes.
OISST_BUCKET=noaa-cdr-sea-surface-temp-optimum-interpolation-pds
OISST_ROOT=data/v2.1/avhrr
DATASET=oisst-v2.1-daily${OISST_MONTHS:+-$(echo $OISST_MONTHS | tr ' ' '-')}
# product group (products/oisst/): the scratch prefix on source.coop
PRODUCT_GROUP=oisst
ARRAYS="sst anom err ice"
OISST_PATTERN='oisst-avhrr-v02r01\.([0-9]{8})(_preliminary)?\.nc$'
sources() (
  # anonymous listing of the NOAA bucket; a publish config sourced before
  # this one may have set the S3 endpoint to another service
  export AWS_NO_SIGN_REQUEST=YES AWS_S3_ENDPOINT=s3.amazonaws.com AWS_VIRTUAL_HOSTING=TRUE \
         AWS_HTTPS=YES AWS_REGION=us-east-1
  root=/vsis3/$OISST_BUCKET/$OISST_ROOT
  url=/vsicurl/https://$OISST_BUCKET.s3.amazonaws.com/$OISST_ROOT
  months=${OISST_MONTHS:-$("$GDAL" vsi ls "$root" | grep -E '^[0-9]{6}$')}
  for m in $months; do
    "$GDAL" vsi ls "$root/$m" | grep -E "$OISST_PATTERN" | sed "s#^#$url/$m/#"
  done |
    # one file per date: final, else (OISST_PRELIMINARY=1) preliminary
    awk -v pre="${OISST_PRELIMINARY:-0}" '
      { f = $0; sub(/.*\//, "", f); d = substr(f, 20, 8)
        if (f ~ /_preliminary\.nc$/) { if (pre == 1 && !(d in fin)) prel[d] = $0 }
        else fin[d] = $0 }
      END { for (d in fin) print d "\t" fin[d]
            for (d in prel) if (!(d in fin)) print d "\t" prel[d] }' |
    sort | cut -f2
)
make_plan() {
  arr=(); for a in $ARRAYS; do arr+=(--array "$a"); done
  "$PYTHON" "$HERE/py/plan_daily.py" --sources "$WORK/sources.txt" "${arr[@]}" \
    --pattern "$OISST_PATTERN" --gdal "$GDAL" "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=""
WORKERS=${WORKERS:-16}

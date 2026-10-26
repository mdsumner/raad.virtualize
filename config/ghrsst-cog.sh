# GHRSST MUR v4.1 L4 daily as Cloud Optimized GeoTIFFs on source.coop
# (ausantarctic/ghrsst-mur-v2): one COG per variable per day, 36000 x 17999
# Int16, 512 x 512 tiles, ZSTD with PREDICTOR=2, from 2002-06-01 (about
# 2556 tiles per day, 22.8M for the full series).
#
#   GHRSST_VAR       variable (file name suffix), default analysed_sst
#   GHRSST_YEARS     years to include (default every year in the bucket)
#   GHRSST_COG_ROOT  default /vsis3/ausantarctic/ghrsst-mur-v2 (listed
#                    anonymously from data.source.coop; sources are recorded
#                    as /vsicurl/https://data.source.coop/...). A local
#                    directory of the same YYYY/MM/DD layout also works.
#
# MUR rewrites its newest days for several days after first publication:
# rerun with HARVEST_RECHECK=30 to rescan any of the last 30 days that changed.
#
# gdal mdim mosaic does not take GeoTIFF, so the plan is py/plan_cog.py (the
# vrtstack form). PREDICTOR=2 maps to the imagecodecs_delta filter: the
# kerchunk and Icechunk forms need imagecodecs in the reader, and GDAL reads
# neither (the VRT form is unaffected).
GHRSST_VAR=${GHRSST_VAR:-analysed_sst}
GHRSST_COG_ROOT=${GHRSST_COG_ROOT:-/vsis3/ausantarctic/ghrsst-mur-v2}
DATASET=ghrsst-mur-cog-$GHRSST_VAR${GHRSST_YEARS:+-$(echo $GHRSST_YEARS | tr ' ' '-')}
ARRAYS=$GHRSST_VAR
GHRSST_PATTERN="^([0-9]{8})090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02\.0-fv04\.1_${GHRSST_VAR}\.tif\$"
sources() (
  root=$GHRSST_COG_ROOT; url=$root
  if [[ $root == /vsis3/ausantarctic/* ]]; then
    export AWS_NO_SIGN_REQUEST=YES AWS_S3_ENDPOINT=data.source.coop AWS_VIRTUAL_HOSTING=FALSE
    url=/vsicurl/https://data.source.coop/${root#/vsis3/}
  fi
  years=${GHRSST_YEARS:-$("$GDAL" vsi ls "$root" | grep -E '^[0-9]{4}$')}
  for y in $years; do
    "$GDAL" vsi ls -R "$root/$y" | grep -E "(^|/)${GHRSST_PATTERN#^}" | sed "s#^#$url/$y/#"
  done | awk -F/ '{print $NF "\t" $0}' | sort | cut -f2   # date order, by file name
)
make_plan() {
  "$PYTHON" "$HERE/py/plan_cog.py" --sources "$WORK/sources.txt" --array "$GHRSST_VAR" \
    --pattern "$GHRSST_PATTERN" "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=""
WORKERS=${WORKERS:-8}

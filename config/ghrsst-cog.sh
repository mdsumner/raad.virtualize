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
#   GHRSST_OVERVIEWS 1 (default): every overview level of the cogger COGs
#                    is an array of its own (py/plan_cog.py --overviews;
#                    resampling recorded as unknown, it is cogger's); about
#                    a third more refs (30.5M rows against 22.77M). 0: IFD 0
#                    only, as the first scratch stores
#   GHRSST_HOLD_BACK_DAYS  index only days at least this many days old, by
#                    the date in the file name against today (UTC); default
#                    17. ghrsst-cogger rewrites a day's COGs at the same key
#                    about 5 days after the date, and upstream MUR granules
#                    were seen to change up to 16 days after it (aad-filelist
#                    corpus, podaac_mur_sst_v41, November 2026). A byte
#                    reference to a rewritten COG reads the wrong bytes, so
#                    days inside the window stay out of the store. 0: no
#                    hold-back
#   GHRSST_LAST      last day to index, YYYYMMDD (default none); the earlier
#                    of this and the hold-back date applies
#   GHRSST_MAX_MISSING  days between the first and last file allowed to have
#                    no file (default 0): the plan step stops on more, so a
#                    listing cut short by server errors is not published
#   GRIST_VERIFY_WINDOW  side of the window py/verify_grist.py reads from each
#                    checked field (default 2048; a whole field is 1.3 GB)
#
# Harvest skips a source whose fragments exist, so a work directory that
# scanned days inside the window (before GHRSST_HOLD_BACK_DAYS) holds scans of
# COGs since rewritten: remove those fragments (scan/sources/<key>.json and
# scan/chunks_*/<key>.parquet), or rerun with HARVEST_RECHECK=N to rescan any
# of the last N sources whose size or mtime changed.
#
# gdal mdim mosaic does not take GeoTIFF, so the plan is py/plan_cog.py (the
# vrtstack form). PREDICTOR=2 maps to the imagecodecs_delta filter: the
# kerchunk and Icechunk forms need imagecodecs in the reader, and GDAL reads
# neither (the VRT form is unaffected).
GHRSST_VAR=${GHRSST_VAR:-analysed_sst}
GHRSST_COG_ROOT=${GHRSST_COG_ROOT:-/vsis3/ausantarctic/ghrsst-mur-v2}
DATASET=ghrsst-mur-cog-$GHRSST_VAR${GHRSST_YEARS:+-$(echo $GHRSST_YEARS | tr ' ' '-')}
# product group (products/ghrsst/): the scratch prefix on source.coop
PRODUCT_GROUP=ghrsst
ARRAYS=$GHRSST_VAR
GHRSST_PATTERN="^([0-9]{8})090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02\.0-fv04\.1_${GHRSST_VAR}\.tif\$"
GHRSST_HOLD_BACK_DAYS=${GHRSST_HOLD_BACK_DAYS:-17}
# the last day indexed: today less the hold-back, or GHRSST_LAST if earlier
ghrsst_last=$(date -u -d "-$GHRSST_HOLD_BACK_DAYS days" +%Y%m%d)
if [ -n "${GHRSST_LAST:-}" ] && [ "$GHRSST_LAST" \< "$ghrsst_last" ]; then ghrsst_last=$GHRSST_LAST; fi
sources() (
  root=$GHRSST_COG_ROOT; url=$root
  if [[ $root == /vsis3/ausantarctic/* ]]; then
    export AWS_NO_SIGN_REQUEST=YES AWS_S3_ENDPOINT=data.source.coop AWS_VIRTUAL_HOSTING=FALSE
    url=/vsicurl/https://data.source.coop/${root#/vsis3/}
  fi
  years=${GHRSST_YEARS:-$("$GDAL" vsi ls "$root" | grep -E '^[0-9]{4}$')}
  for y in $years; do
    "$GDAL" vsi ls -R "$root/$y" | grep -E "(^|/)${GHRSST_PATTERN#^}" | sed "s#^#$url/$y/#"
  done | awk -F/ -v last="$ghrsst_last" 'substr($NF, 1, 8) <= last {print $NF "\t" $0}' |
    sort | cut -f2   # date order, by file name; nothing after the last day
)
make_plan() {
  "$PYTHON" "$HERE/py/plan_cog.py" --sources "$WORK/sources.txt" --array "$GHRSST_VAR" \
    --pattern "$GHRSST_PATTERN" --max-missing "${GHRSST_MAX_MISSING:-0}" \
    $([ "${GHRSST_OVERVIEWS:-1}" = 1 ] && echo --overviews) "$WORK/plan.vrt"
}
# target|prefix|replacement, applied at publish only (sources stay verbatim)
REMAPS=("public|/vsicurl/https://|https://")
KERCHUNK_TARGET=public
ICECHUNK_TARGET=public
VRT_TARGET=""
WORKERS=${WORKERS:-8}
GRIST_VERIFY_WINDOW=${GRIST_VERIFY_WINDOW:-2048}

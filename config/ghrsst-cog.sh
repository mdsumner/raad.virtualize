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
#   GHRSST_MAX_MISSING  days between the first and last file allowed to have
#                    no file (default 0): the plan step stops on more, so a
#                    listing cut short by server errors is not published
#   GRIST_VERIFY_WINDOW  side of the window py/verify_grist.py reads from each
#                    checked field (default 2048; a whole field is 1.3 GB)
#
#   GHRSST_HOLD_BACK days (default 17) between a file's date and the time
#                    the listing was taken before the file is indexed: see
#                    below. 0 indexes every listed day
#   GHRSST_LISTER    corpus (default for the source.coop root) or vsi.
#                    corpus: the file list is source ausantarctic-ghrsst-mur-v2
#                    of the aad-filelist listing corpus (py/corpus.py, S3
#                    ListObjectsV2 with size, mtime, etag), and what it knew
#                    of each file is written to $WORK/sources.meta.tsv, the
#                    build record the stale step checks. Run the aad-filelist
#                    sync first for a recent end date (the corpus is weekly).
#                    vsi: `gdal vsi ls` of GHRSST_COG_ROOT now (the only
#                    choice for a local directory); no build record, and the
#                    hold-back counts from today
#   CORPUS_BASE      corpus release or local copy (py/corpus.py)
#
# Hold-back: ghrsst-cogger rewrites each day's COGs at the same address
# about 5 days after the date, and upstream MUR itself revises a day for up
# to 16 days. A store harvested before the last rewrite holds byte offsets
# into the old file: the kerchunk and Icechunk forms then read wrong bytes
# or fail (the VRT form opens the file and is unaffected). The 3 Nov 2026
# scratch build had 7 such days. So the newest GHRSST_HOLD_BACK days are
# left out, and the stale step (run.sh ... stale) reports any indexed file
# that changed since. HARVEST_RECHECK=30 still rescans recent days that
# changed, for a work directory built without the hold-back.
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
GHRSST_HOLD_BACK=${GHRSST_HOLD_BACK:-17}
if [ -z "${GHRSST_LISTER:-}" ]; then
  if [ "$GHRSST_COG_ROOT" = /vsis3/ausantarctic/ghrsst-mur-v2 ]; then GHRSST_LISTER=corpus; else GHRSST_LISTER=vsi; fi
fi
case "$GHRSST_LISTER" in
  corpus)
    [ "$GHRSST_COG_ROOT" = /vsis3/ausantarctic/ghrsst-mur-v2 ] ||
      { echo "GHRSST_LISTER=corpus lists the source.coop bucket only; use GHRSST_LISTER=vsi for $GHRSST_COG_ROOT" >&2; exit 1; }
    sources() {
      local yrs=; [ -z "${GHRSST_YEARS:-}" ] || yrs="/($(echo $GHRSST_YEARS | tr ' ' '|'))/"
      "$PYTHON" "$HERE/py/corpus.py" --source ausantarctic-ghrsst-mur-v2 \
        --cache "$WORK/listing.parquet" --meta "$WORK/sources.meta.tsv" \
        --match "/${GHRSST_PATTERN#^}" ${yrs:+--match "$yrs"} --date "$GHRSST_PATTERN" \
        --hold-back "$GHRSST_HOLD_BACK" --prefix https:// /vsicurl/https://
    } ;;
  vsi)
    sources() (
      root=$GHRSST_COG_ROOT; url=$root
      if [[ $root == /vsis3/ausantarctic/* ]]; then
        export AWS_NO_SIGN_REQUEST=YES AWS_S3_ENDPOINT=data.source.coop AWS_VIRTUAL_HOSTING=FALSE
        url=/vsicurl/https://data.source.coop/${root#/vsis3/}
      fi
      last=99999999
      [ "$GHRSST_HOLD_BACK" = 0 ] || last=$(date -u -d "-$GHRSST_HOLD_BACK days" +%Y%m%d)
      echo "ghrsst: hold-back $GHRSST_HOLD_BACK days: last date kept $last" >&2
      years=${GHRSST_YEARS:-$("$GDAL" vsi ls "$root" | grep -E '^[0-9]{4}$')}
      for y in $years; do
        "$GDAL" vsi ls -R "$root/$y" | grep -E "(^|/)${GHRSST_PATTERN#^}" | sed "s#^#$url/$y/#"
      done | awk -F/ -v last="$last" '{d = substr($NF, 1, 8); if (d <= last) print $NF "\t" $0}' \
        | sort | cut -f2   # date order, by file name
    ) ;;
  *) echo "GHRSST_LISTER must be corpus or vsi" >&2; exit 1 ;;
esac
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

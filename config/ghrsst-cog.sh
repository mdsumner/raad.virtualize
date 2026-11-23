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
#   GHRSST_LISTER    cogger (default for the source.coop root) or vsi.
#                    cogger: ghrsst-cogger's own output is the list
#                    (py/ghrsst_sources.py: ListObjectsV2 of the bucket plus
#                    each recent day's STAC item), and its size, mtime and
#                    etag go to $WORK/sources.meta.tsv, the build record the
#                    stale step checks against the bucket. The aad-filelist
#                    corpus is not involved: cogger makes this dataset.
#                    vsi: `gdal vsi ls` of GHRSST_COG_ROOT (the only choice
#                    for a local directory); no build record
#   GHRSST_QUIET_DAYS  (cogger, default 3) days since cogger last wrote a
#                    day's COG before it is indexed
#   GHRSST_STATUS_DAYS (cogger, default 60) days back from the newest whose
#                    STAC item is read for ghrsst:status
#   GHRSST_HOLD_BACK (vsi, default 17) days between a file's date and today
#                    before it is indexed (no status is known there)
#
# Hold-back: ghrsst-cogger first writes a day from the interim (NRT) MUR
# file, its STAC item saying ghrsst:status "preliminary", then rewrites the
# same keys from the final MUR file a few days later ("final"). A store
# harvested before that rewrite holds byte offsets into the old file: the
# kerchunk and Icechunk forms then read wrong bytes or fail (the VRT form
# opens the file and is unaffected). The 3 Nov 2026 scratch build had 7
# such days. So a day is indexed only when cogger says final and has not
# written it for GHRSST_QUIET_DAYS, and every later day is held back with
# it; the stale step (run.sh ... stale) reports any indexed COG that changed
# since (a cogger reprocessing rewrites old days too). HARVEST_RECHECK=30
# still rescans recent days that changed, for an older work directory.
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
  if [ "$GHRSST_COG_ROOT" = /vsis3/ausantarctic/ghrsst-mur-v2 ]; then GHRSST_LISTER=cogger; else GHRSST_LISTER=vsi; fi
fi
case "$GHRSST_LISTER" in
  cogger)
    [ "$GHRSST_COG_ROOT" = /vsis3/ausantarctic/ghrsst-mur-v2 ] ||
      { echo "GHRSST_LISTER=cogger lists the source.coop bucket only; use GHRSST_LISTER=vsi for $GHRSST_COG_ROOT" >&2; exit 1; }
    ghrsst_lister() {
      "$PYTHON" "$HERE/py/ghrsst_sources.py" --var "$GHRSST_VAR" ${GHRSST_YEARS:+--years "$GHRSST_YEARS"} \
        --quiet "${GHRSST_QUIET_DAYS:-3}" --status-days "${GHRSST_STATUS_DAYS:-60}" "$@"
    }
    sources() { ghrsst_lister --meta "$WORK/sources.meta.tsv"; }
    # run.sh stale: the build record against the bucket now (not the corpus)
    stale_check() { ghrsst_lister --stale "$WORK/sources.meta.tsv" | tee "$WORK/stale.tsv"; } ;;
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

#!/usr/bin/env bash
# End-to-end write: sources -> plan (mdim mosaic VRT) -> byte-ref harvest ->
# byterefs/0.1 store -> flat refs store -> MDIM VRT, kerchunk Parquet,
# Icechunk -> verify. See README.md.
#
#   ./run.sh config/oisst.sh                 all steps
#   ./run.sh config/bran.sh harvest collate  some steps
#   ./run.sh config/bran.sh config/aadc-transfer.sh publish verify-published
#
# Every leading *.sh argument is sourced, in order (dataset, then a publish
# target). Steps: deps plan harvest collate render icechunk grist stac verify, and
# prepare publish publish-stac verify-published stale (not run by default).
# stale compares the build record (sources.meta.tsv) with the listing corpus.
# publish-stac republishes only stac/ and thumbnail.png. prepare runs the
# config's prepare function, for a dataset that writes its sources first.
# Env: E2E_WORK (default ./work/<DATASET>), PYTHON, RSCRIPT, GDAL, WORKERS,
#      HARVEST_LIMIT (scan only the first N sources; for a smoke test),
#      HARVEST_ENGINE (auto | gdal | h5py; see py/harvest.py),
#      R_LIB (default ./r-lib: R packages installed by the deps step),
#      ICECHUNK_ARGS (extra py/render_icechunk.py options, e.g. "--split 0"),
#      PUBLISH (a /vsis3/ prefix; set by config/aadc-transfer.sh),
#      PUBLISH_WITH (gdal, or obstore for py/s3_sync.py),
#      S3_SYNC_ARGS (extra py/s3_sync.py options, e.g. --skip-same-size to
#      resume a publish cut off by an expired token),
#      STAC_TARGET (remap target for STAC item hrefs; default KERCHUNK_TARGET),
#      STAC_BASE (public URL of the published dataset prefix, for absolute
#      STAC asset hrefs and GDAL open strings), STAC_ITEM_FILES (see
#      R/stac.R), STAC_GEOPARQUET, STAC_THUMBNAIL and STAC_THUMB_* (see the
#      stac step),
#      GRIST_LEVELS, GRIST_ARRAYS, GRIST_TARGET (default VRT_TARGET),
#      GRIST_BASE (default STAC_BASE), GRIST_VERIFY_BOUNDARIES,
#      GRIST_VERIFY_WINDOW (see R/grist.R and py/verify_grist.py),
#      DEFAULT_STEPS (steps when none are named; set by a config with no time
#      axis, which leaves out grist).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -ge 1 ] || { sed -n '2,26p' "$0"; exit 1; }
CONFIGS=()
while [ $# -ge 1 ] && [[ $1 == *.sh ]]; do source "$1"; CONFIGS+=("$(basename "$1")"); shift; done
# Provenance stamped into the store meta (and so into every rendered form).
# safe.directory: a container running as root may not own the checkout.
REV=$(git -c safe.directory="$HERE" -C "$HERE" describe --always --dirty 2>/dev/null || echo unversioned)
REPO=$(git -c safe.directory="$HERE" -C "$HERE" remote get-url origin 2>/dev/null | sed -E "s#//[^@/]*@#//#")
export E2E_GENERATOR="${E2E_REPO:-${REPO:-local}} $REV" E2E_CONFIG="${CONFIGS[*]}"
STEPS=${*:-${DEFAULT_STEPS:-plan harvest collate render icechunk grist stac verify}}
PYTHON=${PYTHON:-python}; RSCRIPT=${RSCRIPT:-Rscript}; GDAL=${GDAL:-gdal}
WORK=${E2E_WORK:-$HERE/work/$DATASET}
mkdir -p "$WORK"
R_LIB=${R_LIB:-$HERE/r-lib}
export R_LIBS="$R_LIB${R_LIBS:+:$R_LIBS}"
PUB=${PUBLISH:+${PUBLISH%/}/$DATASET}
LOG="$WORK/log.txt"
# unbuffered Python, so log.txt shows each verify window as it finishes
export PYTHONUNBUFFERED=1
export GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR GDAL_HTTP_MAX_RETRY=${GDAL_HTTP_MAX_RETRY:-5} \
       GDAL_HTTP_RETRY_DELAY=${GDAL_HTTP_RETRY_DELAY:-2}

step() {
  local name=$1; shift
  local t0=$SECONDS
  echo "== $name: $*" | tee -a "$LOG"
  "$@" 2>&1 | tee -a "$LOG"
  echo "== $name done in $((SECONDS - t0)) s" | tee -a "$LOG"
}

arr_flags=(); for a in $ARRAYS; do arr_flags+=(--array "$a"); done
for s in $STEPS; do
  case $s in
    deps)
      step deps "$RSCRIPT" "$HERE/R/install-deps.R" "$R_LIB" ;;
    prepare)
      declare -F prepare > /dev/null || { echo "prepare: the config defines no prepare"; exit 1; }
      step prepare prepare ;;
    plan)
      # sources go to the mosaic as a response file (@file): a full GHRSST
      # or multi-year BRAN listing is longer than the argument limit
      # sources() may also write the build record (sources.meta.tsv, for the
      # stale step); drop the last one so a lister that writes none leaves none
      rm -f "$WORK/sources.meta.tsv"
      sources > "$WORK/sources.txt"
      [ -s "$WORK/sources.txt" ] || { echo "plan: no sources"; exit 1; }
      # a config may define make_plan (sources.txt -> plan.vrt) for sources
      # the mosaic does not take, such as GeoTIFF
      if declare -F make_plan > /dev/null; then step plan make_plan
      else step plan "$GDAL" mdim mosaic --overwrite "${arr_flags[@]}" "@$WORK/sources.txt" "$WORK/plan.vrt"
      fi ;;
    harvest)
      step harvest "$PYTHON" "$HERE/py/harvest.py" --plan "$WORK/plan.vrt" --out "$WORK/scan" \
        "${arr_flags[@]}" --workers "$WORKERS" --engine "${HARVEST_ENGINE:-auto}" \
        ${HARVEST_LIMIT:+--limit "$HARVEST_LIMIT"} ${HARVEST_RECHECK:+--recheck "$HARVEST_RECHECK"} ;;
    collate)
      step collate "$RSCRIPT" "$HERE/R/collate.R" "$WORK/scan" "$WORK/plan.vrt" \
        "$WORK/store.sqlite" "$DATASET" ${REMAPS[@]+"${REMAPS[@]}"} ;;
    render)
      step render "$RSCRIPT" "$HERE/R/render.R" "$WORK/store.sqlite" "$WORK/out" \
        "$KERCHUNK_TARGET" "$VRT_TARGET" ;;
    icechunk)
      step icechunk "$PYTHON" "$HERE/py/render_icechunk.py" "$WORK/out/flat" \
        "$WORK/out/icechunk" --target "$ICECHUNK_TARGET" ${ICECHUNK_ARGS:-} ;;
    grist)
      # grist catalog (hypertidy/grist mdim contract): one row per date and
      # level, dsn the published mdim.vrt; before stac, which lists it
      step grist "$RSCRIPT" "$HERE/R/grist.R" "$WORK/store.sqlite" "$WORK/out" \
        "${GRIST_TARGET-$VRT_TARGET}" "${GRIST_BASE-${STAC_BASE:-}}" ;;
    stac)
      # after icechunk and grist: the collection lists every form present in out/.
      # A projected grid's lon/lat box comes from the plan (GDAL/OSR in Python)
      if [ -z "${STAC_BBOX:-}" ] && [ -f "$WORK/plan.vrt" ]; then
        STAC_BBOX=$("$PYTHON" "$HERE/py/plan_bbox.py" "$WORK/plan.vrt" || true)
        [ -z "$STAC_BBOX" ] || echo "stac: bbox $STAC_BBOX (py/plan_bbox.py)" | tee -a "$LOG"
      fi
      export STAC_BBOX
      # collection title: the dataset's row in its group's datasets.tsv
      # where the config sets none
      if [ -z "${STAC_TITLE:-}" ] && [ -n "${PRODUCT_GROUP:-}" ] && [ -f "$HERE/products/$PRODUCT_GROUP/datasets.tsv" ]; then
        STAC_TITLE=$(awk -F'\t' -v d="$DATASET" '!/^#/ && $1 == d {print $4; exit}' "$HERE/products/$PRODUCT_GROUP/datasets.tsv")
        export STAC_TITLE
      fi
      # overview image of one field (py/thumbnail.py), a collection asset;
      # a failure leaves the collection without one. STAC_THUMBNAIL=0 skips,
      # STAC_THUMB_ARRAY (default the first of ARRAYS), STAC_THUMB_PALETTE,
      # STAC_THUMB_LOG10=1 and STAC_THUMB_WIDTH choose what is drawn
      rm -f "$WORK/out/thumbnail.png"
      if [ "${STAC_THUMBNAIL:-1}" = 1 ]; then
        if desc=$("$PYTHON" "$HERE/py/thumbnail.py" "$WORK/store.sqlite" "$WORK/out/thumbnail.png" \
              --array "${STAC_THUMB_ARRAY:-${ARRAYS%% *}}" --palette "${STAC_THUMB_PALETTE:-viridis}" \
              --width "${STAC_THUMB_WIDTH:-512}" $([ "${STAC_THUMB_LOG10:-0}" = 1 ] && echo --log10) \
              2>> "$LOG"); then
          export STAC_THUMB_DESCRIPTION="Overview of $desc (py/thumbnail.py)."
          echo "stac: thumbnail $desc" | tee -a "$LOG"
        else
          rm -f "$WORK/out/thumbnail.png"; echo "stac: no thumbnail (py/thumbnail.py failed, see $LOG)" | tee -a "$LOG"
        fi
      fi
      # items as stac-geoparquet (rustac); the collection lists it only when
      # it is written. STAC_GEOPARQUET=0 skips
      want=${STAC_GEOPARQUET:-1}; STAC_GEOPARQUET=0
      if [ "$want" = 1 ] && "$PYTHON" "$HERE/py/stac_geoparquet.py" --check; then
        STAC_GEOPARQUET=1
      else
        echo "stac: no stac-geoparquet (pip install rustac)" | tee -a "$LOG"
      fi
      export STAC_GEOPARQUET
      step stac "$RSCRIPT" "$HERE/R/stac.R" "$WORK/store.sqlite" "$WORK/out" \
        "${STAC_TARGET-$KERCHUNK_TARGET}" "${STAC_BASE:-}"
      if [ "$STAC_GEOPARQUET" = 1 ]; then
        step stac "$PYTHON" "$HERE/py/stac_geoparquet.py" "$WORK/out/stac/items.ndjson" "$WORK/out/stac/items.parquet"
      fi ;;
    verify)
      step verify "$PYTHON" "$HERE/py/verify.py" --plan "$WORK/plan.vrt" --out "$WORK/out" \
        ${VERIFY_WINDOWS:-}
      # the catalog rows against their source granules, through the local VRT
      if [ -f "$WORK/out/grist/catalog.parquet" ]; then
        step verify "$PYTHON" "$HERE/py/verify_grist.py" --catalog "$WORK/out/grist/catalog.parquet" \
          --vrt "$WORK/out/mdim.vrt" --boundaries "${GRIST_VERIFY_BOUNDARIES:-8}" \
          --window "${GRIST_VERIFY_WINDOW:-0}"
      fi ;;
    publish)
      [ -n "$PUB" ] || { echo "publish: set PUBLISH or source a publish config"; exit 1; }
      # PUBLISH_WITH=obstore (config/source-coop.sh): py/s3_sync.py, for
      # endpoints that reject GDAL's request signing
      if [ "${PUBLISH_WITH:-gdal}" = obstore ]; then
        step publish "$PYTHON" "$HERE/py/s3_sync.py" ${S3_SYNC_ARGS:-} "$WORK/out" "$PUB"
        for f in plan.vrt store.sqlite sources.meta.tsv; do
          [ -f "$WORK/$f" ] && step publish "$PYTHON" "$HERE/py/s3_sync.py" ${S3_SYNC_ARGS:-} "$WORK/$f" "$PUB/$f"
        done
      else
        step publish "$GDAL" vsi sync -r -j 8 "$WORK/out/" "$PUB/"
        for f in plan.vrt store.sqlite sources.meta.tsv; do
          [ -f "$WORK/$f" ] && step publish "$GDAL" vsi copy "$WORK/$f" "$PUB/$f"
        done
      fi ;;
    publish-stac)
      # the STAC render and thumbnail only, after a stac step on a dataset
      # whose other forms are already published
      [ -n "$PUB" ] || { echo "publish-stac: set PUBLISH or source a publish config"; exit 1; }
      [ -f "$WORK/out/stac/collection.json" ] || { echo "publish-stac: no $WORK/out/stac; run the stac step"; exit 1; }
      if [ "${PUBLISH_WITH:-gdal}" = obstore ]; then
        step publish-stac "$PYTHON" "$HERE/py/s3_sync.py" ${S3_SYNC_ARGS:-} "$WORK/out/stac" "$PUB/stac"
        [ ! -f "$WORK/out/thumbnail.png" ] ||
          step publish-stac "$PYTHON" "$HERE/py/s3_sync.py" "$WORK/out/thumbnail.png" "$PUB/thumbnail.png"
      else
        step publish-stac "$GDAL" vsi sync -r "$WORK/out/stac/" "$PUB/stac/"
        [ ! -f "$WORK/out/thumbnail.png" ] ||
          step publish-stac "$GDAL" vsi copy "$WORK/out/thumbnail.png" "$PUB/thumbnail.png"
      fi ;;
    verify-published)
      [ -n "$PUB" ] || { echo "verify-published: set PUBLISH or source a publish config"; exit 1; }
      # obstore targets (source.coop) are public and their proxy rejects
      # GDAL's request signing: read back anonymously, as a public reader
      anon=; [ "${PUBLISH_WITH:-gdal}" = obstore ] && anon=AWS_NO_SIGN_REQUEST=YES
      step verify-published env $anon "$PYTHON" "$HERE/py/verify.py" --plan "$WORK/plan.vrt" --out "$WORK/out" \
        --published "$PUB" ${VERIFY_WINDOWS:-}
      # the published catalog read back from its public URL, each row's dsn
      # opened as written (as grist opens it)
      if [ -f "$WORK/out/grist/catalog.parquet" ]; then
        gcat=${GRIST_BASE-${STAC_BASE:-}}; gcat=${gcat:-$PUB}
        step verify-published "$PYTHON" "$HERE/py/verify_grist.py" \
          --catalog "${gcat%/}/grist/catalog.parquet" --require-url \
          --boundaries "${GRIST_VERIFY_BOUNDARIES:-8}" --window "${GRIST_VERIFY_WINDOW:-0}"
      fi ;;
    stale)
      # source files that changed or went away since the build, against the
      # listing corpus now (py/stale.py); STALE_ARGS e.g. --warn
      [ -f "$WORK/sources.meta.tsv" ] || { echo "stale: no $WORK/sources.meta.tsv (a config whose lister writes no build record)"; exit 1; }
      step stale "$PYTHON" "$HERE/py/stale.py" --meta "$WORK/sources.meta.tsv" \
        --out "$WORK/stale.tsv" ${STALE_ARGS:-} ;;
    *) echo "unknown step $s"; exit 1 ;;
  esac
done
du -sh "$WORK"/{plan.vrt,scan,store.sqlite,out/*} 2>/dev/null | tee -a "$LOG" || true

#!/usr/bin/env bash
# End-to-end write: sources -> plan (mdim mosaic VRT) -> byte-ref harvest ->
# mdim-refs/0.2 store -> flat refs store -> MDIM VRT, kerchunk Parquet,
# Icechunk -> verify. See README.md.
#
#   ./run.sh config/oisst.sh                 all steps
#   ./run.sh config/bran.sh harvest collate  some steps
#   ./run.sh config/bran.sh config/aadc-transfer.sh publish verify-published
#
# Every leading *.sh argument is sourced, in order (dataset, then a publish
# target). Steps: deps plan harvest collate render icechunk verify, and
# publish verify-published (not run by default).
# Env: E2E_WORK (default ./work/<DATASET>), PYTHON, RSCRIPT, GDAL, WORKERS,
#      HARVEST_LIMIT (scan only the first N sources; for a smoke test),
#      HARVEST_ENGINE (auto | gdal | h5py; see py/harvest.py),
#      R_LIB (default ./r-lib: R packages installed by the deps step),
#      ICECHUNK_ARGS (extra py/render_icechunk.py options, e.g. "--split 0"),
#      PUBLISH (a /vsis3/ prefix; set by config/aadc-transfer.sh),
#      STAC_TARGET (remap target for STAC item hrefs; default KERCHUNK_TARGET),
#      STAC_BASE (public URL of the published dataset prefix, for absolute
#      STAC asset hrefs and GDAL open strings).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -ge 1 ] || { sed -n '2,21p' "$0"; exit 1; }
CONFIGS=()
while [ $# -ge 1 ] && [[ $1 == *.sh ]]; do source "$1"; CONFIGS+=("$(basename "$1")"); shift; done
# Provenance stamped into the store meta (and so into every rendered form).
# safe.directory: a container running as root may not own the checkout.
REV=$(git -c safe.directory="$HERE" -C "$HERE" describe --always --dirty 2>/dev/null || echo unversioned)
REPO=$(git -c safe.directory="$HERE" -C "$HERE" remote get-url origin 2>/dev/null | sed -E "s#//[^@/]*@#//#")
export E2E_GENERATOR="${E2E_REPO:-${REPO:-local}} $REV" E2E_CONFIG="${CONFIGS[*]}"
STEPS=${*:-plan harvest collate render icechunk stac verify}
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
    plan)
      # sources go to the mosaic as a response file (@file): a full GHRSST
      # or multi-year BRAN listing is longer than the argument limit
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
        ${HARVEST_LIMIT:+--limit "$HARVEST_LIMIT"} ;;
    collate)
      step collate "$RSCRIPT" "$HERE/R/collate.R" "$WORK/scan" "$WORK/plan.vrt" \
        "$WORK/store.sqlite" "$DATASET" ${REMAPS[@]+"${REMAPS[@]}"} ;;
    render)
      step render "$RSCRIPT" "$HERE/R/render.R" "$WORK/store.sqlite" "$WORK/out" \
        "$KERCHUNK_TARGET" "$VRT_TARGET" ;;
    icechunk)
      step icechunk "$PYTHON" "$HERE/py/render_icechunk.py" "$WORK/out/flat" \
        "$WORK/out/icechunk" --target "$ICECHUNK_TARGET" ${ICECHUNK_ARGS:-} ;;
    stac)
      # after icechunk: the collection lists every form present in out/
      step stac "$RSCRIPT" "$HERE/R/stac.R" "$WORK/store.sqlite" "$WORK/out" \
        "${STAC_TARGET-$KERCHUNK_TARGET}" "${STAC_BASE:-}"
      # stac-geoparquet from the ndjson items, where rustac is installed
      if command -v rustac > /dev/null; then
        step stac rustac translate "$WORK/out/stac/items.ndjson" "$WORK/out/stac/items.parquet"
      fi ;;
    verify)
      step verify "$PYTHON" "$HERE/py/verify.py" --plan "$WORK/plan.vrt" --out "$WORK/out" \
        ${VERIFY_WINDOWS:-} ;;
    publish)
      [ -n "$PUB" ] || { echo "publish: set PUBLISH or source a publish config"; exit 1; }
      step publish "$GDAL" vsi sync -r -j 8 "$WORK/out/" "$PUB/"
      for f in plan.vrt store.sqlite; do step publish "$GDAL" vsi copy "$WORK/$f" "$PUB/$f"; done ;;
    verify-published)
      [ -n "$PUB" ] || { echo "verify-published: set PUBLISH or source a publish config"; exit 1; }
      step verify-published "$PYTHON" "$HERE/py/verify.py" --plan "$WORK/plan.vrt" --out "$WORK/out" \
        --published "$PUB" ${VERIFY_WINDOWS:-} ;;
    *) echo "unknown step $s"; exit 1 ;;
  esac
done
du -sh "$WORK"/{plan.vrt,scan,store.sqlite,out/*} 2>/dev/null | tee -a "$LOG" || true

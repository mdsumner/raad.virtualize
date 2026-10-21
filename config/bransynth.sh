# Synthetic BRAN-shaped rehearsal (py/make_bran_synth.py): two local monthly
# files, many chunks per file, some never written. Runs anywhere, no network.
# The files are made on the first `plan` step.
DATASET=bran-synth
ARRAYS="temp"
SYNTH_DIR=${SYNTH_DIR:-${E2E_WORK:-$HERE/work/$DATASET}/nc}
sources() {
  [ -f "$SYNTH_DIR/ocean_temp_2010_02.nc" ] || ${PYTHON:-python} "$HERE/py/make_bran_synth.py" "$SYNTH_DIR" >&2
  echo "$SYNTH_DIR/ocean_temp_2010_01.nc"
  echo "$SYNTH_DIR/ocean_temp_2010_02.nc"
}
# local files: Icechunk and kerchunk read them as file paths (no remap)
REMAPS=()
KERCHUNK_TARGET=""
ICECHUNK_TARGET=""
VRT_TARGET=""
WORKERS=${WORKERS:-2}

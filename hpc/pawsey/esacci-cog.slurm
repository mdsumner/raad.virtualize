#!/bin/bash --login
#SBATCH --job-name=esacci-cog
#SBATCH --account=pawsey1362
#SBATCH --partition=work
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=08:00:00
#SBATCH --output=esacci-cog-%j.out
# ESA CCI Ocean Colour netCDF -> COG (py/esacci_cog.py) on Pawsey Setonix,
# then upload of the COGs to Acacia with rclone. Submit from the repository
# root; see docs/esacci-oc.md.
#
#   sbatch hpc/pawsey/esacci-cog.slurm
#   sbatch --export=ALL,ESACCI_YEARS="2024 2025",ESACCI_LIMIT=2 hpc/pawsey/esacci-cog.slurm
#
#   ESACCI_CATALOG  THREDDS catalog.xml (default the v6.0 geographic monthly
#                   chlor_a catalog)
#   ESACCI_VARS     netCDF variables, space separated (default chlor_a
#                   chlor_a_log10_bias chlor_a_log10_rmsd)
#   ESACCI_YEARS    years, space separated (default every year)
#   ESACCI_LIMIT    convert at most N netCDF files (smoke test)
#   ESACCI_OUT      local COG root (default $MYSCRATCH/esacci-oc/cog)
#   ESACCI_REMOTE   rclone destination of the COG root (default
#                   pawsey1197:aad-derived/esacci-oc); empty: no upload
#   ESACCI_WORKERS  files at once (default 8: the downloads, not the CPUs,
#                   set the pace, and each worker holds about 1 GB)
#   SIF             container image (default the gdal-r-python-extras SIF
#                   in $MYSOFTWARE/sif_lib)
#
# COGs already under ESACCI_OUT, or listed under ESACCI_REMOTE, are skipped,
# so a job that runs out of time is resubmitted as is. rclone runs on the
# host with its own configuration (no keys in the job or the environment).
set -uo pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"
module load singularity/4.1.0-slurm
command -v rclone > /dev/null || module load rclone

CATALOG=${ESACCI_CATALOG:-https://www.oceancolour.org/thredds/catalog/cci/v6.0-release/geographic/monthly/chlor_a/catalog.xml}
VARS=${ESACCI_VARS:-chlor_a chlor_a_log10_bias chlor_a_log10_rmsd}
OUT=${ESACCI_OUT:-$MYSCRATCH/esacci-oc/cog}
TMP=$(dirname "$OUT")/download
REMOTE=${ESACCI_REMOTE-pawsey1197:aad-derived/esacci-oc}
WORKERS=${ESACCI_WORKERS:-8}
SIF=${SIF:-$MYSOFTWARE/sif_lib/gdal-r-python-extras_2026-10-25.sif}
mkdir -p "$OUT" "$TMP"

# COGs already in the bucket, by name
DONE=$(dirname "$OUT")/done.txt
: > "$DONE"
if [ -n "$REMOTE" ]; then
  rclone lsf -R --files-only --include '*.tif' "$REMOTE" > "$DONE" 2>/dev/null || true
  echo "esacci-cog: $(wc -l < "$DONE") COGs already under $REMOTE"
fi

var_flags=(); for v in $VARS; do var_flags+=(--var "$v"); done
singularity exec -B /scratch "$SIF" python "$PWD/py/esacci_cog.py" \
  --catalog "$CATALOG" "${var_flags[@]}" --out "$OUT" --tmp "$TMP" --done "$DONE" \
  --workers "$WORKERS" --threads 2 ${ESACCI_YEARS:+--years $ESACCI_YEARS} \
  ${ESACCI_LIMIT:+--limit "$ESACCI_LIMIT"}
rc=$?

# upload what was written, also after a partial run; *.part are unfinished
if [ -n "$REMOTE" ]; then
  rclone copy "$OUT" "$REMOTE" --exclude '*.part' --transfers 8 --checkers 16 || rc=1
  rclone check "$OUT" "$REMOTE" --one-way --size-only --exclude '*.part' || rc=1
fi
echo "esacci-cog: exit $rc"
exit $rc

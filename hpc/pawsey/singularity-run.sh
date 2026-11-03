#!/usr/bin/env bash
# Run a script of this repository (run.sh, catalog.sh) inside the
# gdal-r-python-extras image on Pawsey Setonix, the singularity counterpart
# of hpc/vm/docker-run.sh. From the repository root, on a login node (the
# source.coop publish keys last one hour) or inside a Slurm job:
#
#   bash hpc/pawsey/singularity-run.sh run.sh config/esacci-oc.sh
#   bash hpc/pawsey/singularity-run.sh run.sh config/esacci-oc.sh config/source-coop.sh publish verify-published
#
# The Python packages the image lacks (obstore for source.coop publish,
# imagecodecs and fastparquet) are installed once with pip --user into
# RV_PYUSER. The environment passes into the container as is.
#
#   SIF        default $MYSOFTWARE/sif_lib/gdal-r-python-extras_2026-10-25.sif
#   RV_PYUSER  default $MYSOFTWARE/rv-pyuser
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ $# -ge 1 ] || { sed -n '2,15p' "$0"; exit 1; }
module load singularity/4.1.0-slurm 2>/dev/null || true
SIF=${SIF:-$MYSOFTWARE/sif_lib/gdal-r-python-extras_2026-10-25.sif}
export PYTHONUSERBASE=${RV_PYUSER:-$MYSOFTWARE/rv-pyuser}
PKGS="obstore imagecodecs fastparquet"
cd "$HERE"
exec singularity exec -B /scratch -B "$MYSOFTWARE" "$SIF" bash -c '
  python -c "import obstore, imagecodecs, fastparquet" 2>/dev/null ||
    python -m pip install -q --user '"$PKGS"' 2>/dev/null ||
    python -m pip install -q --user --break-system-packages '"$PKGS"'
  exec bash "$@"' bash "$@"

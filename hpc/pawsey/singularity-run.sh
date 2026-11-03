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
# imagecodecs, fastparquet, rustac) are installed once with pip --target into
# RV_PYUSER/site, which goes on PYTHONPATH (the image's Python is a
# virtualenv, which refuses pip --user). The environment passes into the
# container as is.
#
#   SIF        default $MYSOFTWARE/sif_lib/gdal-r-python-extras_2026-10-25.sif
#   RV_PYUSER  default $MYSOFTWARE/rv-pyuser
#   SINGULARITY_MODULE  default singularity/4.3.5-slurm, loaded when
#              singularity is not already on PATH
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ $# -ge 1 ] || { sed -n '2,17p' "$0"; exit 1; }
command -v singularity > /dev/null || module load "${SINGULARITY_MODULE:-singularity/4.3.5-slurm}"
command -v singularity > /dev/null || { echo "singularity-run.sh: no singularity (set SINGULARITY_MODULE)" >&2; exit 1; }
SIF=${SIF:-$MYSOFTWARE/sif_lib/gdal-r-python-extras_2026-10-25.sif}
PYSITE=${RV_PYUSER:-$MYSOFTWARE/rv-pyuser}/site
export PYTHONPATH=$PYSITE${PYTHONPATH:+:$PYTHONPATH}
PKGS="obstore imagecodecs fastparquet rustac"
cd "$HERE"
exec singularity exec -B "$MYSOFTWARE" "$SIF" bash -c '
  for p in '"$PKGS"'; do
    python -c "import $p" 2>/dev/null && continue
    # only what is missing, and without dependencies for the self-contained
    # wheels, so nothing on PYTHONPATH shadows the image numpy or GDAL
    case $p in obstore|rustac) nd=--no-deps ;; *) nd= ;; esac
    python -m pip install -q --target "'"$PYSITE"'" $nd $p
  done
  exec bash "$@"' bash "$@"

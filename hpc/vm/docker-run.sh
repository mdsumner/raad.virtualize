#!/usr/bin/env bash
# Run a script of this repository (run.sh, catalog.sh) inside the
# gdal-r-python-extras image on a docker host such as the Nectar VM. The
# checkout is mounted at its own path, so work/ and log paths match the host.
#
#   bash hpc/vm/docker-run.sh run.sh config/ghrsst-cog.sh config/source-coop.sh
#   bash hpc/vm/docker-run.sh run.sh config/ghrsst-cog.sh config/source-coop.sh publish
#   bash hpc/vm/docker-run.sh catalog.sh products/ghrsst config/source-coop.sh check publish
#
# Settings exported on the host are passed in by name: AWS_* (publish keys),
# the dataset settings (GHRSST_*, BRAN_*, BLUELINK_*, OISST_*, SEAICE_*, BEDMAP3_*, IBCSO_*, ESACCI_*), the run.sh settings
# (E2E_WORK, WORKERS, HARVEST_*, VERIFY_WINDOWS, GRIST_*, STAC_*,
# ICECHUNK_ARGS, S3_SYNC_ARGS) and the publish target (SOURCECOOP_*,
# AADC_PREFIX). The Python packages the image lacks (obstore for source.coop
# publish, imagecodecs and fastparquet for TIFF predictor sources, rustac
# for stac-geoparquet) are
# installed into the container on each start (the container is removed
# after the run). The container runs as root, so work/ is root-owned.
#
#   RV_IMAGE   default ghcr.io/hypertidy/gdal-r-python-extras:latest
#   RV_MOUNTS  extra host directories mounted read-only at the same path,
#              space separated; default /rdsi when it exists (the raad
#              collection, for OISST_MIRROR and SEAICE_MIRROR)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ $# -ge 1 ] || { sed -n '2,22p' "$0"; exit 1; }
IMAGE=${RV_IMAGE:-ghcr.io/hypertidy/gdal-r-python-extras:latest}
envs=()
for v in $(compgen -e); do
  case $v in
    AWS_*|GHRSST_*|BRAN_*|BLUELINK_*|OISST_*|SEAICE_*|BEDMAP3_*|IBCSO_*|ESACCI_*|HARVEST_*|GRIST_*|STAC_*|SOURCECOOP_*|\
    E2E_WORK|WORKERS|VERIFY_WINDOWS|ICECHUNK_ARGS|S3_SYNC_ARGS|AADC_PREFIX) envs+=(-e "$v") ;;
  esac
done
mounts=()
for m in ${RV_MOUNTS-$([ -d /rdsi ] && echo /rdsi)}; do mounts+=(-v "$m:$m:ro"); done
PKGS="obstore imagecodecs fastparquet rustac"
exec docker run --rm -i -v "$HERE:$HERE" -w "$HERE" ${mounts[@]+"${mounts[@]}"} ${envs[@]+"${envs[@]}"} "$IMAGE" bash -c '
  python -c "import obstore, imagecodecs, fastparquet, rustac" 2>/dev/null ||
    python -m pip install -q '"$PKGS"' 2>/dev/null ||
    python -m pip install -q --break-system-packages '"$PKGS"'
  exec bash "$@"' bash "$@"

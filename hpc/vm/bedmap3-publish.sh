#!/usr/bin/env bash
# Publish Bedmap3 to ausantarctic/bedmap: COGs, virtual forms, anonymous
# read-back, catalog, README. Needs the product's AWS_* keys
# exported and the builds of docs/bedmap-source-coop.md done. Stops at the
# first failure.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$HERE"
export RV_MOUNTS= SOURCECOOP_REPO=ausantarctic/bedmap SOURCECOOP_PRODUCTION=1
export AWS_S3_ENDPOINT=data.source.coop AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE AWS_REGION=us-west-2
dr() { bash hpc/vm/docker-run.sh "$@"; }
# BEDMAP_WRITE_CHECK=1 runs py/sourcecoop_check.py first. Off by default: on
# 2026-11-03 login credentials could write but not delete in this product, so
# the check fails at cleanup and leaves 125 MB under _write-check/ each run.
cat > work/bedmap3-upload.sh <<INNER
set -euo pipefail
[ "${BEDMAP_WRITE_CHECK:-0}" != 1 ] || python py/sourcecoop_check.py ausantarctic/bedmap
python py/s3_sync.py work/bedmap3-cog /vsis3/ausantarctic/bedmap/bedmap3/cog
INNER
dr work/bedmap3-upload.sh
dr run.sh config/bedmap3.sh config/source-coop.sh publish verify-published
dr catalog.sh products/bedmap config/source-coop.sh check publish
# the product landing page: the catalog's README (previews and links added)
cat > work/bedmap3-upload.sh <<'INNER'
set -euo pipefail
python py/s3_sync.py work/bedmap/catalog/README.md /vsis3/ausantarctic/bedmap/README.md
INNER
dr work/bedmap3-upload.sh

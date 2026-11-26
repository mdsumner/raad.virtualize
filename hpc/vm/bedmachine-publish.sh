#!/usr/bin/env bash
# Publish BedMachine Antarctica to ausantarctic/bedmachine: COGs, virtual
# forms, anonymous read-back, catalog, README. Needs the product's AWS_*
# keys exported and the builds of docs/bedmachine-source-coop.md done. Stops
# at the first failure. Login credentials cannot delete in these products: a
# wrong upload is removed from the source.coop dashboard.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$HERE"
export RV_MOUNTS=${RV_MOUNTS-} SOURCECOOP_REPO=ausantarctic/bedmachine SOURCECOOP_PRODUCTION=1
export AWS_S3_ENDPOINT=data.source.coop AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE AWS_REGION=us-west-2
# dr runs a script in the image, whose interpreter is python (no python3);
# the work/*-upload.sh scripts below run there, not on the host
dr() { bash hpc/vm/docker-run.sh "$@"; }
cat > work/bedmachine-upload.sh <<'INNER'
set -euo pipefail
python py/s3_sync.py work/bedmachine-cog /vsis3/ausantarctic/bedmachine/v4.1/cog
INNER
dr work/bedmachine-upload.sh
# the public forms reference the COG URLs, so their verify (the publish
# gate's record) runs once the COGs are up
dr run.sh config/bedmachine.sh config/source-coop.sh verify publish verify-published
dr catalog.sh products/bedmachine config/source-coop.sh check publish
# the product landing page: the catalog's README (previews and links added)
cat > work/bedmachine-upload.sh <<'INNER'
set -euo pipefail
python py/s3_sync.py work/bedmachine/catalog/README.md /vsis3/ausantarctic/bedmachine/README.md
INNER
dr work/bedmachine-upload.sh

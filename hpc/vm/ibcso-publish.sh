#!/usr/bin/env bash
# Publish IBCSO releases to ausantarctic/ibcso: COGs, verify, virtual forms,
# anonymous read-back, catalog, README. Needs the product's AWS_* keys exported and
# the public builds done (config/ibcso.sh, one per IBCSO_RELEASE). Stops at
# the first failure. Login credentials cannot delete in these products: a
# wrong upload is removed from the source.coop dashboard.
#
#   bash hpc/vm/ibcso-publish.sh v2 2024 2025
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$HERE"
[ $# -ge 1 ] || { sed -n '2,8p' "$0"; exit 1; }
export RV_MOUNTS= SOURCECOOP_REPO=ausantarctic/ibcso SOURCECOOP_PRODUCTION=1
# dr runs a script in the image, whose interpreter is python (no python3);
# the work/*-upload.sh scripts below run there, not on the host
dr() { bash hpc/vm/docker-run.sh "$@"; }
for rel in "$@"; do
  case $rel in v2) prefix=v2 ;; 2024|2025) prefix=annual-$rel ;; *) echo "unknown release $rel"; exit 1 ;; esac
  cat > work/ibcso-upload.sh <<INNER
set -euo pipefail
export AWS_S3_ENDPOINT=data.source.coop AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE AWS_REGION=us-west-2
python py/s3_sync.py --skip-same-size work/ibcso-$prefix-cog /vsis3/ausantarctic/ibcso/$prefix/cog
INNER
  dr work/ibcso-upload.sh
  # the public forms reference the COG URLs, so their verify (the publish
  # gate's record) runs once the COGs are up
  IBCSO_RELEASE=$rel dr run.sh config/ibcso.sh config/source-coop.sh verify publish verify-published
done
cat > work/ibcso-upload.sh <<'INNER'
set -euo pipefail
export AWS_S3_ENDPOINT=data.source.coop AWS_HTTPS=YES AWS_VIRTUAL_HOSTING=FALSE AWS_REGION=us-west-2
python py/s3_sync.py work/ibcso/catalog/README.md /vsis3/ausantarctic/ibcso/README.md
INNER
# the product landing page is the catalog's README (previews and links added)
dr catalog.sh products/ibcso config/source-coop.sh check publish
dr work/ibcso-upload.sh

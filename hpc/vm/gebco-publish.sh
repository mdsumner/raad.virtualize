#!/usr/bin/env bash
# Build and publish the GEBCO indexes to ausantarctic/gebco/virtual/: one
# dataset per release, read-back with anonymous reads, then the catalog
# (virtual/catalog.json and virtual/README.md; the product root README and
# the COGs are not touched). Builds first (no keys needed), then publishes
# (the product's AWS_* keys exported; they last one hour). Stops at the
# first failure.
#
#   bash hpc/vm/gebco-publish.sh 2026 2025 2024
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$HERE"
[ $# -ge 1 ] || { sed -n '2,9p' "$0"; exit 1; }
export RV_MOUNTS=
dr() { bash hpc/vm/docker-run.sh "$@"; }
for y in "$@"; do GEBCO_YEAR=$y dr run.sh config/gebco.sh; done
export SOURCECOOP_REPO=ausantarctic/gebco SOURCECOOP_PRODUCTION=1
for y in "$@"; do
  GEBCO_YEAR=$y dr run.sh config/gebco.sh config/source-coop.sh publish verify-published
done
dr catalog.sh products/gebco config/source-coop.sh check publish

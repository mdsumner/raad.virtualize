#!/usr/bin/env bash
# Build portolan-browser for this VM: upstream main plus the fork's patch
# branches listed in hpc/vm/portolan-patches.txt, tested, built for the
# path /portolan/ and copied to the directory nginx serves there.
#
#   bash hpc/vm/portolan-site.sh               # build, test, publish
#   bash hpc/vm/portolan-site.sh --no-publish  # build and test only
#
# The fork clone (PORTOLAN_REPO, default ~/Git/portolan-browser, remotes
# origin = mdsumner/portolan-browser and upstream = portolan-sdi) is only
# fetched. The build runs in a worktree of it (PORTOLAN_BUILD), so the
# clone's own checkout is not touched. A patch that does not merge, a failed
# unit test or a failed build stops the script and leaves the published site
# as it was. dist/vm-build.txt records the commits built.
#
# Publish target PORTOLAN_WWW (default /var/www/portolan), served by the
# nginx site with:
#   location /portolan/ { alias /var/www/portolan/; index index.html; }
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO=${PORTOLAN_REPO:-$HOME/Git/portolan-browser}
BUILD=${PORTOLAN_BUILD:-$HOME/.cache/portolan-site/build}
WWW=${PORTOLAN_WWW:-/var/www/portolan}
PREFIX=${PORTOLAN_PATH_PREFIX:-/portolan/}
PATCHES=$HERE/hpc/vm/portolan-patches.txt
publish=1
[ "${1:-}" = --no-publish ] && publish=0

git -C "$REPO" fetch -q upstream
git -C "$REPO" fetch -q origin
if [ ! -e "$BUILD/.git" ]; then
  mkdir -p "$(dirname "$BUILD")"
  git -C "$REPO" worktree add -q --detach "$BUILD" upstream/main
fi
git -C "$BUILD" reset -q --hard
git -C "$BUILD" clean -qfdx -e node_modules
git -C "$BUILD" checkout -q --detach upstream/main

mapfile -t branches < <(grep -v '^\s*#' "$PATCHES" | awk 'NF {print $1}')
for b in "${branches[@]}"; do
  if ! git -C "$BUILD" merge -q --no-edit "origin/$b"; then
    git -C "$BUILD" merge --abort || true
    echo "portolan-site: origin/$b does not merge onto upstream/main"
    exit 1
  fi
done

cd "$BUILD"
pnpm install --frozen-lockfile
pnpm run test:unit
SB_pathPrefix=$PREFIX SB_historyMode=hash pnpm run build
{
  echo "built $(date -u +%FT%TZ) for $PREFIX"
  echo "upstream/main $(git -C "$REPO" rev-parse --short upstream/main)"
  for b in "${branches[@]}"; do echo "origin/$b $(git -C "$REPO" rev-parse --short "origin/$b")"; done
} > dist/vm-build.txt
cat dist/vm-build.txt

if [ "$publish" = 1 ]; then
  [ -w "$WWW" ] || { echo "portolan-site: $WWW is not writable; built in $BUILD/dist"; exit 1; }
  rsync -a --delete dist/ "$WWW/"
  echo "portolan-site: published to $WWW"
fi

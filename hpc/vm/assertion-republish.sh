#!/usr/bin/env bash
# Republish scratch datasets with their assertions applied
# (requests/assertion-step.md). No harvest and no collate: each dataset's
# published store.sqlite and plan.vrt are fetched into a fresh work
# directory (work/assert-<dataset>), and the assert, render, icechunk,
# grist, stac and verify steps run from them, as the assertion-cards job
# does. Phase "build" needs no keys; phase "publish" uploads with the
# scratch product's keys (they last one hour, so publish a few datasets per
# key set) and reads every form back anonymously.
#
#   bash hpc/vm/assertion-republish.sh build g02202-v6-daily-south
#   bash hpc/vm/assertion-republish.sh publish g02202-v6-daily-south
#   bash hpc/vm/assertion-republish.sh build all
#
# Datasets: the assertion-cards matrix (.github/workflows/assertion-cards.yml).
# Stops at the first failure. Writes only to
# ausantarctic/ausantarctic-scratch (config/source-coop.sh refuses
# production products).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$HERE"
[ $# -ge 2 ] || { sed -n '2,18p' "$0"; exit 1; }
phase=$1; shift
SCRATCH=https://data.source.coop/ausantarctic/ausantarctic-scratch

# dataset group config env
table() {
  cat <<'EOF'
g02202-v6-daily-south seaice config/seaice-g02202.sh SEAICE_HEM=south
g02202-v6-daily-north seaice config/seaice-g02202.sh SEAICE_HEM=north
asi-amsr2-v5.4-daily-south seaice config/seaice-asi-amsr2.sh SEAICE_HEM=south
oisst-v2.1-daily oisst config/oisst.sh -
ghrsst-mur-cog-analysed_sst ghrsst config/ghrsst-cog.sh GHRSST_VAR=analysed_sst
bluelink-daily-temp bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=temp
bluelink-daily-salt bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=salt
bluelink-daily-eta_t bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=eta_t
bluelink-daily-mld bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=mld
bluelink-daily-u bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=u
bluelink-daily-v bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=v
bluelink-daily-w bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=w
bluelink-daily-tx_trans_int_z bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=tx_trans_int_z
bluelink-daily-ty_trans_int_z bluelink config/bluelink.sh BLUELINK_FREQ=daily,BRAN_VAR=ty_trans_int_z
EOF
}

names=("$@")
[ "${names[0]}" = all ] && mapfile -t names < <(table | cut -d' ' -f1)

for ds in "${names[@]}"; do
  row=$(table | awk -v d="$ds" '$1 == d') || true
  [ -n "$row" ] || { echo "assertion-republish: $ds is not in the table"; exit 1; }
  read -r _ group config envs <<< "$row"
  W=$HERE/work/assert-$ds
  (
    [ "$envs" = - ] || { IFS=, ; for kv in $envs; do export "${kv?}"; done; }
    export E2E_WORK=$W
    case $phase in
      build)
        mkdir -p "$W"
        for f in store.sqlite plan.vrt; do
          curl -fsSL -o "$W/$f" "$SCRATCH/$group/$ds/$f"
        done
        # optional: not every dataset has one
        curl -fsL -o "$W/sources.meta.tsv" "$SCRATCH/$group/$ds/sources.meta.tsv" 2>/dev/null ||
          rm -f "$W/sources.meta.tsv"
        echo "assertion-republish: $ds fetched; render and verify (log: $W/log.txt)"
        bash hpc/vm/docker-run.sh run.sh "$config" config/source-coop.sh \
          assert render icechunk grist stac verify ;;
      publish)
        [ -f "$W/out/verify.json" ] || { echo "assertion-republish: $ds has no verify pass; run build first"; exit 1; }
        : "${AWS_ACCESS_KEY_ID:?export the scratch product keys}"
        bash hpc/vm/docker-run.sh run.sh "$config" config/source-coop.sh publish verify-published ;;
      *) echo "assertion-republish: phase is build or publish"; exit 1 ;;
    esac
  )
done

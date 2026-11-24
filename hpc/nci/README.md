# BRAN2023 on NCI Gadi

The BRAN2023 daily store built in situ from `/g/data/gb6`, with the same
container image as the desktop runs. Sources are recorded as
`/g/data/gb6/...` paths and rewritten to NCI THREDDS URLs at render
(`REMAPS` in `config/bran.sh`), so the published forms read over HTTPS from
anywhere.

## Container image

Once, from a login node or copyq (the pull needs internet):

```
module load singularity
SIF=/g/data/$PROJECT/$USER/sif_lib/gdal-r-python-extras_latest.sif
mkdir -p "$(dirname "$SIF")"
singularity pull "$SIF" docker://ghcr.io/hypertidy/gdal-r-python-extras:latest
```

Both jobs use that path when `SIF` is not set (add `gdata/<project>` to
`-l storage`); pass `SIF=...` in `-v` for an image elsewhere.

## Jobs

| Script | Queue | Steps |
|---|---|---|
| `bran-build.pbs` | normal, 48 cores | plan, harvest, collate, render, Icechunk, STAC |
| `bran-publish.pbs` | copyq | verify, publish, verify-published |

Compute nodes have no internet, and the rendered forms point at THREDDS, so
verify runs with the publish on copyq. From the repository root, with
`ab12` replaced by the project:

```
JOB=$(qsub -P ab12 -l storage=gdata/gb6+scratch/ab12 \
  -v BRAN_VAR=temp,BRAN_YEARS=2010:2023,SIF=$SIF hpc/nci/bran-build.pbs)
qsub -P ab12 -l storage=gdata/gb6+scratch/ab12 -W depend=afterok:$JOB \
  -v BRAN_VAR=temp,BRAN_YEARS=2010:2023,SIF=$SIF,AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY \
  hpc/nci/bran-publish.pbs
```

`BRAN_YEARS` is a `FIRST:LAST` range. `CONFIG=config/bluelink.sh` (in both
`-v` lists) builds the coalesced series instead: BRAN2020 from 1993, BRAN2023
from 2010 to its last month on disk, about 37M refs for `temp`. Work goes to
`/scratch/$PROJECT/$USER/raad.virtualize/bran2023-daily-<var>` (override with
`E2E_WORK`). The harvest restarts where it stopped, so a job that runs out of
walltime is resubmitted as is.

`bran-publish.pbs` publishes to the AADC transfer bucket
(`config/aadc-transfer.sh`) unless `PUBLISH_CONFIG` names another target.
Drafts go to source.coop, `ausantarctic/ausantarctic-scratch` under
the config's group, `bluelink/<DATASET>/` (`PUBLISH_CONFIG=config/source-coop.sh`). Its keys last
one hour and include `AWS_SESSION_TOKEN`, so that publish is submitted
after the build finishes rather than held with `-W depend`:

```
# needs the scratch product's AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN already exported
qsub -P ab12 -l storage=gdata/gb6+scratch/ab12 \
  -v CONFIG=config/bluelink.sh,BRAN_VAR=temp,PUBLISH_CONFIG=config/source-coop.sh,AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY,AWS_SESSION_TOKEN \
  hpc/nci/bran-publish.pbs
```

`config/source-coop.sh` publishes with obstore (`py/s3_sync.py`), which the
image needs.

## Standing job

`standing.pbs` keeps the datasets of `standing.tsv` current from `/g/data`
without a THREDDS crawl: the filesystem is the listing. Each run, on copyq:

1. lists every source of `standing.tsv` in situ (`py/gdata_listing.py`):
   path, size and mtime of each matching file, kept in the aad-filelist
   corpus shape under `LISTINGS` (default `/g/data/$PROJECT/$USER/listings`):
   `current__<source_id>.parquet`, `changes__<source_id>.parquet`,
   `runs/<source_id>/<run_id>.parquet` and `heartbeat__<source_id>.json`
   (`listed_at`, file count, bytes, `listing_hash`, what changed);
2. checks the last build of each dataset against that listing
   (`run.sh <config> stale` with `CORPUS_BASE=$LISTINGS`);
3. when the listing changed, the build is stale, or there is no build yet,
   submits `bran-build.pbs` with `GDATA_LISTINGS=$LISTINGS` (the config
   selects its files from the listing and writes `sources.meta.tsv`) and
   `standing-handoff.pbs` held on it, unless a build or hand-off for that
   dataset is still queued or running;
4. writes `$LISTINGS/standing/<dataset>.json` (checked_at, heartbeat, stale
   count, action) and submits itself for the next run with `qsub -a`.

`standing-handoff.pbs` verifies the build (copyq, the forms point at
THREDDS) and records it in bowerbird-byterefs: the release
`<dataset>@<build_id>` and a pull request with the git record. Merging the
pull request adopts the build. Source.coop keys last one hour, so the
publish is not part of the chain: after the pull request, submit
`bran-publish.pbs` with fresh keys, as above. A file of a store's sources
replaced or removed on `/g/data` shows in the next run's stale check and
triggers a rebuild.

Once, on a login node: a bowerbird-byterefs checkout that can push, at
`/g/data/$PROJECT/$USER/bowerbird-byterefs` (or `BBR` in `-v`), and `gh`
on `PATH`, signed in. Then start the chain:

```
qsub -P jk72 -l storage=gdata/gb6+gdata/jk72+scratch/jk72 \
  -v STANDING_STORAGE=gdata/gb6+gdata/jk72+scratch/jk72,STANDING_DRY=1,STANDING_ONCE=1 \
  hpc/nci/standing.pbs
```

`STANDING_DRY=1` lists and checks without submitting builds,
`STANDING_ONCE=1` without submitting the next run; drop both to start the
chain. `qselect -N rv-standing -u $USER` shows the queued run; `qdel` it to
stop. Settings are in the header of `standing.pbs`.

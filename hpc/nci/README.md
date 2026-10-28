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
SIF=/scratch/$PROJECT/$USER/gdal-r-python-extras.sif
singularity pull "$SIF" docker://ghcr.io/hypertidy/gdal-r-python-extras:latest
```

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

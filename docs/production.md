---
title: "Production jobs"
---

Status 2026-11-27: planned, not started. The current work is the
republish queue in `STATUS.md`: each dataset republished once under the new
schemes, with a source.coop key per publish run. This page records the plan
for the jobs that afterwards keep each published store current and up to
standard. The production team takes over a store once it passes the four
criteria on the [Datasets](published.md#freshness) page.

## What a job keeps

- **Current:** *index to* equals *upstream to*, and nothing referenced is
  stale (the freshness table on the [Datasets](published.md#freshness)
  page).
- **Up to standard:** `verify` and `verify-published` agree, the assertion
  cards pass (`py/assertion_cards.py`), and the viewer draws the collection
  ([Viewer strategy](viewer-strategy.md)).

## One job per update model

| Update model | Datasets | Job |
|---|---|---|
| `fixed` | Bedmap3, BedMachine, IBCSO, GEBCO, ACCESS-ESM1.6 | No rebuild. A periodic check: `verify-published`, cards, viewer. A new release is a new dataset |
| `append` | OISST, G02202, ASI, Bluelink, ESA CCI | Listing, then the `stale` step, then a rebuild and publish when the upstream extends |
| `append-rewrite` | GHRSST MUR | As `append`, with the dataset config's hold-back of the newest days |
| `rewrite` | IMOS MEOP | Listing, then a rebuild on any change |

The listing comes from the aad-filelist corpus (weekly), or from an in-situ
listing where the files are on a filesystem the job can read
(`hpc/nci/standing.pbs` for `/g/data`).

## Where jobs run

- **Nectar VM** (`hpc/vm/docker-run.sh`): sources on source.coop and other
  public HTTP hosts.
- **NCI Gadi**: `/g/data` sources (Bluelink). `hpc/nci/standing.pbs` with
  `standing.tsv` already lists, checks staleness and submits builds. Its
  publish runs on copyq.
- **Pawsey** (`hpc/pawsey/`): the ESA CCI COGs.
- **GitHub Actions**: metadata-only jobs (the assertion cards workflow, a
  viewer check). Actions cannot read `/g/data`.

## Credentials

- **Now:** a dashboard key per publish run. It lasts one hour and can write
  but not delete.
- **Next: the source-coop CLI on the VM.**
  - Sign in once, over an SSH port forward (`source-coop login`).
  - Use an AWS profile with `credential_process = source-coop creds`, or
    `eval $(source-coop creds --format env)` at the start of each publish,
    for `py/s3_sync.py`.
  - `creds` renews the credentials from the refresh token, and each renewal
    restarts that token's lifetime (about 30 days), so a daily job keeps the
    sign-in alive.
  - To check first: whether the proxy honours `login --duration` above one
    hour, and whether these credentials can delete. If they can delete,
    `s3_sync.py --delete` removes old Icechunk objects.
- **Later: service accounts** (CLI `next` build).
  - A GitHub OIDC trust for Actions workflows, with no stored secret.
  - An API key with an expiry (30 days to one year) for VM and HPC cron jobs.
  - One service account per job, with write access only to the products it
    publishes.
  - source.coop must first enable service accounts for the ausantarctic
    account.

## Icechunk republish without old objects

Each build creates a new local Icechunk repository, so a republish uploads
new object names and the previous build's objects stay (LEDGER,
2026-11-26). An unattended job needs one of:

- **Commit into the published repository** in place of creating a new one,
  so a republish adds a commit. Expiring old snapshots still needs delete.
- **A credential that deletes**, then `s3_sync.py --delete` after the
  upload.

A dashboard folder delete before the upload works by hand only.

## Increments

1. CLI credentials on the VM for the manual publishes of the republish
   queue, in place of dashboard keys.
2. A scheduled check job with no writes: `verify-published`, the cards and
   the viewer for each collection, reported per dataset.
3. Rebuild jobs for the `append` datasets, one at a time, each with its
   staleness check.
4. Service accounts once source.coop offers them, one per job.

---
title: "Production jobs"
---

Status 2026-11-27: planned; the credentials step is in place. The current work is the
republish queue in `STATUS.md`: each dataset republished once under the new
schemes, with CLI credentials per publish run. This page records the plan
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

- **Now: the source-coop CLI on the VM** (0.3.0, signed in 2026-11-27).
  - Sign in once per account, over an SSH tunnel from the laptop:

    ```sh
    ssh -i <key>.pem -N -L 8400:127.0.0.1:8400 ubuntu@<VM>   # laptop, left running
    source-coop login --port 8400 --duration 12h              # VM, as the account that publishes
    ```

    The session belongs to the account that ran `login`, so sign in as the
    account that runs the publishes.
  - Each publish starts with `eval "$(source-coop creds --format env)"`, or
    uses an AWS profile with `credential_process = source-coop creds`.
    `creds` renews the credentials from the refresh token, and each renewal
    restarts that token's lifetime (about 30 days), so a daily job keeps the
    sign-in alive. Credentials renewed on 2026-11-27 lasted 12 hours.
  - These credentials write and delete. Deletes must be signed in their
    headers (`aws s3 rm`, boto3, `s3_sync.py --delete`); the proxy refuses
    a presigned DELETE.
- **Before: a dashboard key per publish run.** It lasts one hour.
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
2026-11-26). Two ways for an unattended job:

- **Upload, then delete** (available): `s3_sync.py --delete` on the
  `icechunk/` prefix, with CLI credentials. The `repo` file goes up after
  every other file and the delete runs last, so a reader never finds a
  branch whose snapshot is missing.
- **Commit into the published repository** in place of creating a new one,
  so a republish adds a commit. Expiring old snapshots still deletes
  objects, through Icechunk's own S3 client (untested against the proxy).

## Increments

1. CLI credentials on the VM for the manual publishes of the republish
   queue, in place of dashboard keys. In place since 2026-11-27.
2. A scheduled check job with no writes: `verify-published`, the cards and
   the viewer for each collection, reported per dataset.
3. Rebuild jobs for the `append` datasets, one at a time, each with its
   staleness check.
4. Service accounts once source.coop offers them, one per job.

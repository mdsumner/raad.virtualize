# Ledger

Facts learned while building and publishing the stores, each with the check
that guards it. Re-run the check before relying on a fact. Add a row when a
fact is learned; open work goes in [STATUS.md](STATUS.md).

## Publishing and credentials

| Date | Fact | Check |
|---|---|---|
| 2026-11-26 | source.coop dashboard keys last one hour and include `AWS_SESSION_TOKEN`. A run after expiry fails with `ExpiredToken` and writes nothing | The failing run's stderr; last-modified of the target objects unchanged |
| 2026-11-26 | Dashboard keys write but do not delete: `s3_sync.py --delete` is refused. The dashboard itself deletes a whole folder | `s3_sync.py --delete` on a scratch object; the folder delete of 2026-11-26 (three `icechunk/` folders) |
| 2026-11-27 | source-coop CLI 0.3.0 has `login` and `creds`. `login --duration` (`12h`, `1d`) sets the requested credential lifetime. `creds` renews expired credentials from the cached refresh token (scope `offline_access`). The README estimates the refresh token at 30 days (Ory's default), restarted at each renewal. Whether the proxy grants more than one hour is not checked | `source-coop login --help`; CLI README, "See your sign-in status" |
| 2026-11-27 | Service accounts (GitHub Actions OIDC trust with no secret, or API keys expiring after 30 days, 90 days, one year or never) are in the CLI's unreleased `next` build, not 0.3.0. source.coop must first let the account own service accounts | CLI README, "Service accounts"; `source-coop --help` on 0.3.0 lists only `login` and `creds` |
| 2026-11-23 | Size alone misses a rewritten file. The first MEOP resume compared sizes and left `store.sqlite` and `stac/items.parquet` as the 19 Nov copies. `s3_sync.py --skip-same-size` compares ETags since #113 | ETag of each local file against the anonymous listing |
| 2026-11-23 | Publish gate (#103): `plan`, `harvest`, `collate`, `render`, `icechunk` and `grist` remove `out/verify.json`, and `publish` refuses without it | `run.sh <config> publish` on a build without `verify.json` |
| 2026-11-26 | The public forms of a COG product reference the published COG URLs, so `verify` runs after the COG upload (#120) | `hpc/vm/bedmap3-publish.sh`, `ibcso-publish.sh` |
| 2026-11-26 | The `generator` stamp is written at `collate` (`R/collate.R`, `E2E_GENERATOR`). A republish that skips collate keeps the collate build's commit | `generator` in a republished store's meta |
| 2026-11-27 | A git worktree fails inside the build container: its `.git` file points outside the mount. Build from a plain clone | #125 log, 2026-11-27 |

## Icechunk

| Date | Fact | Check |
|---|---|---|
| 2026-11-26 | Icechunk 2.3.1 names objects at random, and `render_icechunk.py` creates a new local repository per build. A republish uploads new names, and the previous build's objects stay in the published folder. On 2026-11-26: 27,435 (meop-ctd-tags), 48 (meop-ctd-2024) and 421 (MUR) | Anonymous ListObjectsV2 of `<store>/icechunk/` against the local build |
| 2026-11-27 | The #125 republishes left the previous build in place. Published against built objects: G02202 south 119/61, north 119/61, ASI south 231/79, OISST 389/196 | The same listing against `rv-assert2/work/assert-<dataset>/out/icechunk` |
| 2026-11-26 | The `repo` file names the branch snapshots. `s3_sync.py` uploads it after every other file (#121), so `main` never names a snapshot that is not yet up | `icechunk_pointers()` in `py/s3_sync.py` |
| 2026-11-26 | `expire_snapshots` and `garbage_collect` exist in Icechunk 2.3.1, but they delete objects, so dashboard keys cannot run them | Icechunk API; the delete fact above |
| 2026-11-27 | Icechunk keys virtual chunk containers by URL prefix. Two remap roots whose prefixes coincide under one target overwrote each other's container, and every ref under the first was rejected | #126, `py/render_icechunk.py` (shared container, `byterefs_roots.container`) |

## GDAL readers

| Date | Fact | Check |
|---|---|---|
| 2026-11-26 | GDAL reads multidim VRT `<Overviews>` from 3.13 (OSGeo/gdal `ccb731e17a`, 2026-01-20). 3.12.3 ignores the element. The classic view keeps levels of the same rank and data type. BedMachine `bed`, 1000 x 1000 through `AsClassicDataset()`: 191 s without, 8 to 9 s with | `tests/mdim_vrt_overviews.R`; overview count of the array and of its classic view |
| 2026-11-26 | GDAL 3.12.3 to master read `<SourceBand>` sources with a `count * step` RasterIO window. An index view returns the no-data value (0 where none is set) with no error. A strided view fails at the edge, or returns decimated or overview values. `[0:1]` and other contiguous slices are correct | mdsumner/osgeo-upstream `notes/2026-11-26-mdim-classic-strided-read-repro.py` |

## Browsers and hosts

| Date | Fact | Check |
|---|---|---|
| 2026-11-27 | GET with an `Origin` returns `Access-Control-Allow-Origin: *` from data.source.coop, the NOAA OISST bucket, the IMOS bucket, projects.pawsey.org.au and thredds.nci.org.au. THREDDS answers 403 to HEAD with an Origin. noaadata.apps.nsidc.org and data.seaice.uni-bremen.de send no CORS header | `curl -s -o /dev/null -r 0-15 -H 'Origin: https://example.org' -D - <url>`; #99, item 4 |
| 2026-11-27 | A kerchunk asset typed `application/vnd+zarr` makes the Portolan browser open it as a plain Zarr store, find `.zmetadata`, then 404 on the chunks | #126 (asset type `application/x-kerchunk-parquet`) |
| 2026-11-27 | ASI south through the relay takes 2,656 chunk requests per field (one per row chunk), about 26 s; icechunk-js does not merge them | #126 test table |
| 2026-11-28 | `py/thumbnail.py` rotated polar stereographic grids as if x were 0..360 longitude. Rotation is removed; the preview is the array as stored, with only the south-up flip | #125 log, 2026-11-28 |

## Store and pipeline scale

| Date | Fact | Check |
|---|---|---|
| 2026-11-23 | One chunk table and one view per array does not scale to tens of thousands of arrays. SQLite reads `sqlite_master` again after every CREATE: about 57 ms each at 27,000 arrays (meop-ctd-tags: 564 groups, 27,432 arrays, 54 min). The flat, kerchunk and Icechunk forms are one object per array each, so about 82,000 objects | `config/imos-meop.sh` per-tag build log |
| 2026-10-21 | BRAN2023 `temp` 2010, 1,116,900 refs: collate 12 s, render 16 s, Icechunk 5 s | `config/bran.sh` build log |

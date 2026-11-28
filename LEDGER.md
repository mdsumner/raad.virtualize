# Ledger

Facts learned while building and publishing the stores, each with the check
that guards it. Re-run the check before relying on a fact. Add a row when a
fact is learned; open work goes in [STATUS.md](STATUS.md).

## Publishing and credentials

| Date | Fact | Check |
|---|---|---|
| 2026-11-26 | source.coop dashboard keys last one hour and include `AWS_SESSION_TOKEN`. A run after expiry fails with `ExpiredToken` and writes nothing | The failing run's stderr; last-modified of the target objects unchanged |
| 2026-11-27 | The proxy refuses a presigned (query-string signed) DELETE with 403 AccessDenied, with CLI credentials as with dashboard keys (2026-11-26), and accepts a DeleteObject signed in its headers (`aws s3 rm`, boto3) with the same CLI credentials. So the refusal on 2026-11-26 was the request form; dashboard keys with a header-signed DELETE are untested. The dashboard deletes a whole folder | Presigned DELETE through obstore's `sign()` on one stale object: 403; `aws s3 rm` on a throwaway object and on 461 stale Icechunk objects: deleted, then GET 404; `s3_sync.py --delete` and `s3_rm.py --yes` (boto3 DeleteObject) on `mdstest/s3sync-delete-test/`: deleted, then GET 404; `tests/s3_sync_delete.py` (request form) |
| 2026-11-27 | source-coop CLI 0.3.0 has `login` and `creds`. `login --duration` (`12h`, `1d`) sets the requested credential lifetime. `creds` renews expired credentials from the cached refresh token (scope `offline_access`). The README estimates the refresh token at 30 days (Ory's default), restarted at each renewal. Credentials renewed by `creds` on the VM expired 12 hours later (21:16 to 09:16 UTC); whether that came from a `--duration` or is the proxy's default is not separated | `source-coop login --help`; `source-coop creds \| jq -r .Expiration` |
| 2026-11-27 | On a server, `login` waits for the browser's redirect on `127.0.0.1:<port>`. Sign in over an SSH tunnel: `ssh -i <key>.pem -N -L 8400:127.0.0.1:8400 ubuntu@<VM>` from the laptop, then `source-coop login --port 8400` on the VM as the account that runs the publishes. The session is per account: a sign-in as `ubuntu` does not serve `mdsumner` | The 2026-11-27 sign-in |
| 2026-11-27 | Service accounts (GitHub Actions OIDC trust with no secret, or API keys expiring after 30 days, 90 days, one year or never) are in the CLI's unreleased `next` build, not 0.3.0. source.coop must first let the account own service accounts | CLI README, "Service accounts"; `source-coop --help` on 0.3.0 lists only `login` and `creds` |
| 2026-11-27 | Anonymous ListObjectsV2 on `https://data.source.coop/<account>/<product>?list-type=2` returns keys that start with the product (`ausantarctic-scratch/seaice/...`). Join them onto `https://data.source.coop/<account>/`, not onto the product URL | `curl -s '.../ausantarctic/ausantarctic-scratch?list-type=2&prefix=seaice/&max-keys=1'` |
| 2026-11-27 | obstore's `S3Store` exposes `.prefix` and `.config` (bucket, endpoint, region, credentials, `virtual_hosted_style_request`), so a boto3 client can be built for the same store | `S3Store(...).config` in the image (obstore 0.12.1) |
| 2026-11-23 | Size alone misses a rewritten file. The first MEOP resume compared sizes and left `store.sqlite` and `stac/items.parquet` as the 19 Nov copies. `s3_sync.py --skip-same-size` compares ETags since #113 | ETag of each local file against the anonymous listing |
| 2026-11-23 | Publish gate (#103): `plan`, `harvest`, `collate`, `render`, `icechunk` and `grist` remove `out/verify.json`, and `publish` refuses without it | `run.sh <config> publish` on a build without `verify.json` |
| 2026-11-26 | The public forms of a COG product reference the published COG URLs, so `verify` runs after the COG upload (#120) | `hpc/vm/bedmap3-publish.sh`, `ibcso-publish.sh` |
| 2026-11-26 | The `generator` stamp is written at `collate` (`R/collate.R`, `E2E_GENERATOR`). A republish that skips collate keeps the collate build's commit | `generator` in a republished store's meta |
| 2026-11-27 | A git worktree fails inside the build container: its `.git` file points outside the mount. Build from a plain clone | #125 log, 2026-11-27 |

## Icechunk

| Date | Fact | Check |
|---|---|---|
| 2026-11-26 | Icechunk 2.3.1 names objects at random, and `render_icechunk.py` creates a new local repository per build. A republish uploads new names, and the previous build's objects stay in the published folder. On 2026-11-26: 27,435 (meop-ctd-tags), 48 (meop-ctd-2024) and 421 (MUR) | Anonymous ListObjectsV2 of `<store>/icechunk/` against the local build |
| 2026-11-27 | The #125 republishes left the previous build in place. Published against built objects: G02202 south 119/61, north 119/61, ASI south 231/79, OISST 389/196. The 461 old objects were deleted the same day; nothing else changed | The same listing against `rv-assert2/work/assert-<dataset>/out/icechunk`; whole-store ETag compare and an anonymous Icechunk open afterwards |
| 2026-11-27 | A relocatable Icechunk ref is `vcc://<container>/<rest>`, resolved through the repository's named virtual chunk container (for Bluelink, `g-data-gb6` with the THREDDS prefix). icechunk-python reads it (a relocatable `eta_t` build gave the same verify digests as the VRT and kerchunk forms), and so does icechunk-js (the viewer's `browser` asset is relocatable) | `verify` on a `--relocatable` build; #126 viewer tests |
| 2026-11-27 | GDAL's Icechunk driver does not resolve `vcc://` refs: "Access to non-network chunk location ... disabled by default", and with `ICECHUNK_ALLOW_LOCAL_CHUNK_LOCATION=YES` "Cannot open vcc://g-data-gb6/...". Master `948f102a` has no `vcc://` handling in `frmts/icechunk` | `gdal.OpenEx("ICECHUNK:<relocatable repo>", OF_MULTIDIM_RASTER)` then a read, GDAL 3.14.0dev-fedfd3ec89; `git grep vcc:// -- frmts/icechunk` |
| 2026-11-27 | Remap roots are named per byterefs decision 0014: a config's `REMAPS` rule takes an optional fourth field (`target\|prefix\|replacement\|root`), the store's `remap` table has a `root` column (added on first use in an older store), and `arrays.json` writes `root` only on named rules. A store republished from the published `store.sqlite` gets the config's rules with the `remap` step (no collate). The unnamed slug follows 0014's text: `/vsicurl/https://` gives `vsicurl` (it gave `root` before) | `tests/remap_roots.R`, `tests/remap_roots_render.py`; `run.sh config/bluelink.sh remap render` on the published `eta_t` store, then `render_icechunk.py --relocatable`: container `bran2023` at the THREDDS prefix |
| 2026-11-26 | The `repo` file names the branch snapshots. `s3_sync.py` uploads it after every other file (#121), so `main` never names a snapshot that is not yet up | `icechunk_pointers()` in `py/s3_sync.py` |
| 2026-11-26 | `expire_snapshots` and `garbage_collect` exist in Icechunk 2.3.1. They delete objects, through Icechunk's own S3 client; whether the proxy accepts its delete requests is untested | Icechunk API |
| 2026-11-27 | Icechunk keys virtual chunk containers by URL prefix. Two remap roots whose prefixes coincide under one target overwrote each other's container, and every ref under the first was rejected | #126, `py/render_icechunk.py` (shared container, `byterefs_roots.container`) |

## GDAL readers

| Date | Fact | Check |
|---|---|---|
| 2026-11-26 | GDAL reads multidim VRT `<Overviews>` from 3.13 (OSGeo/gdal `ccb731e17a`, 2026-01-20). 3.12.3 ignores the element. The classic view keeps levels of the same rank and data type. BedMachine `bed`, 1000 x 1000 through `AsClassicDataset()`: 191 s without, 8 to 9 s with | `tests/mdim_vrt_overviews.R`; overview count of the array and of its classic view |
| 2026-11-26 | GDAL 3.12.3 to master read `<SourceBand>` sources with a `count * step` RasterIO window. An index view returns the no-data value (0 where none is set) with no error. A strided view fails at the edge, or returns decimated or overview values. `[0:1]` and other contiguous slices are correct | mdsumner/osgeo-upstream `notes/2026-11-26-mdim-classic-strided-read-repro.py` |

| 2026-11-27 | A Bluelink plan (sources at `/g/data` paths, built on NCI) verifies on the VM with `SOURCE_READ_REMAP=/g/data/gb6/=/vsicurl/https://thredds.nci.org.au/thredds/fileServer/gb6/` (set by `config/bluelink.sh` where `/g/data/gb6` is not mounted): the plan reference reads all 403 sources over THREDDS | `assertion-republish.sh build bluelink-daily-eta_t`: six windows SAME in every form, scale and fill ok |
| 2026-11-27 | Re-rendered Bluelink `eta_t` opens with plain `xr.open_zarr`: Zarr `fill_value` -1e20 (float32) and the CF `_FillValue` attribute base64-encoded (Zarr v3). With the image's development builds (xarray 2026.4.1.dev32, dask 2026.6.0.post13), `.values` on a dask-backed variable returns an object array of dask arrays; `chunks=None` reads float32 with the fill masked | `xr.open_zarr(session.store, consolidated=False, chunks=None)["eta_t"]` on the build |

| 2026-11-28 | `py/thumbnail.py` opens the newest placement's source path from the store, so on the VM the Bluelink republishes drew no thumbnail ("/g/data/gb6/...: No such file or directory") and their collections lost the asset. With `SOURCE_READ_REMAP` (renamed from `VERIFY_PLAN_REMAP`) it reads the source over THREDDS | `run.sh config/bluelink.sh config/source-coop.sh stac` on the `eta_t` republish build: `eta_t [0] from ocean_eta_t_2026_07.nc`, 9 collection assets |
| 2026-11-28 | In the build container the netCDF driver refuses `/vsi` paths (no userfaultfd), so `py/thumbnail.py` reads netCDF-4 sources with the HDF5 driver. Its classic mode lists only 2D and 3D datasets as subdatasets: a BRAN file with a 4D field (`temp`, `salt`, `u`, `v`, `w`) opens as its one 2D dataset, `Time_bnds` (2 x 31), and the thumbnail drew that (1.735e+04 to 1.738e+04, days since 1979). The HDF5 multidimensional driver gives no scale or offset for CF-packed int16 (`GetScale()` returns None; `scale_factor` and `add_offset` stay attributes) | `tests/thumbnail_subdataset.py`; `gdal.OpenEx(<THREDDS URL>, gdal.OF_RASTER)` with netCDF deregistered: description ends `://Time_bnds` |

## Browsers and hosts

| Date | Fact | Check |
|---|---|---|
| 2026-11-28 | The Portolan browser (browser.portolan-sdi.org, portolan-browser `026734e`, deployed 2026-11-26) reports every Bluelink variable as declaring "no spatial reference". Its GeoZarr parser, `@developmentseed/geozarr` 0.9.0, matches `spatial:dimensions` by label (`y`/`lat`/`latitude`, `x`/`lon`/`longitude`) and rejects `["yt_ocean","xt_ocean"]`. The browser's fallback from coordinate arrays matches the same names, and reads a CF grid mapping only after they match. The spatial convention orders `spatial:dimensions` by role (Y, then X), with any names. geozarr 0.10.0 reads them by position (developmentseed/deck.gl-raster #785, from #451), and deck.gl-zarr 0.10.0 depends on it; the browser pins `^0.9.0` for both | `upstream/portolan/browser-check.mjs` (portolan-browser's `makeZarrLayerProps` run in Node, with zarrita, icechunk-js and geozarr at the browser's versions) against each published collection: all nine Bluelink `zarr-no-geo` with geozarr 0.9.0, all pass with 0.10.0. deck.gl-zarr 0.9.0's `ZarrLayer` parses the attributes again with its own geozarr (`dist/zarr-layer.js`), so geozarr 0.10 alone does not fix the draw |
| 2026-11-28 | deck.gl-raster 0.10 layers take `source` in place of the props portolan-browser passes (`COGLayer` `geotiff`, `ZarrLayer` `node` and `metadata`). Given the old props, `loadMetadata` returns with no source and raises no error, so the layer draws nothing. With the four packages at 0.10, portolan-browser's 917 unit tests and its build pass, and no e2e test draws a raster. Renovate's grouped non-major update (portolan-browser #116, org default `automerge: true`, `schedule:earlyMondays`) carries the four packages | `upstream/portolan/layer-old-props.mjs` in a portolan-browser checkout with the 0.10 packages; `pnpm run test:unit` and `pnpm run build` there |
| 2026-11-28 | In the same check the G02202 south and north, ASI south and G02202 south `browser/` test copy Icechunk assets pass the georeference checks (no `zarr-no-geo`, no `zarr-crs`). Their collections, published before #126, still type the kerchunk asset `application/vnd+zarr`, which the browser lists as Zarr and fails to open (OISST too); the next `stac` render fixes it | As above |
| 2026-11-28 | Bluelink collections have no `renders` entry, so the Portolan browser draws with a colour ramp from 0 to 1 ("the image may saturate"). Only `config/seaice-g02202.sh` sets `STAC_RENDERS` | As above: the browser's warning |
| 2026-11-27 | GET with an `Origin` returns `Access-Control-Allow-Origin: *` from data.source.coop, the NOAA OISST bucket, the IMOS bucket, projects.pawsey.org.au and thredds.nci.org.au. THREDDS answers 403 to HEAD with an Origin. noaadata.apps.nsidc.org and data.seaice.uni-bremen.de send no CORS header | `curl -s -o /dev/null -r 0-15 -H 'Origin: https://example.org' -D - <url>`; #99, item 4 |
| 2026-11-27 | A kerchunk asset typed `application/vnd+zarr` makes the Portolan browser open it as a plain Zarr store, find `.zmetadata`, then 404 on the chunks | #126 (asset type `application/x-kerchunk-parquet`) |
| 2026-11-27 | ASI south through the relay takes 2,656 chunk requests per field (one per row chunk), about 26 s; icechunk-js does not merge them | #126 test table |
| 2026-11-28 | `py/thumbnail.py` rotated polar stereographic grids as if x were 0..360 longitude. Rotation is removed; the preview is the array as stored, with only the south-up flip | #125 log, 2026-11-28 |

## Conventions

| Date | Fact | Check |
|---|---|---|
| 2026-11-28 | zarr-conventions/spatial has one tag, `v0.1`. The `zarr_conventions` registration written since #125 named `refs/tags/v1` and `blob/v1`, both 404 (the UUID is right). Fixed to `v0.1`; stores published before the fix carry the 404 URLs until their next render | `gh api repos/zarr-conventions/spatial/tags`; `curl -o /dev/null -w '%{http_code}'` on each URL |

## Store and pipeline scale

| Date | Fact | Check |
|---|---|---|
| 2026-11-23 | One chunk table and one view per array does not scale to tens of thousands of arrays. SQLite reads `sqlite_master` again after every CREATE: about 57 ms each at 27,000 arrays (meop-ctd-tags: 564 groups, 27,432 arrays, 54 min). The flat, kerchunk and Icechunk forms are one object per array each, so about 82,000 objects | `config/imos-meop.sh` per-tag build log |
| 2026-10-21 | BRAN2023 `temp` 2010, 1,116,900 refs: collate 12 s, render 16 s, Icechunk 5 s | `config/bran.sh` build log |

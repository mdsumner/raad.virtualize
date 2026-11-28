# Status

Open work for raad.virtualize and the stores it publishes: pull requests in
flight, the republish queue, open issues, decisions and dangling threads. A
PR that starts, finishes or parks a thread updates this file. Facts learned
on the way, each with its check, are in [LEDGER.md](LEDGER.md).

Last updated 2026-11-28 (third update).

## Pull requests in flight

None.

Merged since the last update: #125 (assertion step), #128 (header-signed
DeleteObject in `s3_sync.py`), #129 (`verify --plan-remap`), #130 (named
remap roots, the `remap` step), #131 (`SOURCE_READ_REMAP` for the
thumbnail), #132 (`thumbnail.py` reads 4D HDF5 fields and CF packing).
#126 (viewer, browser step, STAC renders and viewer link) and #127 (this
file) merged on 2026-11-27. xpystac, checked before #126 merged,
opens an asset by media type: `application/vnd+zarr` opened the kerchunk
Parquet folder as a plain Zarr store, and `application/x-kerchunk-parquet`
matches no reader, so nothing that opened before stopped opening; the
Icechunk asset is unchanged.

## Republish queue

Each dataset is republished once per batch of new schemes: every Icechunk
republish leaves the previous build's objects behind (LEDGER, 2026-11-26),
and each removal is one more pass with `s3_sync.py --delete`. The schemes:

- **A**: assertions (#125). Needs `assertions/<dataset>/`.
- **O**: `<Overviews>` in the mdim VRT (#122, merged). Any `render` from
  `93f68a3` on.
- **V**: viewer (#126). The STAC link comes from the `stac` step. A
  `browser` asset is needed only where the chunk host sends no CORS header
  (the relay).
- **R**: the float `_FillValue` fix (#117, closed). Bluelink only. The
  relocatable default was dropped (Open issues).

`#121` (Icechunk `repo` file uploaded last) applies to every republish and
needs no step.

| Group | Dataset | A | O | V | State |
|---|---|---|---|---|---|
| seaice | g02202-v6-daily-south | done | n/a | relay; browser rules in config (#126) | Republished with A; Icechunk cleaned 2026-11-27. `remap` (sets the config's browser rules in the published store; no re-collate), then `browser stac publish`. Keep the `browser/` test copy (linked from elsewhere) until Michael retires it |
| seaice | g02202-v6-daily-north | done | n/a | relay | Republished with A; Icechunk cleaned 2026-11-27 |
| seaice | asi-amsr2-v5.4-daily-south | done | n/a | relay; no browser rules yet | Republished with A; Icechunk cleaned 2026-11-27. Row chunks: 2,656 requests per field through the relay |
| oisst | oisst-v2.1-daily | done | n/a | direct | Republished with A; Icechunk cleaned 2026-11-27 |
| ghrsst | ghrsst-mur-cog-analysed_sst | done | done | done (link) | Republished 2026-11-27 from main `44e6bc0` (A, O, V): `verify-published` passes, 299 old Icechunk objects deleted, 644 files match the build with nothing extra, the repository opens anonymously at `main` `PXBQEF86` |
| bluelink | bluelink-daily-{temp, salt, eta_t, mld, u, v, w, tx_trans_int_z, ty_trans_int_z} | done | n/a | direct, untested (THREDDS answers 403 to HEAD with an Origin) | Republished 2026-11-28 from main `9e747fc` (A, the `_FillValue` fix, absolute Icechunk refs, root `bran2023`), built on the VM through THREDDS (`SOURCE_READ_REMAP`). `verify` and `verify-published`: 29 SAME, 0 DIFFERENT for each. Old Icechunk objects deleted (43 each for the four 3D stores, 192 each for `temp`, `salt`, `u`, `v`, 163 for `w`). Thumbnails and collections republished (`publish-stac`): `eta_t`, `mld`, `tx_trans_int_z`, `ty_trans_int_z` from main `3896ff4`, `temp`, `salt`, `u`, `v`, `w` from main `f905e24`. Each store matches its build by ETag with nothing extra |
| bedmap | bedmap3 | documents ready (EPSG:3031, 7 arrays) | pending | direct | `hpc/vm/bedmap3-publish.sh` (production product; `assertion-republish.sh` refuses it) |
| bedmachine | bedmachine-v4.1 | documents ready (EPSG:3031, 10 arrays) | pending | direct | `hpc/vm/bedmachine-publish.sh` |
| ibcso | ibcso-v2, ibcso-annual-2024, ibcso-annual-2025 | documents ready (EPSG:9354, 4 arrays each) | pending | direct | `hpc/vm/ibcso-publish.sh` |
| gebco | gebco-2024, gebco-2025, gebco-2026 | documents ready (EPSG:4326, `elevation`) | pending | direct | `hpc/vm/gebco-publish.sh` |
| oceancolour | esacci-oc-v6.0-{monthly, 5day}-{chlor_a, chlor_a_log10_bias, chlor_a_log10_rmsd} | no documents (EPSG:4326) | pending | direct (Pawsey) | Built on Pawsey (`hpc/pawsey/`) |
| imos-tracking | meop-ctd-2024, meop-ctd-tags | n/a (profiles) | n/a | n/a (not a grid) | Nothing to republish |
| access-esm | access-esm1-6.historical.ocean-3d-temp-1mon-mean | n/a (tripolar ocean grid) | n/a | not drawable as an affine grid | Nothing to republish |

The four republished stores held the previous build's Icechunk objects
(58, 58, 152 and 193). They were deleted on 2026-11-27 with `aws s3 rm` and
CLI credentials, after checking that each published `repo` file equals the
build's and every build file is published. Afterwards each store matches
its build by ETag with nothing extra (G02202 south keeps its 120 `browser/`
objects), and each repository opens anonymously at the build's `main`
snapshot, array tree and first chunk.

Suggested order:

1. Merge #125 and #126, so each later republish carries A, O and V
   together. Done 2026-11-27.
2. Remove the old Icechunk objects of the four republished stores. Done
   2026-11-27.
3. MUR: `assertion-republish.sh build` then `publish`. Done 2026-11-27.
4. Bluelink, nine variables: one republish each with A and the
   `_FillValue` fix, absolute refs, verified on the VM through THREDDS.
   Done 2026-11-28, thumbnails included.
5. COG products (Bedmap3, BedMachine, IBCSO, GEBCO): write assertion
   documents from each COG's CRS, then use each product's publish script.
   Documents written 2026-11-28 (32, one per base array; each applies to
   the published store and plan, overview levels included); the cards
   workflow covers the eight datasets. The publishes are next.
6. Sea ice viewer pass: the browser rules for ASI, then `remap browser stac`
   and a publish for each sea ice store (`remap` sets the config's rules in
   the published store, so no re-collate).
7. ESA CCI: assertion documents, then a build on Pawsey.

Credentials: `eval "$(source-coop creds --format env)"` on the VM (CLI 0.3.0,
signed in 2026-11-27; credentials for 12 hours, renewed by `creds`). Each
publish that replaces an Icechunk repository ends with `s3_sync.py --delete`
on its `icechunk/` prefix (`delete_one` sends a header-signed DeleteObject
through boto3; the proxy refuses the presigned DELETE it sent before). See [docs/production.md](docs/production.md).

## Open issues

#117 (relocatable Icechunk by default, Bluelink re-render) closed
2026-11-28. GDAL's Icechunk driver does not resolve `vcc://` refs
(icechunk-python and icechunk-js do), so the published stores keep absolute
refs. On NCI, read the netCDF in place or render a local relocatable
Icechunk from the flat refs (root `bran2023`). The re-render fixed the
float `_FillValue`: the published `w`, `mld` and `tx_trans_int_z` open with
plain `xr.open_zarr(..., chunks=None)`.

| Issue | What | Next |
|---|---|---|
| #99 | storecard findings on the scratch stores | 1 (no CRS): fixed by A where republished. 2 (BRAN `coordinates` names absent arrays): open. 3 (kerchunk form drops CF `_FillValue`): open. 4 (hosts without CORS): the relay (#126) |

## Decisions

- IBCSO: the product move into AustralianAntarcticDivision/ibcso pins
  `v0.1.0`; a licence for that repo; `ibcso/virtual/ibcso-v1/`: catalogue
  or drop.
- BedMachine owner: `research` in `products/bedmachine/datasets.tsv` until
  it joins the production set.
- Nesting option A to D (per-product repo map). The GHRSST index beside its
  bytes (`ghrsst-mur-v2/virtual/`) is option B.
- Bluelink combined store (one group, nine variables): sets which repos go
  to production first.
- Spec decision 0015 (`srs` per array) is not in byterefs/spec. #125 carries
  the CRS into every form, including `<SRS>` in the VRT. Either record the
  assertion route in 0015 or drop it. The Bluelink brief that proposed 0015
  has not been seen by these sessions.
- `mdstest/uploadtest.tif` (2024): keep or delete.
- Root names for the G02202 browser rules. Unnamed, the browser root
  `/vsicurl/https://` takes the slug `vsicurl`; proposed: name the NSIDC
  product path (for example `nsidc-g02202-v6`).

## Dangling threads

Publishing:

- Every Icechunk republish leaves the previous build's objects behind (new
  local repository per build, random object names). They are removable now
  (`s3_sync.py --delete` with CLI credentials). Committing into the
  published repository would avoid them.
- A source-coop CLI session also exists for the `ubuntu` account (the
  2026-11-27 sign-in was first made there). Remove it if unused: 0.3.0 has
  no logout command, so delete that account's `~/.cache/source-coop`.
- `~/Git/rv-assert2` (#125 branch at `c343c41`, untracked
  `work-build-rest.out`) and `~/Git/rv-thumb` (#131 branch) are no longer
  needed: #125 and #131 merged and the old objects are cleaned.
- Credentials were printed into a session transcript on 2026-11-23 (CMEMS,
  Earthdata, GitHub, TERN). Rotate them if the transcript is shared or kept.

Products and sources:

- GHRSST:
  - The trend.sst provisional tail (ten days) is shorter than the upstream
    changes observed (granules 5 to 16 days old).
  - ghrsst-cogger rewrites each COG once, about 5 days after the date.
    Upstream granules changed later than that (2026-10-31 to 11-04) without
    a COG rewrite. For the production team to check whether those were data
    changes.
- ACCESS-OM2-01 waits for COSIMA to confirm that an index may be published
  (cj50 licence CC BY-NC-ND 4.0). Its `hpc/nci/standing.tsv` row is
  commented out.
- Listing corpus (aad-filelist):
  - BRAN2020 is a THREDDS dry run with no sizes. A size check of the
    Bluelink stores before 2010 waits for THREDDS HEAD access.
  - Ocean colour monthly: `oceancolour_cci_v6_chlor_a` dropped all 349
    monthly files on 2026-11-16. Michael is checking it on Pawsey.
  - `cordex-polarres-ant12-metum-bas` listed 0 URLs in the 2026-11-23 run.
    Michael's clone has an uncommitted edit to `sources/metum_bas.R`.

Metadata and specification:

- byterefs/spec decision 0014 (named remap roots, proposed): its heading
  reads "0011". raad.virtualize follows it: `REMAPS` take an optional fourth
  field `root`, the store's `remap` table has a `root` column, and the slug
  rule is the decision's text.
- storecard (from #125): its MUR document is stale (overview levels came
  later). Moving `assertions/ausantarctic` to settled is still to do.
- Attribute types in the store: xarray decodes packed int16 to float64,
  because the JSON attributes do not keep the float32 type of
  `scale_factor`.

Upstream:

- GDAL, index and strided reads of `<SourceBand>` VRT sources (README known
  limit, #123). The issue draft is in mdsumner/osgeo-upstream
  `notes/2026-11-26-mdim-classic-strided-read-issue.md`; not filed.
- GDAL, `numcodecs.shuffle` in Zarr v3 (OSGeo/gdal#15565, open). Needed for
  GDAL to read the shuffled arrays of the Icechunk form.
- deck.gl-raster does not draw polar grids, which blocks Portolan for the
  sea ice, Bedmap3, BedMachine and IBCSO stores
  ([docs/viewer-strategy.md](docs/viewer-strategy.md)).
- icechunk-js does not merge chunk requests (ASI: 2,656 requests per field).
- GDAL's Icechunk driver does not resolve relocatable `vcc://<container>/`
  refs through the repository's named containers ("Cannot open vcc://..."),
  so relocatable stores are for icechunk-python and icechunk-js readers.
  Reproducer and issue draft in mdsumner/osgeo-upstream
  `notes/2026-11-27-icechunk-vcc-*` (gap G of
  `notes/2026-11-16-icechunk-driver-gaps.md`); not filed.
- THREDDS reset the connection ("Connection reset by peer") when
  icechunk-python read nine chunks of one `mld` field at once from the
  published store, and the Python process then crashed in its exception
  handler. One chunk at a time reads. Whether THREDDS limits concurrent
  connections is not separated.

## Production jobs

Deferred until the republish queue is through. The plan is in
[docs/production.md](docs/production.md).

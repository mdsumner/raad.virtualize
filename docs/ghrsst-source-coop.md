# GHRSST virtual indexes on source.coop

Layout of the byte-reference indexes (flat refs, kerchunk Parquet, Icechunk,
MDIM VRT, STAC) for the GHRSST MUR COGs in the source.coop repository
`ausantarctic/ghrsst-mur-v2`, the trial procedure in this repository, and the
changes to `AustralianAntarcticDivision/ghrsst-cogger` that would take the
procedure over.

Status: draft. Nothing has been written to source.coop yet. Credential and
product details are from the source.coop documentation (docs.source.coop,
read 2026-10-29) and are untested here.

## Repository layout

The COGs and the cogger VRT stay where they are. The indexes go under one
new top-level prefix, `virtual/`, one directory per dataset (a dataset is
one store and its rendered forms; several can sit side by side).

```
ausantarctic/ghrsst-mur-v2/
  YYYY/MM/DD/<date>090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1_<var>.tif
  ghrsst-mur-v2.vrt                 cogger VRT (unchanged)
  virtual/
    <DATASET>/
      mdim.vrt                      GDAL multidim VRT (SourceSlab counts)
      kerchunk/                     kerchunk Parquet, fsspec layout (Zarr v2)
        .zmetadata
        <var>/refs.<n>.parq
      icechunk/                     Icechunk repository, branch main
      flat/                         flat refs store
        arrays.json
        sources.parquet
        refs_<var>.parquet
      stac/
        collection.json             one asset per form above
        items.ndjson                one item per COG
        items.parquet               stac-geoparquet (where rustac is installed)
      plan.vrt                      plan, verbatim source URIs
      store.sqlite                  mdim-refs/0.2 store
  dev/
    virtual/<DATASET>/              trial, same layout as virtual/
```

Notes on the layout:

- Every form references the COGs by absolute URL
  (`https://data.source.coop/ausantarctic/ghrsst-mur-v2/YYYY/...`), so a
  dataset directory can be copied between prefixes unchanged. Only the STAC
  collection holds its own location (`STAC_BASE`): promotion from `dev/` to
  `virtual/` is a copy of the directory followed by a re-render of `stac/`
  with the new base.
- The source listing in `config/ghrsst-cog.sh` takes only four-digit
  top-level names, so `virtual/` and `dev/` are not mistaken for data. Any
  listing in ghrsst-cogger that walks the repository root needs the same
  check (not confirmed; the cogger code was not reviewed for this draft).
- `dev/` is public and visible in the source.coop browser. It carries a
  `README.md` stating that its contents are transient and may be removed
  without notice.
- The Icechunk repository registers one virtual chunk container,
  `https://data.source.coop/`. Readers authorize it with
  `icechunk.credentials.HttpAccess` (anonymous).

### Dataset names

Current: `ghrsst-mur-cog-<var>` (one array per store, from
`config/ghrsst-cog.sh`), with a year suffix for subsets.

Target: one dataset holding every array that cogger writes
(`analysed_sst`, `analysis_error`, `mask`, `sea_ice_fraction`, and the
others cogger adds), under a name without the variable, such as
`mur-daily`. One Icechunk repository and one kerchunk directory then serve
an xarray Dataset with all variables on one time axis. This needs
`py/plan_cog.py` to place several arrays from per-variable files (one
`--array` and pattern per variable), which it does not do yet.

### Sizes

From the full `analysed_sst` series (8909 days, 22,771,404 refs, built on
the Nectar VM, 2026-10):

| Item | Size or time |
|---|---|
| store.sqlite | 1.2 GB |
| Icechunk | 568 MB, 23 commits, 105 s |
| harvest (GDAL, py/harvest.py) | 17 min |
| harvest (async-tiff via rustycogs, IFD 0 and overviews) | 137 s, 30.5M rows |
| collate | 6 min |
| render (flat, VRT, kerchunk) | 5 min |

A five-array dataset is roughly five times these sizes, except where
arrays are smaller (mask is Byte).

## Trial procedure

### Test product

The first trial goes to a separate, unlisted source.coop product rather
than to `dev/` in the production product. A separate product needs no
change to `ausantarctic/ghrsst-mur-v2`, its credentials cannot write to the
production data, and it can be emptied or abandoned without coordination.
The forms reference the COGs in `ausantarctic/ghrsst-mur-v2` by absolute
URL, so they work from any product.

- Create the product under a personal account or an organization the
  person is owner or maintainer of (top-right menu, after beta access is
  granted), for example `mdsumner/ghrsst-mur-virtual-test`. New products
  are unlisted: readable by URL, absent from search.
- Product ID rules: 3 to 39 characters, letters, digits and single hyphens,
  not starting or ending with a hyphen.
- The source.coop documentation does not describe deleting a product;
  plan on emptying it instead.

Inside the test product the layout is the production one from the
`virtual/` level down (`virtual/<DATASET>/...`), so promotion is the same
copy plus `stac/` re-render described above.

### Credentials

Three ways to get write credentials, all exchanged at the data proxy
(`https://data.source.coop`; any region value is accepted):

| Method | Use | Lifetime |
|---|---|---|
| "View Credentials" on the product page | one-off runs | temporary, expiry shown |
| `source-coop login`, then `source-coop creds` (AWS `credential_process`) | interactive runs | one hour, renewed by AWS CLI and SDKs; login every 30 days |
| service account: API key (`sck_...`) or GitHub Actions OIDC | scheduled jobs (cogger) | one hour per exchange; GHA up to 12 h with `role-duration-seconds` |

All three give an `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`AWS_SESSION_TOKEN`. Exported keys are not renewed, so a publish that
runs past an hour fails with `ExpiredToken`. A one-year trial is well under
that; a full-series publish goes in parts. Service account keys are
exchanged through STS at `https://data.source.coop/.sts`; GDAL would send
them to AWS STS instead, so `config/source-coop.sh` sets
`CPL_AWS_WEB_IDENTITY_ENABLE=NO`.

A service account is scoped to products its owner owns, with Read or Read
and write per product. For cogger, a GitHub Actions trust on the cogger
repository and branch avoids storing a secret.

### GDAL writes

On 2026-10-29 the proxy accepted writes from Icechunk with the product's
temporary keys but rejected every signed GDAL `/vsis3/` request (PUT,
multipart initiate, list) with `InvalidRequest: missing SignedHeaders`.
Anonymous GDAL reads work. The likely cause is the proxy's parsing of the
`Authorization` header that GDAL writes (not confirmed). Until that is
resolved, `config/source-coop.sh` sets `PUBLISH_WITH=obstore`, and the
publish step uploads with `py/s3_sync.py` (obstore) instead of
`gdal vsi sync`. The image needs `pip install obstore`.

### Write check

`py/sourcecoop_check.py` writes under `<product>/_write-check/<time>/` and
removes what it wrote: a small PUT and a 120 MB multipart PUT (obstore), a
listing, an anonymous https read, an Icechunk repository created and
committed twice directly on the proxy (conditional writes, needed for later
in-place commits), a GDAL PUT (informational), and deletes.

```sh
# needs the product's AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN exported
python py/sourcecoop_check.py mdsumner/ghrsst-mur-virtual-test
```

### Build, publish, read back

`config/source-coop.sh` is the publish target. `SOURCECOOP_REPO` names the
product (default `ausantarctic/ghrsst-mur-v2`, where any prefix outside
`dev/` is refused unless `SOURCECOOP_PRODUCTION=1`), and `STAC_BASE` is set
to the public URL of the dataset directory.

```sh
export SOURCECOOP_REPO=mdsumner/ghrsst-mur-virtual-test SOURCECOOP_PREFIX=virtual GHRSST_YEARS=2024
# build and verify locally
bash run.sh config/ghrsst-cog.sh config/source-coop.sh
# publish (product credentials exported)
bash run.sh config/ghrsst-cog.sh config/source-coop.sh publish
# read back anonymously, as a public reader
env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN AWS_NO_SIGN_REQUEST=YES \
  bash run.sh config/ghrsst-cog.sh config/source-coop.sh verify-published
```

The `stac` step must run with `config/source-coop.sh` sourced, so that the
collection carries the public base. Because the forms are rendered before
`publish`, a local build of the same dataset can be published to the AADC
transfer bucket and to source.coop without a rebuild, apart from `stac/`.

## Checks before anything goes outside dev/

1. Completeness: the harvested source count equals the listed COG count,
   and every source has its full tile grid (an earlier full run lost 19
   sources to HTTP 503 from data.source.coop without failing). The build
   stops on a shortfall rather than publishing a shorter series.
2. Overviews: the contract states whether overview IFDs are indexed. The
   current stores index IFD 0 only (22.77M refs); the async-tiff harvest
   returns overviews too (30.5M rows). Proposed for version 1: IFD 0 only.
3. Anonymous read-back passes for VRT and Icechunk (kerchunk via GDAL stays
   a known limit until GDAL Zarr reads the TIFF predictor filter).
4. The async-tiff harvest is the harvest step for COG sources, with the
   GDAL harvest kept as the cross-check.

## Update cadence

MUR rewrites its newest days for several days after first publication, and
a full rescan takes minutes, so each run rebuilds the dataset from a full
listing. What changes between runs:

- flat refs, kerchunk, VRT, STAC: rewritten whole. The kerchunk record
  files are ordered with time first, so only the last records differ. The
  publish step syncs by timestamp, so every rewritten file is uploaded; a
  content (ETag) sync strategy would upload only the changed ones.
- Icechunk: a full rebuild produces a new repository with no history.
  Commit continuity (one commit per new or changed day on an existing
  repository) is a later step and needs `--split 1` on the time axis so
  that a day's commit rewrites one manifest.
- store.sqlite (1.2 GB per array): uploading it each day is the largest
  cost. Open: publish it only on a slower cadence, or not at all and keep
  the flat refs as the published contract.

## ghrsst-cogger update plan

cogger already writes the COGs, holds the source.coop credential and knows
when a new day has landed, so it owns the trigger; this repository owns the
engine and the store contract.

1. Pin the engine: cogger calls `run.sh` from a tagged release of this
   repository (or its successor) in the `gdal-r-python-extras` image, with
   `config/ghrsst-cog.sh` (multi-array form) and `config/source-coop.sh`.
2. Trigger: after cogger's daily COG write succeeds, a job runs plan,
   harvest, collate, render, icechunk, stac, verify, then publish and
   verify-published to `virtual/` (`SOURCECOOP_PRODUCTION=1`).
3. Runner: a GitHub Actions job in cogger (standard runner: 4 CPU, 16 GB,
   about 14 GB of disk) fits a full rebuild of one array (about 15 min
   with the async-tiff harvest); five arrays need the work directory on a
   larger runner or a per-array split. AWS Lambda does not fit (15 min
   limit, 10 GB of /tmp). Pawsey (Setonix, Slurm) is the interim runner.
4. Failure policy: verify or completeness failure stops before publish and
   leaves the previous `virtual/` contents in place.
5. Provenance: the store meta records the engine commit and config; the
   STAC collection repeats it (`rv:meta`).

## Open questions

- Prefix name `virtual/` and dataset name `mur-daily`.
- Whether `store.sqlite` is published (see Update cadence).
- Whether the cogger VRT `ghrsst-mur-v2.vrt` is replaced by
  `virtual/<DATASET>/mdim.vrt` or kept alongside.
- Who at source.coop needs to know about the new prefix (the operators
  maintain the repository listing and URL rewrites).

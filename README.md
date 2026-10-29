# raad.virtualize

Virtualization of archival array collections (local file mirrors and online
datasets): one central store of byte references, from which published
cloud-native forms (kerchunk, Icechunk, VRT) are derived as projections.

This repo is a working stage and will change shape and name. This README
documents the model and the pipeline that implements it.

Project page (datasets, reader coverage, ongoing work):
<https://mdsumner.github.io/raad.virtualize/>, built from `docs/`.


## Design

Every array dataset consists of granules (netCDF, HDF5, COG, GRIB) in which
each chunk of each array occupies a byte range. Cloud-native access to
archival data (kerchunk, VirtualiZarr, Icechunk, GDAL multidim VRT) reduces
to knowing those byte ranges and pointing readers at them, but the tools
store the information in memory or in bespoke file stores.

In this project each granule is scanned once into a durable store. Every
published form is then a projection of the store: a remap of URIs, a
selection of files, an assignment of a global index, a serialization. The
expensive operation (reading chunk indexes out of thousands of HDF5 files)
runs once per granule.

## The store

The store is a SQLite database in the mdim-refs/0.2 layout (specification:
wxylib/design, `specs/mdim-refs-0.2.md`). It has three layers:

- **physical**: `sources` (one row per granule, the URI as harvested, size,
  mtime) and one chunk table per array, keyed on (source, within-source
  chunk coordinate), with `present`, `offset`, `size`
- **plan**: `arrays` (shape, chunks, dtype, codec, fill, attributes) and
  `placements` (where each source's slab lands in the global array), both
  taken from a `gdal mdim mosaic` VRT
- **view**: `refs_<array>` views that join the two into global chunk
  coordinates

`meta` records the dataset name, format version, creation time, the plan
file, and the code revision and configuration that built the store.
`remap` holds URI rewrite rules per publish target.

### The source rule

A source is the URI at harvest time (`/g/data/...`, `https://...`,
`/vsicurl/...`, `/vsis3/...`) recorded verbatim. That URI is the key that
byte offsets are bound to. Remap rules are stored beside the chunk tables
and applied only when a form is rendered (local root to public https,
/vsicurl/ to https, mirror to mirror); the chunk tables are never rewritten.

Because prelim/final churn arrives as *renamed files*, a given source string
is immutable content. Incremental harvest is "scan the sources not already in
the store". Preliminary and final versions of a day coexist in the store as
distinct sources; choosing between them is a projection.

## Projections

Dataset-specific logic lives in projections, applied at publish time:

- date extraction and global index assignment, delegated to `gdal mdim
  mosaic` (the plan)
- dedup policy (prefer final over preliminary, or keep both as two canons)
- URI remapping to whichever endpoint a published form should reference
- array metadata (dtype, chunk shape, codec, fill, coordinates), read from
  the plan and the first source

A "canon" is the store plus a projection: the OISST daily cube is the store
joined with the mosaic concatenation. One store can carry many canons.

## Published forms

Five renderings, all from the store and none derived from another:

1. **Flat refs store**: `arrays.json`, `refs_<array>.parquet` and
   `sources.parquet`. Read by wxylib (`wxy-refs`) and by any Parquet reader.
   `arrays.json` also states dimension types and directions and, per array,
   the chunk grid size, present and absent chunks and referenced bytes.
2. **GDAL multidim VRT**: rebuilt from `placements`, so it can be remapped.
3. **kerchunk Parquet**: fsspec layout, readable by xarray and by GDAL
   (`ZARR:"/vsikerchunk_parquet_ref/{DIR}"`).
4. **Icechunk**: virtual references, one virtual chunk container per source
   host.
5. **STAC**: a static catalog (`stac/collection.json`, `stac/items/`,
   `stac/items.ndjson`, and `stac/items.parquet` in stac-geoparquet form
   where `rustac` is installed). The collection describes the whole cube
   with the datacube extension and carries one asset per form above (VRT,
   kerchunk, Icechunk, flat refs, store, plan); each item is one source
   granule, with its time range from the plan placement, its bbox, and the
   projection fields where the grid is affine and the SRS known. The forms
   in 1 to 4 serve readers of the cube; STAC serves search, discovery and
   the granule-level readers (GDAL STACIT and GTI, gdalcubes, odc-stac,
   stackstac).

Each form carries the store's `meta` as root attributes (STAC: `rv:meta` on
the collection).

## Pipeline

```
sources --(plan: gdal mdim mosaic)------> plan.vrt
        --(harvest: py/harvest.py)------> scan/   one Parquet fragment per source
        --(collate: R/collate.R)--------> store.sqlite   mdim-refs/0.2
        --(render: R/render.R)----------> out/flat/  out/mdim.vrt  out/kerchunk/
        --(icechunk: py/render_icechunk.py, from out/flat)--> out/icechunk/
        --(stac: R/stac.R, from the store and plan)---------> out/stac/
        --(verify: py/verify.py)--------> every form against GDAL on the sources
        --(publish, verify-published)---> object storage, then read back and verified
```

```sh
bash run.sh config/bransynth.sh                  # synthetic BRAN-shaped, local, about 10 s
bash run.sh config/oisst.sh                      # OISST Sept 1981 from NOAA S3, about 1 min
BRAN_VAR=salt BRAN_MONTHS="01 02" bash run.sh config/bran.sh   # BRAN smoke test over THREDDS
BRAN_YEARS=2010 bash run.sh config/bran.sh       # one BRAN year, about 1.1M refs
bash run.sh config/bran.sh config/aadc-transfer.sh publish verify-published
GHRSST_ROOT=/path/to/MUR/v4.1 GHRSST_YEARS=2024 bash run.sh config/ghrsst.sh   # MUR netCDF, local
GHRSST_YEARS=2024 bash run.sh config/ghrsst-cog.sh   # MUR COGs on source.coop, one year
```

Every leading `*.sh` argument is sourced in order (a dataset, then
optionally a publish target). Steps can be named to run a subset
(`bash run.sh config/bran.sh collate render`). Work goes to
`work/<DATASET>/` (or `$E2E_WORK`), and each step logs to `log.txt` there.
Harvest is restartable: a source whose fragments exist is skipped.

| Variable | Meaning |
|---|---|
| `WORKERS` | parallel harvest workers |
| `HARVEST_ENGINE` | `auto` (h5py for local netCDF4/HDF5, GDAL for remote), `gdal`, `h5py` |
| `HARVEST_LIMIT` | scan only the first N sources |
| `ICECHUNK_ARGS` | extra `py/render_icechunk.py` options: `--split N` chunks along the first axis per manifest (default 365, 0 for none; set it to the append unit, such as 1 for daily, for a repository that later takes incremental commits), `--commit-every N` refs (default 1M) |
| `BRAN_YEARS`, `BRAN_MONTHS`, `BRAN_VAR`, `BRAN_ROOT` | BRAN selection; a month subset gets its own dataset name |
| `GHRSST_VAR`, `GHRSST_YEARS`, `GHRSST_COG_ROOT` | GHRSST COG selection (`config/ghrsst-cog.sh`) |
| `VERIFY_WINDOWS` | explicit `--window ARRAY:START:COUNT` checks |
| `STAC_TARGET` | remap target for STAC item hrefs (default `KERCHUNK_TARGET`) |
| `STAC_BASE` | URL of the published dataset prefix; collection asset hrefs become absolute and carry a GDAL open string (`rv:gdal`). Without it the hrefs are relative to the published layout. |
| `STAC_ITEM_FILES` | `0` skips `stac/items/` (one file per granule) for long series; the ndjson and stac-geoparquet forms remain |
| `PYTHON`, `RSCRIPT`, `GDAL` | executables |
| `R_LIB` | R library used ahead of the system one (default `./r-lib`) |
| `PUBLISH`, `AADC_PREFIX` | publish prefix (`/vsis3/...`), set by a publish config |
| `SOURCECOOP_REPO`, `SOURCECOOP_PREFIX`, `SOURCECOOP_PRODUCTION` | source.coop publish target (`config/source-coop.sh`) |

### Environment

conda-forge:

```sh
micromamba create -n rv -c conda-forge python=3.12 "gdal>=3.12" libgdal-netcdf \
  libgdal-hdf5 libgdal-arrow-parquet pyarrow numpy h5py fsspec aiohttp netcdf4 \
  icechunk zarr xarray r-base r-dbi r-rsqlite r-jsonlite r-xml2 r-arrow r-blob \
  imagecodecs fastparquet
```

`imagecodecs` and `fastparquet` are needed only for TIFF sources with a
predictor (the GHRSST COGs): the Icechunk render and the Python kerchunk
check in verify use them. In the docker image, `pip install imagecodecs
fastparquet`.

Or the hypertidy image, with the missing R packages installed once into
`./r-lib` by the `deps` step:

```sh
docker run --rm -ti -v $(pwd):$(pwd) -w $(pwd) \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY ghcr.io/hypertidy/gdal-r-python:dev bash
bash run.sh config/bran.sh deps
```

The container runs as root, so `work/` and `r-lib/` are root-owned on the
host. `deps` installs Posit Package Manager binaries for the distro where it
can, so arrow does not build from source.

### Publishing

`config/aadc-transfer.sh` targets the AADC transfer bucket
(`transfer.data.aad.gov.au`, path style; private, keys from the AADC
website). Credentials come from `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` in the environment and are not stored. `publish`
syncs `out/`, `plan.vrt` and `store.sqlite` to `<prefix>/<DATASET>/`.
`verify-published` reads the VRT, kerchunk and Icechunk forms back from the
bucket and checks them against GDAL on the sources.

`config/source-coop.sh` targets a source.coop repository (default
`ausantarctic/ghrsst-mur-v2`) through the data proxy S3 API, with the
source.coop API key pair in the same variables. It requires
`SOURCECOOP_PREFIX` and refuses any prefix outside `dev/` unless
`SOURCECOOP_PRODUCTION=1`. `verify-published` with `AWS_NO_SIGN_REQUEST=YES`
reads the forms back anonymously. Layout and promotion:
[docs/ghrsst-source-coop.md](docs/ghrsst-source-coop.md).

### Reading the outputs

```python
import icechunk, xarray as xr, zarr
zarr.config.set({"async.concurrency": 4})   # THREDDS resets connections at the default of 10
st = icechunk.local_filesystem_storage("work/bran2023-daily-temp/out/icechunk")
repo = icechunk.Repository.open(st, authorize_virtual_chunk_access={
    "https://thredds.nci.org.au/": icechunk.credentials.HttpAccess})
ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
```

```sh
gdal mdim info /vsis3/aadc-transfer/michae_sum/e2e/bran2023-daily-temp/mdim.vrt
gdal mdim info 'ZARR:"/vsikerchunk_parquet_ref/{work/bran2023-daily-temp/out/kerchunk}"'
```

The STAC catalog, in R (rstac, gdalcubes) and from GDAL:

```r
coll  <- jsonlite::fromJSON("work/ghrsst-mur-cog-analysed_sst-2024/out/stac/collection.json")
coll$assets$icechunk$`rv:virtual_chunk_containers`   # prefixes to authorize
feats <- lapply(readLines(".../out/stac/items.ndjson"), jsonlite::fromJSON, simplifyVector = FALSE)
ic <- gdalcubes::stac_image_collection(feats, asset_names = "data", url_fun = identity)
```

```sh
gdal raster info GTI:work/ghrsst-mur-cog-analysed_sst-2024/out/stac/items.parquet   # 2D mosaic
ogrinfo -so work/ghrsst-mur-cog-analysed_sst-2024/out/stac/items.parquet items      # items as a vector layer
```

`url_fun = identity` because gdalcubes prefixes `/vsicurl/` to every href
by default, which breaks local paths. rstac `read_items()` on a local static
catalog resolves item links to `:///path` and fails; over https it is
unaffected.

Known limits for readers: TIFF `PREDICTOR=2` (horizontal differencing,
restarted on every row) is written as the `imagecodecs_delta` filter, as
tifffile writes it; numcodecs `delta` runs over the flattened chunk and
decodes the first value of every row wrongly. Readers of the kerchunk and
Icechunk forms then need imagecodecs (`imagecodecs.numcodecs.register_codecs()`
or `imagecodecs.zarr.register_codecs()`), and GDAL's Zarr driver reads
neither form; the VRT form reads the TIFFs directly and is unaffected.
GDAL's Zarr v3 reader has no `numcodecs.shuffle`,
so GDAL does not read shuffled arrays from the Icechunk store (kerchunk is
Zarr v2 and is read). xarray decodes packed int16 to float64 from the
Icechunk and kerchunk stores, because the JSON attributes do not keep the
float32 type of `scale_factor`. Results and findings are in
[docs/results.md](docs/results.md).

## Files

- `run.sh`: driver. `config/*.sh`: datasets (sources, arrays, remap rules,
  render targets) and publish targets.
- `py/harvest.py`: harvest engines (GDAL `GetRawBlockInfo`, h5py
  `chunk_iter`, and the TIFF tile index for GeoTIFF sources).
  `py/plan_cog.py`: the plan for a daily GeoTIFF series, in the
  hypertidy/vrtstack form (`gdal mdim mosaic` does not take GeoTIFF). `py/probe_harvest.py`: request and byte counts for one
  source. `R/stac.R`: the STAC render. `py/render_icechunk.py`, `py/verify.py`: Icechunk render and
  verification. `py/make_bran_synth.py`: BRAN-shaped synthetic files with
  unwritten chunks.
- `R/mdimrefs.R`: the mdim-refs/0.2 reference implementation, copied with a
  JSON precision fix. `R/mdimrefs_pipeline.R`: directory ingest, flat store,
  VRT renderer and the kerchunk writer from blocklist (vendored with the
  same fix). `R/collate.R`, `R/render.R`: steps 3 and 4.
  `R/install-deps.R`: the `deps` step.
- `legacy/`: the earlier two-table OISST store (`store.R`, `oisst_harvest.R`,
  `oisst_to_icechunk.py`). The release artifact `oisst-refs.sqlite` and
  [with-oisst-gdal.md](with-oisst-gdal.md) use that layout.

## Current state

- **BRAN2023 daily** over NCI THREDDS: `temp` 2010 (1,116,900 refs;
  collate 12 s, render 16 s, Icechunk 5 s) verified locally and published to
  the AADC transfer bucket; `salt` January and February 2010 published and
  verified from the bucket.
- **GHRSST MUR COGs** (source.coop): the TIFF path verified end to end on
  synthetic COGs of the same encoding (Int16, ZSTD, `PREDICTOR=2`, a sparse
  tile, a missing day); not yet run against the bucket.
- **OISST** (NOAA v2.1 AVHRR daily, 1981-09-01 to present): fully harvested
  in the legacy layout, 16,387 files, published as `oisst-refs.sqlite`. One
  month runs through the current pipeline as a test.

## Roadmap

- Ingest the legacy OISST store into mdim-refs/0.2, or reharvest.
- Feed the store from local file mirrors (the raad collection on openstack):
  the schema is dataset-agnostic.
- GHRSST COGs (source.coop): the full `analysed_sst` series (about 22.8M
  refs) as the Icechunk scale test, then the other variables. An async-tiff
  harvest engine would read the tile indexes faster than GDAL.
- Further BRAN variables and years. Beyond a few years of BRAN, materialise `refs_<array>` (the
  view has no index) and batch the mosaic.
- Record attribute types in the store, so readers keep float32 packing.
- Production publishing to the public endpoints (Pawsey, source.coop).
- Longer term this store is a prototype of the reference-extraction model
  proposed for GDAL itself (`gdal mdim` chunk-reference extraction, built on
  `GDALMDArray::GetRawBlockInfo`): the same table, produced by one code path
  for every driver, consumable as a virtual multidim store.

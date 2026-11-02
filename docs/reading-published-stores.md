---
title: "Reading published stores"
---

Draft workflow illustration over one dataset, `bluelink-daily-salt` in the
source.coop scratch product, read two ways with the same selections (a
point, a depth profile, a 30-day series):

| Form | Reader | Script |
|---|---|---|
| Icechunk | icechunk + xarray | [`examples/read_bluelink_icechunk.py`](https://github.com/mdsumner/raad.virtualize/blob/main/examples/read_bluelink_icechunk.py) |
| GDAL mdim VRT | gdalxarray + xarray (GDAL multidim API) | [`examples/read_bluelink_mdimvrt.py`](https://github.com/mdsumner/raad.virtualize/blob/main/examples/read_bluelink_mdimvrt.py) |

Both forms point at the same BRAN netCDF files on
`https://thredds.nci.org.au/`; only the index differs.

## Icechunk

The store:

```
s3://us-west-2.opendata.source.coop/ausantarctic/ausantarctic-scratch/virtual/bluelink-daily-salt/icechunk/
```

Repository metadata, manifests and coordinates are read anonymously from
source.coop. Data chunks are virtual: each one is an HTTP range request
into the BRAN netCDF files on `https://thredds.nci.org.au/`.

### Steps

1. `icechunk.s3_storage(bucket=..., prefix=..., region="us-west-2", anonymous=True)`.
2. `icechunk.Repository.fetch_config(storage)` returns the stored
   configuration, including `virtual_chunk_containers`. For this store
   the only container is `https://thredds.nci.org.au/`.
3. Authorize each container: `icechunk.credentials.HttpAccess` for http(s)
   prefixes, `icechunk.s3_anonymous_credentials()` for public `s3://`
   prefixes. An unauthorized prefix fails at the first chunk read.
4. Cap concurrency: `config.max_concurrent_requests` (a top-level
   attribute of `RepositoryConfig` in icechunk 2.x) and
   `zarr.config.set({"async.concurrency": 4})`. The zarr setting bounds how
   many chunks of one selection are requested at once; THREDDS resets
   connections at the default of 10.
5. `xarray.open_zarr(session.store, consolidated=False, chunks=None)`, then
   `.sel()` / `.isel()`, then `.load()` or `.values` on the selection only.

### Request counts

`salt` is chunked `(Time=1, st_ocean=1, yt_ocean=300, xt_ocean=300)`:

| Selection | Chunks requested |
|---|---|
| one value | 1 |
| depth profile, one day | 51 |
| N days at one point and depth | N |
| one latitude line (no `yt_ocean` selection), one day and depth | 5 |

A long point time series is one request per day on this layout.

### Dask

With `chunks={}` and the dask array-expression backend
(`array.query-planning = True`), `.values` on a selection has returned an
object array of dask arrays. `chunks=None` avoids dask. When dask is
wanted, open with chunks matching the store and compute under
`dask.config.set(scheduler="threads", num_workers=4)`.

## GDAL mdim VRT

```
/vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/virtual/bluelink-daily-salt/mdim.vrt
```

The VRT is about 140 KB with 403 sources, one per monthly netCDF file, each
a `/vsicurl/` URL on THREDDS with a `SourceSlab count`, so opening it reads
no source file.

```python
ds = xr.open_dataset(url, engine="gdalxarray", chunks=None,
                     config_options={"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
                                     "GDAL_HTTP_MAX_RETRY": "3",
                                     "GDAL_HTTP_RETRY_DELAY": "2"})
```

`config_options` (gdalxarray 0.5.1) applies the options around the open and
every later read. A read call goes through its sources one after another,
so one process sends one request at a time; parallel reads need separate
processes, each opening the VRT. A read touching a source opens that
netCDF file over HTTP before reading its chunks, so the first read in each
month costs more than later reads in the same file.

The same coordinate names apply (`Time`, `st_ocean`, `yt_ocean`,
`xt_ocean`), and `.sel()` / `.isel()` then `.load()` reads only the
selection.

GDAL's own Icechunk reader (`/vsiicechunk/{...}`) opens the store but skips
`salt` and `temp` with `Unsupported codec: numcodecs.shuffle`: the BRAN
chunks are HDF5 shuffle + zlib, and GDAL's Zarr v3 codec list has no
`numcodecs.shuffle` (GDAL master, 2026-11-01; its shuffle filter exists
for Zarr v2 only). GDAL readers of these bytes use the mdim VRT or the
kerchunk Parquet form (Zarr v2). GDAL recognises the kerchunk directory
from a plain `ZARR:` path:

```python
ds = xr.open_dataset(
    'ZARR:"/vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/'
    'virtual/bluelink-daily-temp/kerchunk/"', engine="gdalxarray")
```

The explicit form
`ZARR:"/vsikerchunk_parquet_ref/{/vsicurl/https://.../kerchunk}"` is
equivalent.

### One index, three readers

`temp.isel(Time=-1, xt_ocean=1200, yt_ocean=slice(300, 350), st_ocean=5)`
on `bluelink-daily-temp` (2026-11-02) returned the same 50 values through
gdalxarray on the mdim VRT and through gdalxarray on the kerchunk store
(GDAL Zarr driver). The Icechunk store holds the same references; GDAL
does not read it (shuffle codec, above), zarr-python does.

## Other bluelink datasets

The other `bluelink-daily-*` datasets sit beside this one with the same
layout. `u` and `v` use `xu_ocean` / `yu_ocean`; 2D variables such as
`eta_t` have no `st_ocean`.

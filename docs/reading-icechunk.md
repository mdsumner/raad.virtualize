---
title: Reading a published Icechunk store
---

# Reading a published Icechunk store

Draft workflow illustration. Script:
[`examples/read_bluelink_icechunk.py`](https://github.com/mdsumner/raad.virtualize/blob/main/examples/read_bluelink_icechunk.py).

The store is `bluelink-daily-salt` in the source.coop scratch product:

```
s3://us-west-2.opendata.source.coop/ausantarctic/ausantarctic-scratch/virtual/bluelink-daily-salt/icechunk/
```

Repository metadata, manifests and coordinates are read anonymously from
source.coop. Data chunks are virtual: each one is an HTTP range request
into the BRAN netCDF files on `https://thredds.nci.org.au/`.

## Steps

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

## Request counts

`salt` is chunked `(Time=1, st_ocean=1, yt_ocean=300, xt_ocean=300)`:

| Selection | Chunks requested |
|---|---|
| one value | 1 |
| depth profile, one day | 51 |
| N days at one point and depth | N |
| one latitude line (no `yt_ocean` selection), one day and depth | 5 |

A long point time series is one request per day on this layout.

## Dask

With `chunks={}` and the dask array-expression backend
(`array.query-planning = True`), `.values` on a selection has returned an
object array of dask arrays. `chunks=None` avoids dask. When dask is
wanted, open with chunks matching the store and compute under
`dask.config.set(scheduler="threads", num_workers=4)`.

## Other bluelink datasets

The other `bluelink-daily-*` stores sit beside this one with the same
layout. `u` and `v` use `xu_ocean` / `yu_ocean`; 2D variables such as
`eta_t` have no `st_ocean`.

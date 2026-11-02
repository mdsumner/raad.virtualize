"""
Read the bluelink-daily-salt virtual Icechunk store on source.coop.

Draft workflow illustration: one published store, read from Python with
icechunk + xarray, with request concurrency capped. See
docs/reading-published-stores.md.

The repository lives in the public source.coop bucket (anonymous S3 read).
Its chunks are *virtual*: byte ranges inside the original BRAN netCDF files
on the NCI THREDDS server (https://thredds.nci.org.au/). Metadata and
coordinates come from source.coop; every data chunk is an HTTP range GET
against THREDDS. THREDDS resets connections at ~10 concurrent requests and
accepts 4.

Chunking of salt is (Time=1, st_ocean=1, yt_ocean=300, xt_ocean=300), so
  - one point            = 1 chunk
  - one depth profile    = 51 chunks (one per st_ocean level)
  - an N-day time series = N chunks (one per day)
Select first, then read. ds.load() or ds.compute() on the whole dataset
fetches all of it (salt is ~27 TB decoded).

Requires: icechunk >= 2, zarr >= 3, xarray. Dask is optional (see bottom).
Open, config and coordinates checked with icechunk 2.3.1, zarr 3.4.2,
xarray 2026.9.0; data reads need network access to thredds.nci.org.au.
"""

import time

import icechunk as ic
import xarray as xr
import zarr

BUCKET = "us-west-2.opendata.source.coop"
# Other bluelink-daily-* datasets sit beside this one; u and v use
# xu_ocean/yu_ocean, and 2D variables have no st_ocean.
PREFIX = "ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-salt/icechunk"
VARIABLE = "salt"
CONCURRENCY = 4  # simultaneous requests to THREDDS; keep this small

# -- 1. storage: anonymous read of the public source.coop bucket -------------
storage = ic.s3_storage(
    bucket=BUCKET,
    prefix=PREFIX,
    region="us-west-2",
    anonymous=True,
)

# -- 2. config: start from the config stored in the repo, then throttle ------
# fetch_config() returns the repo's own config, including its
# virtual_chunk_containers (here just "https://thredds.nci.org.au/").
config = ic.Repository.fetch_config(storage)
config.max_concurrent_requests = CONCURRENCY  # top-level attribute, no .runtime

# -- 3. authorise every virtual chunk container the repo declares ------------
# Icechunk refuses to fetch virtual chunks from a prefix you have not
# authorised. Build the map from the repo itself rather than hard-coding it.
def credentials_for(prefix):
    if prefix.startswith("s3://"):
        return ic.s3_anonymous_credentials()
    if prefix.startswith(("http://", "https://")):
        return ic.credentials.HttpAccess  # sentinel, no actual credentials
    raise ValueError(f"no credential rule for virtual chunk prefix {prefix!r}")

authorize = {c.url_prefix: credentials_for(c.url_prefix)
             for c in config.virtual_chunk_containers.values()}
print("virtual chunk containers:", list(authorize))

repo = ic.Repository.open(
    storage,
    config=config,
    authorize_virtual_chunk_access=authorize,
)
session = repo.readonly_session("main")

# -- 4. open WITHOUT dask -----------------------------------------------------
# chunks=None gives lazily indexed numpy-backed arrays: .sel/.isel stay lazy
# and only the selected chunks are fetched when you ask for .values. This
# also sidesteps the object-array result seen with chunks={} under the new
# dask array-expression backend.
ds = xr.open_zarr(session.store, consolidated=False, chunks=None)
print(ds)

# zarr's own async concurrency is what decides how many chunks of one
# selection are requested at once (default 10). Cap it for every read below.
zarr.config.set({"async.concurrency": CONCURRENCY})

salt = ds[VARIABLE]
LON, LAT, DEPTH = 147.0, -44.0, 5.0  # south of Tasmania, near-surface


def timed(label, da):
    t0 = time.perf_counter()
    out = da.load()  # reads only what `da` covers
    print(f"\n{label}: shape {out.shape}, {time.perf_counter() - t0:.1f} s")
    return out


# -- 5a. a single value: last day, nearest point and depth -------------------
point = salt.sel(xt_ocean=LON, yt_ocean=LAT, st_ocean=DEPTH,
                 method="nearest").isel(Time=-1)
point = timed("point", point)
print(point.Time.values, float(point.xt_ocean), float(point.yt_ocean),
      float(point.st_ocean), "salt =", float(point))

# -- 5b. a depth profile at that point on the last day (51 chunks) -----------
profile = salt.sel(xt_ocean=LON, yt_ocean=LAT, method="nearest").isel(Time=-1)
profile = timed("profile", profile)
print(profile.to_series().dropna().round(3).to_string())

# -- 5c. a short time series at that point and depth (30 chunks) -------------
series = salt.sel(xt_ocean=LON, yt_ocean=LAT, st_ocean=DEPTH,
                  method="nearest").isel(Time=slice(-30, None))
series = timed("last 30 days", series)
print(series.to_series().round(3).to_string())

# A selection without yt_ocean is a full latitude line on the last
# day: 1500 values from 5 chunks.
#   line = salt.sel(xt_ocean=147, st_ocean=5, method="nearest").isel(Time=-1)
#   line.values

# -- 6. if you do want dask (bigger jobs, parallel compute) ------------------
# Open with explicit chunks matching the store, select, then compute under a
# small thread pool so dask does not launch one request per core:
#
#   import dask
#   dsd = xr.open_zarr(session.store, consolidated=False,
#                      chunks={"Time": 1, "st_ocean": 1,
#                              "yt_ocean": 300, "xt_ocean": 300})
#   sub = dsd[VARIABLE].sel(xt_ocean=LON, yt_ocean=LAT, method="nearest")
#   sub = sub.isel(Time=slice(-30, None))
#   with dask.config.set(scheduler="threads", num_workers=CONCURRENCY):
#       arr = sub.compute()
#
# If .values still comes back as an array of dask objects (dtype=object),
# that is the dask array-expression backend; set
# DASK_ARRAY__QUERY_PLANNING=False before importing dask, or stay with
# chunks=None as above.

"""
Read the bluelink-daily-salt GDAL multidimensional VRT on source.coop with
xarray through the gdalxarray backend.

Draft workflow illustration, the GDAL counterpart of
examples/read_bluelink_icechunk.py. See docs/reading-published-stores.md.

mdim.vrt is a small XML file (~140 KB, 403 sources, one per monthly BRAN
netCDF file). Each source is a /vsicurl/ URL into the NCI THREDDS server,
so the VRT comes from source.coop and every data read is GDAL opening the
netCDF (HDF5) file on THREDDS and reading the chunks it needs. Every source
carries a SourceSlab count, so opening the VRT touches no source file.

GDAL reads one source after another within a single read call, so a
single Python process sends one request at a time. Parallel reads come
from separate processes, each opening the VRT itself.

Selections and requests:
  - one point            = one source file (file open + 1 chunk)
  - one depth profile    = one source file, 51 chunks
  - an N-day time series = the monthly files the days fall in, N chunks

Requires: GDAL with Python bindings (osgeo), gdalxarray >= 0.5.1 (for
config_options), xarray.
"""

import time

import xarray as xr

URL = ("/vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/"
       "bluelink/bluelink-daily-salt/mdim.vrt")
VARIABLE = "salt"

# Applied around the open and every later read (gdalxarray config_options).
GDAL_CONFIG = {
    # no directory listing of THREDDS or source.coop on open
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    # retry transient THREDDS errors with a delay
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
}

# chunks=None: lazy, numpy-backed, no dask; only the selection is read.
ds = xr.open_dataset(URL, engine="gdalxarray", chunks=None,
                     config_options=GDAL_CONFIG)
print(ds)

salt = ds[VARIABLE]
LON, LAT, DEPTH = 147.0, -44.0, 5.0  # south of Tasmania, near-surface


def timed(label, da):
    t0 = time.perf_counter()
    out = da.load()  # reads only what `da` covers
    print(f"\n{label}: shape {out.shape}, {time.perf_counter() - t0:.1f} s")
    return out


# -- a single value: last day, nearest point and depth -----------------------
point = salt.sel(xt_ocean=LON, yt_ocean=LAT, st_ocean=DEPTH,
                 method="nearest").isel(Time=-1)
point = timed("point", point)
print(point.Time.values, float(point.xt_ocean), float(point.yt_ocean),
      float(point.st_ocean), "salt =", float(point))

# -- a depth profile at that point on the last day ---------------------------
profile = salt.sel(xt_ocean=LON, yt_ocean=LAT, method="nearest").isel(Time=-1)
profile = timed("profile", profile)
print(profile.to_series().dropna().round(3).to_string())

# -- a short time series at that point and depth -----------------------------
series = salt.sel(xt_ocean=LON, yt_ocean=LAT, st_ocean=DEPTH,
                  method="nearest").isel(Time=slice(-30, None))
series = timed("last 30 days", series)
print(series.to_series().round(3).to_string())

# The same VRT from the GDAL API directly:
#
#   from osgeo import gdal
#   gdal.UseExceptions()
#   g = gdal.OpenEx(URL, gdal.OF_MULTIDIM_RASTER).GetRootGroup()
#   a = g.OpenMDArray(VARIABLE)
#   # last day, surface, global field (60 chunks)
#   v = a.ReadAsArray(array_start_idx=[a.GetDimensions()[0].GetSize() - 1,
#                                      0, 0, 0],
#                     count=[1, 1, 1500, 3600])
#
# and from the command line:
#
#   gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-salt/mdim.vrt

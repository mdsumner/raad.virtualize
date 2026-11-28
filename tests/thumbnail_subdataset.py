"""thumbnail.read_classic refuses a subdataset the driver chose itself, and
CF packing is read from the attributes where the driver gives no scale and
offset. A netCDF-4 file with a packed 4D field and a 2D Time_bnds (the BRAN
layout), opened with the HDF5 driver (as thumbnail.py does over /vsi in
docker), opens as Time_bnds alone; the field is drawn through the
multidimensional API, with its scale_factor and add_offset. A 2D field
placed as "lift:z" (py/plan_lift.py, the ASI layout) is read as the
source's z.
Run from the repository root, with GDAL's netCDF and HDF5 drivers:
  python tests/thumbnail_subdataset.py
"""
import os
import sys
import tempfile

import numpy as np
from osgeo import gdal

sys.path.insert(0, "py")
from thumbnail import own_subdataset, read_classic, read_mdim  # noqa: E402

gdal.UseExceptions()

# descriptions
assert own_subdataset("/d/f.nc", "/d/f.nc", "temp")
assert own_subdataset("/d/f.tif", "/d/f.tif", "1")
assert own_subdataset('HDF5:"/d/f.nc"://temp', "/d/f.nc", "temp")
assert own_subdataset('NETCDF:"/d/f.nc":temp', "/d/f.nc", "/temp")
assert not own_subdataset('HDF5:"/d/f.nc"://Time_bnds', "/d/f.nc", "temp")
assert not own_subdataset('HDF5:"/d/f.nc"://xtemp', "/d/f.nc", "temp")

# a BRAN-shaped file: temp(Time, st_ocean, yt_ocean, xt_ocean), Time_bnds(Time, nv)
field = np.arange(3 * 2 * 4 * 5, dtype="int16").reshape(3, 2, 4, 5)


def make(path):
    """Written in a function so every handle is released and the file closed
    before the HDF5 driver reads it."""
    ds = gdal.GetDriverByName("netCDF").CreateMultiDimensional(path, [], ["FORMAT=NC4"])
    rg = ds.GetRootGroup()
    f64 = gdal.ExtendedDataType.Create(gdal.GDT_Float64)
    i16 = gdal.ExtendedDataType.Create(gdal.GDT_Int16)
    dims = {n: rg.CreateDimension(n, None, None, k) for n, k in
            [("Time", 3), ("nv", 2), ("st_ocean", 2), ("yt_ocean", 4), ("xt_ocean", 5)]}
    for n in ("Time", "st_ocean", "yt_ocean", "xt_ocean"):
        rg.CreateMDArray(n, [dims[n]], f64).WriteArray(
            np.arange(dims[n].GetSize(), dtype="float64") + (17350 if n == "Time" else 0))
    rg.CreateMDArray("Time_bnds", [dims["Time"], dims["nv"]], f64).WriteArray(
        np.array([[17349.5, 17350.5], [17350.5, 17351.5], [17351.5, 17352.5]]))
    temp = rg.CreateMDArray("temp", [dims[n] for n in ("Time", "st_ocean", "yt_ocean", "xt_ocean")], i16)
    temp.SetScale(0.5)
    temp.SetOffset(10.0)
    temp.WriteArray(field)


def make_lift(path):
    """An ASI-shaped file: z(y, x) float32, one 2D field, no time axis."""
    ds = gdal.GetDriverByName("netCDF").CreateMultiDimensional(path, [], ["FORMAT=NC4"])
    rg = ds.GetRootGroup()
    f64 = gdal.ExtendedDataType.Create(gdal.GDT_Float64)
    dims = {n: rg.CreateDimension(n, None, None, k) for n, k in [("y", 4), ("x", 5)]}
    for n in ("y", "x"):
        rg.CreateMDArray(n, [dims[n]], f64).WriteArray(np.arange(dims[n].GetSize(), dtype="float64"))
    rg.CreateMDArray("z", [dims["y"], dims["x"]], gdal.ExtendedDataType.Create(gdal.GDT_Float32)).WriteArray(lifted)


lifted = np.arange(4 * 5, dtype="float32").reshape(4, 5)
path = os.path.join(tempfile.mkdtemp(), "ocean_temp.nc")
make(path)
lift_path = os.path.join(os.path.dirname(path), "asi.nc")
make_lift(lift_path)

gdal.GetDriverByName("netCDF").Deregister()
opened = gdal.OpenEx(path, gdal.OF_RASTER)
assert opened.GetDescription().endswith("Time_bnds"), opened.GetDescription()  # the layout under test
del opened

assert read_classic(path, "temp", 512) is None
v, _, scale, offset = read_mdim(path, "temp", [2, 1, 0, 0], 512)[:4]
assert v.shape == (4, 5), v.shape
assert np.array_equal(v, field[2, 1]), v
assert (scale, offset) == (0.5, 10.0), (scale, offset)

# the lifted placement: three offsets (the new axis first), the source's z
assert read_classic(lift_path, "lift:z", 512) is None  # HDF5 lists x, y, z as subdatasets
v = read_mdim(lift_path, "lift:z", [0, 0, 0], 512)[0]
assert np.array_equal(v, lifted), v
print("thumbnail_subdataset: ok")

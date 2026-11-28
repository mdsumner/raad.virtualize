"""py/plan_cog.py writes the x and y coordinates of the full-resolution grid
and of each overview level as the doubles they are computed as. Two
monthly COGs on a 1/24 degree grid (the ESA CCI cell, origin -180, 90) with
overviews x2 and x4: every RegularlySpacedValues of the plan reads back as
the cell centre and size from the geotransform, and the corner restated from
them is the origin to the last bit of a double.
Run from the repository root, with GDAL:
  python tests/plan_cog_precision.py
"""
import os
import re
import sys
import tempfile

import numpy as np
from osgeo import gdal

sys.path.insert(0, "py")
from plan_cog import plan  # noqa: E402

gdal.UseExceptions()
D = 1 / 24
NX, NY = 96, 48
with tempfile.TemporaryDirectory() as tmp:
    srcs = []
    for ym in ("202501", "202502"):
        mem = gdal.GetDriverByName("MEM").Create("", NX, NY, 1, gdal.GDT_Float32)
        mem.SetGeoTransform([-180.0, D, 0.0, 90.0, 0.0, -D])
        mem.SetProjection("EPSG:4326")
        mem.GetRasterBand(1).WriteArray(np.arange(NX * NY, dtype="f4").reshape(NY, NX))
        mem.BuildOverviews("AVERAGE", [2, 4])
        p = os.path.join(tmp, f"oc-{ym}-chl.tif")
        gdal.GetDriverByName("COG").CreateCopy(p, mem, options=["BLOCKSIZE=128", "OVERVIEWS=FORCE_USE_EXISTING"])
        srcs.append(p)
    text, nfiles, nt, missing, nlev = plan(srcs, "chl", r"-([0-9]{6})-", "month", overviews=True)
assert (nfiles, nt, missing, nlev) == (2, 2, [], 2), (nfiles, nt, missing, nlev)

REG = (r'<Array name="([xy](?:_x\d+)?)">\s*<DataType>Float64</DataType>\s*<DimensionRef ref="[^"]+"/>\s*'
       r'<RegularlySpacedValues start="([^"]+)" increment="([^"]+)"/>')
got = {n: (float(s), float(i)) for n, s, i in re.findall(REG, text)}
assert sorted(got) == ["x", "x_x2", "x_x4", "y", "y_x2", "y_x4"], sorted(got)
for f in (1, 2, 4):
    sfx = "" if f == 1 else f"_x{f}"
    for axis, origin, cell in (("x", -180.0, D * NX / (NX // f)), ("y", 90.0, -D * NY / (NY // f))):
        start, inc = got[axis + sfx]
        # the same doubles plan_cog computes: corner + cell / 2, and the cell
        assert inc == cell, (axis + sfx, inc, cell)
        assert start == origin + cell / 2, (axis + sfx, start, origin + cell / 2)
        assert start - inc / 2 == origin, (axis + sfx, start - inc / 2, origin)
# 10 significant digits, the format before 2026-11-28, lose the cell
assert float(f"{D:.10g}") != D and float(f"{D:.17g}") == D
print("plan_cog_precision: ok")

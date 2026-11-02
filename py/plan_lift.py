"""plan_lift.py -- mdim VRT plan for a daily series of 2D arrays, one file a day.

For netCDF4/HDF5 collections whose files hold one day each with no time
dimension (University of Bremen AMSR2 ASI: z(y, x), GMT style), which
`gdal mdim mosaic` cannot stack. Writes the form plan_cog.py writes for
GeoTIFFs, with the source read as a multidimensional array:

  <Source>
    <SourceFilename>FILE</SourceFilename>
    <SourceArray>z</SourceArray>
    <SourceTranspose>-1,0,1</SourceTranspose>     a new leading axis of size 1
    <SourceSlab offset="0,0,0" count="1,ny,nx" step="1,1,1"/>
    <DestSlab offset="t,0,0"/>
  </Source>

The time index of a file is its date minus the first date, so a missing day
is a hole in the array rather than a shift of every later day; time is
"days since 1970-01-01" (date at 00:00), regularly spaced. The y and x
coordinates are read from the first file (RegularlySpacedValues when evenly
spaced, InlineValues otherwise), in the file's order. The SRS is the file's,
or --srs (any string OSR takes: a PROJ string, EPSG code, WKT) when the file
has none or --srs-override is given. BlockSize is 1 by the file's chunking.

Only the first file is opened to build the plan; --check N opens N files
spread over the series (plus the first and last) and fails if a file's array
shape, type or chunking differs. harvest.py pads the chunk coordinates of a
source placed this way with a leading 0 (the new axis).

Usage:
  python plan_lift.py --sources sources.txt --array z \
    --pattern '-(\\d{8})-v[0-9.]+\\.nc$' [--srs '+proj=stere ...'] plan.vrt
  [--check 8] [--max-missing N]
"""
import argparse
import datetime as dt
import os
import random
import re
import sys
from xml.sax.saxutils import escape

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
EPOCH = dt.date(1970, 1, 1)
VRT_TYPE = {gdal.GDT_Byte: "Byte", gdal.GDT_Int8: "Int8", gdal.GDT_Int16: "Int16",
            gdal.GDT_UInt16: "UInt16", gdal.GDT_Int32: "Int32",
            gdal.GDT_UInt32: "UInt32", gdal.GDT_Float32: "Float32",
            gdal.GDT_Float64: "Float64"}


def dated(sources, pattern):
    rx = re.compile(pattern)
    out = []
    for s in sources:
        m = rx.search(os.path.basename(s))
        if not m:
            sys.exit(f"plan_lift: no date in {s} (pattern {pattern})")
        out.append((dt.datetime.strptime(m.group(1), "%Y%m%d").date(), s))
    out.sort()
    days = [d for d, _ in out]
    if len(set(days)) != len(days):
        sys.exit("plan_lift: more than one file for a date")
    return out


def open_array(path, name):
    ds = gdal.OpenEx(path, gdal.OF_MULTIDIM_RASTER)
    return ds, ds.GetRootGroup().OpenMDArray(name)


def signature(arr):
    dims = arr.GetDimensions()
    return ([d.GetName() for d in dims], [d.GetSize() for d in dims],
            arr.GetDataType().GetNumericDataType(), list(arr.GetBlockSize()))


def coord(dim):
    """(start, increment) when evenly spaced, else the values."""
    iv = dim.GetIndexingVariable()
    if iv is None:
        sys.exit(f"plan_lift: dimension {dim.GetName()} has no indexing variable")
    v = np.asarray(iv.ReadAsArray(), dtype="f8").ravel()
    if v.size > 1:
        step = np.diff(v)
        if np.allclose(step, step[0], rtol=0, atol=abs(step[0]) * 1e-9):
            return (float(v[0]), float(step[0])), v
    return None, v


def _g(x):
    return f"{x:.17g}"


def plan(files, array, srs_text=None, srs_override=False):
    ds, arr = open_array(files[0][1], array)
    if arr.GetDimensionCount() != 2:
        sys.exit(f"plan_lift: {array} has {arr.GetDimensionCount()} dimensions, not 2 "
                 f"(a file with a time axis is py/plan_daily.py's case)")
    dims = arr.GetDimensions()
    (ydim, xdim), (ny, nx) = dims, [d.GetSize() for d in dims]
    by, bx = [b if b > 0 else s for b, s in zip(arr.GetBlockSize(), (ny, nx))]
    srs = arr.GetSpatialRef()
    if srs_text and (srs is None or srs_override):
        srs = osr.SpatialReference()
        srs.SetFromUserInput(srs_text)
    if srs is None:
        print("plan_lift: no SRS in the file and no --srs; the plan has none", file=sys.stderr)
    t0 = files[0][0]
    nt = (files[-1][0] - t0).days + 1
    yn, xn = ydim.GetName(), xdim.GetName()
    lines = [
        "<VRTDataset>",
        '  <Group name="/">',
        f'    <Dimension name="time" size="{nt}" type="TEMPORAL" indexingVariable="time"/>',
        f'    <Dimension name="{yn}" size="{ny}" type="HORIZONTAL_Y" indexingVariable="{yn}"/>',
        f'    <Dimension name="{xn}" size="{nx}" type="HORIZONTAL_X" indexingVariable="{xn}"/>',
        '    <Array name="time">',
        "      <DataType>Float64</DataType>",
        '      <DimensionRef ref="time"/>',
        f'      <RegularlySpacedValues start="{(t0 - EPOCH).days}" increment="1"/>',
        "      <Unit>days since 1970-01-01</Unit>",
        '      <Attribute name="calendar"><DataType>String</DataType><Value>standard</Value></Attribute>',
        "    </Array>",
    ]
    for d in (ydim, xdim):
        reg, v = coord(d)
        iv = d.GetIndexingVariable()
        lines += [f'    <Array name="{d.GetName()}">', "      <DataType>Float64</DataType>",
                  f'      <DimensionRef ref="{d.GetName()}"/>']
        if reg:
            lines.append(f'      <RegularlySpacedValues start="{_g(reg[0])}" increment="{_g(reg[1])}"/>')
        else:
            lines.append(f'      <InlineValues offset="0" count="{v.size}">'
                         + " ".join(_g(x) for x in v) + "</InlineValues>")
        if iv.GetUnit():
            lines.append(f"      <Unit>{escape(iv.GetUnit())}</Unit>")
        lines.append("    </Array>")
    lines += [
        f'    <Array name="{array}">',
        f"      <DataType>{VRT_TYPE[arr.GetDataType().GetNumericDataType()]}</DataType>",
        '      <DimensionRef ref="time"/>',
        f'      <DimensionRef ref="{yn}"/>',
        f'      <DimensionRef ref="{xn}"/>',
        f"      <BlockSize>1,{by},{bx}</BlockSize>",
    ]
    if srs is not None:
        # axes of the array: time, y, x -> SRS axis 1 (easting) is array axis 3
        lines.append(f'      <SRS dataAxisToSRSAxisMapping="3,2">{escape(srs.ExportToWkt())}</SRS>')
    if arr.GetUnit():
        lines.append(f"      <Unit>{escape(arr.GetUnit())}</Unit>")
    nd = arr.GetNoDataValue()
    if nd is not None:
        lines.append(f"      <NoDataValue>{'NaN' if np.isnan(nd) else _g(nd)}</NoDataValue>")
    if arr.GetOffset():
        lines.append(f"      <Offset>{_g(arr.GetOffset())}</Offset>")
    if arr.GetScale() not in (None, 1):
        lines.append(f"      <Scale>{_g(arr.GetScale())}</Scale>")
    for d, s in files:
        lines += [
            "      <Source>",
            f"        <SourceFilename>{escape(s)}</SourceFilename>",
            f"        <SourceArray>{escape(arr.GetFullName())}</SourceArray>",
            "        <SourceTranspose>-1,0,1</SourceTranspose>",
            f'        <SourceSlab offset="0,0,0" count="1,{ny},{nx}" step="1,1,1"/>',
            f'        <DestSlab offset="{(d - t0).days},0,0"/>',
            "      </Source>",
        ]
    lines += ["    </Array>", "  </Group>", "</VRTDataset>", ""]
    missing = sorted(set(t0 + dt.timedelta(i) for i in range(nt)) - {d for d, _ in files})
    return "\n".join(lines), nt, missing, signature(arr)


def check(files, idx, array, want):
    bad = 0
    for i in idx:
        d, s = files[i]
        _, arr = open_array(s, array)
        got = signature(arr)
        ok = got == want
        print(f"  check {d} {os.path.basename(s)}: {'ok' if ok else f'{got} expected {want}'}")
        bad += not ok
    if bad:
        sys.exit(f"plan_lift: {bad} of {len(idx)} checked files differ from the first")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True, help="file of sources, one per line")
    ap.add_argument("--array", required=True)
    ap.add_argument("--pattern", required=True, help="regex on the file name; group 1 is YYYYMMDD")
    ap.add_argument("--srs", help="SRS when the file has none (PROJ string, EPSG:n, WKT)")
    ap.add_argument("--srs-override", action="store_true", help="use --srs even when the file has one")
    ap.add_argument("--check", type=int, default=8, help="files to open and check (0 none)")
    ap.add_argument("--max-missing", type=int, default=-1,
                    help="fail when more days than this have no file (-1: no limit)")
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        files = dated([s.strip() for s in f if s.strip()], a.pattern)
    if not files:
        sys.exit("plan_lift: no sources")
    text, nt, missing, sig = plan(files, a.array, a.srs, a.srs_override)
    if missing:
        shown = ", ".join(str(d) for d in missing[:20]) + (" ..." if len(missing) > 20 else "")
        print(f"plan_lift: {len(missing)} of {nt} days have no file: {shown}", file=sys.stderr)
    if 0 <= a.max_missing < len(missing):
        sys.exit(f"plan_lift: {len(missing)} missing days, more than --max-missing {a.max_missing}")
    if a.check:
        n = len(files)
        idx = sorted({0, n - 1} | set(random.Random(1).sample(range(n), min(a.check, n))))
        check(files, idx, a.array, sig)
    with open(a.vrt, "w") as f:
        f.write(text)
    print(f"plan_lift: {len(files)} files over {nt} days ({len(missing)} missing) -> {a.vrt}")


if __name__ == "__main__":
    main()

"""plan_cog.py -- multidim VRT plan for a daily series of single-band GeoTIFFs.

The plan step for GeoTIFF and COG collections, which `gdal mdim mosaic`
does not accept. Writes the form hypertidy/vrtstack writes (one <Source> per
file: <SourceBand>1</SourceBand>, <SourceTranspose>-1,0,1</SourceTranspose>,
<DestSlab offset="t,0,0"/>), with three differences: the time index of a file
is its date minus the first date, so a missing day is a hole in the array
rather than a shift of every later day; scale, offset and unit are kept; and
each source states its extent in a <SourceSlab>. Without the count, GDAL
opens every source in order on each read to learn its shape (about 1 s per
/vsicurl/ COG); with it, a read opens only the sources it touches.

Every file is assumed to share the grid, type and tiling of the first one
(only the first is opened). Dates come from the first capture group of
--pattern applied to the file name, as YYYYMMDD.

Usage:
  python plan_cog.py --sources sources.txt --array analysed_sst \
    --pattern '^(\\d{8})090000-.*\\.tif$' plan.vrt
"""
import argparse
import datetime as dt
import os
import re
import sys
from xml.sax.saxutils import escape

from osgeo import gdal

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
            continue
        out.append((dt.datetime.strptime(m.group(1), "%Y%m%d").date(), s))
    out.sort()
    days = [d for d, _ in out]
    if len(set(days)) != len(days):
        sys.exit("plan_cog: more than one file for a date")
    return out


def plan(sources, array, pattern):
    files = dated(sources, pattern)
    if not files:
        sys.exit("plan_cog: no source matches the pattern")
    ds = gdal.Open(files[0][1])
    b = ds.GetRasterBand(1)
    nx, ny = ds.RasterXSize, ds.RasterYSize
    bx, by = b.GetBlockSize()
    x0, dx, _, y0, _, dy = ds.GetGeoTransform()
    t0 = files[0][0]
    nt = (files[-1][0] - t0).days + 1
    srs = ds.GetSpatialRef()
    lines = [
        "<VRTDataset>",
        '  <Group name="/">',
        f'    <Dimension name="time" size="{nt}" type="TEMPORAL" indexingVariable="time"/>',
        f'    <Dimension name="y" size="{ny}" type="HORIZONTAL_Y" indexingVariable="y"/>',
        f'    <Dimension name="x" size="{nx}" type="HORIZONTAL_X" indexingVariable="x"/>',
        '    <Array name="time">',
        "      <DataType>Float64</DataType>",
        '      <DimensionRef ref="time"/>',
        f'      <RegularlySpacedValues start="{(t0 - EPOCH).days}" increment="1"/>',
        "      <Unit>days since 1970-01-01</Unit>",
        "    </Array>",
    ]
    for name, start, inc in (("y", y0 + dy / 2, dy), ("x", x0 + dx / 2, dx)):
        lines += [
            f'    <Array name="{name}">',
            "      <DataType>Float64</DataType>",
            f'      <DimensionRef ref="{name}"/>',
            f'      <RegularlySpacedValues start="{start:.10g}" increment="{inc:.10g}"/>',
            "    </Array>",
        ]
    lines += [
        f'    <Array name="{array}">',
        f"      <DataType>{VRT_TYPE[b.DataType]}</DataType>",
        '      <DimensionRef ref="time"/>',
        '      <DimensionRef ref="y"/>',
        '      <DimensionRef ref="x"/>',
        f"      <BlockSize>1,{by},{bx}</BlockSize>",
    ]
    if srs is not None:
        lines.append(f'      <SRS dataAxisToSRSAxisMapping="2,1">{escape(srs.ExportToWkt())}</SRS>')
    if b.GetUnitType():
        lines.append(f"      <Unit>{escape(b.GetUnitType())}</Unit>")
    if b.GetNoDataValue() is not None:
        lines.append(f"      <NoDataValue>{b.GetNoDataValue():.17g}</NoDataValue>")
    if b.GetOffset():
        lines.append(f"      <Offset>{b.GetOffset():.17g}</Offset>")
    if b.GetScale() not in (None, 1):
        lines.append(f"      <Scale>{b.GetScale():.17g}</Scale>")
    for d, s in files:
        lines += [
            "      <Source>",
            f"        <SourceFilename>{escape(s)}</SourceFilename>",
            "        <SourceBand>1</SourceBand>",
            "        <SourceTranspose>-1,0,1</SourceTranspose>",
            f'        <SourceSlab offset="0,0,0" count="1,{ny},{nx}" step="1,1,1"/>',
            f'        <DestSlab offset="{(d - t0).days},0,0"/>',
            "      </Source>",
        ]
    lines += ["    </Array>", "  </Group>", "</VRTDataset>", ""]
    return "\n".join(lines), len(files), nt


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True, help="file of sources, one per line")
    ap.add_argument("--array", required=True)
    ap.add_argument("--pattern", required=True, help="regex on the file name; group 1 is YYYYMMDD")
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    text, nfiles, nt = plan(sources, a.array, a.pattern)
    with open(a.vrt, "w") as f:
        f.write(text)
    print(f"plan_cog: {nfiles} files over {nt} days -> {a.vrt}")


if __name__ == "__main__":
    main()

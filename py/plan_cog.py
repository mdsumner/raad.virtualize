"""plan_cog.py -- multidim VRT plan for a daily or monthly series of single-band GeoTIFFs.

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
--pattern applied to the file name, as YYYYMMDD (--cadence day, the default)
or YYYYMM (--cadence month).

--cadence month: one time step per calendar month, the time value the first
day of the month in days since 1970-01-01, written as InlineValues (months
are not evenly spaced in days). The time index of a file is its month minus
the first month.

Steps (days or months) between the first and last date with no file are
listed on stderr. --max-missing N stops (exit 1, no plan written) when more
than N steps are missing: a listing that dropped directories (HTTP 503 from
the server, for example) then fails instead of planning a shorter series.
Default -1, no limit.

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


def month_index(d, t0):
    return (d.year - t0.year) * 12 + d.month - t0.month


def step_dates(t0, n, cadence):
    """The first date of each of n steps from t0."""
    if cadence == "day":
        return [t0 + dt.timedelta(i) for i in range(n)]
    return [dt.date(t0.year + (t0.month - 1 + i) // 12, (t0.month - 1 + i) % 12 + 1, 1)
            for i in range(n)]


def dated(sources, pattern, cadence="day"):
    rx = re.compile(pattern)
    fmt = "%Y%m%d" if cadence == "day" else "%Y%m"
    out = []
    for s in sources:
        m = rx.search(os.path.basename(s))
        if not m:
            continue
        out.append((dt.datetime.strptime(m.group(1), fmt).date(), s))
    out.sort()
    days = [d for d, _ in out]
    if len(set(days)) != len(days):
        sys.exit("plan_cog: more than one file for a date")
    return out


def plan(sources, array, pattern, cadence="day"):
    files = dated(sources, pattern, cadence)
    if not files:
        sys.exit("plan_cog: no source matches the pattern")
    ds = gdal.Open(files[0][1])
    b = ds.GetRasterBand(1)
    nx, ny = ds.RasterXSize, ds.RasterYSize
    bx, by = b.GetBlockSize()
    x0, dx, _, y0, _, dy = ds.GetGeoTransform()
    t0 = files[0][0]
    if cadence == "day":
        index = lambda d: (d - t0).days
        tvals = f'      <RegularlySpacedValues start="{(t0 - EPOCH).days}" increment="1"/>'
    else:
        index = lambda d: month_index(d, t0)
    nt = index(files[-1][0]) + 1
    steps = step_dates(t0, nt, cadence)
    if cadence == "month":
        tvals = (f'      <InlineValues offset="0" count="{nt}">'
                 + " ".join(str((d - EPOCH).days) for d in steps) + "</InlineValues>")
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
        tvals,
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
            f'        <DestSlab offset="{index(d)},0,0"/>',
            "      </Source>",
        ]
    lines += ["    </Array>", "  </Group>", "</VRTDataset>", ""]
    missing = sorted(set(steps) - {d for d, _ in files})
    return "\n".join(lines), len(files), nt, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True, help="file of sources, one per line")
    ap.add_argument("--array", required=True)
    ap.add_argument("--pattern", required=True,
                    help="regex on the file name; group 1 is YYYYMMDD (day) or YYYYMM (month)")
    ap.add_argument("--cadence", choices=("day", "month"), default="day")
    ap.add_argument("--max-missing", type=int, default=-1,
                    help="fail when more steps than this have no file (-1: no limit)")
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    text, nfiles, nt, missing = plan(sources, a.array, a.pattern, a.cadence)
    unit = "days" if a.cadence == "day" else "months"
    if missing:
        shown = ", ".join(str(d) for d in missing[:20]) + (" ..." if len(missing) > 20 else "")
        print(f"plan_cog: {len(missing)} of {nt} {unit} have no file: {shown}", file=sys.stderr)
    if 0 <= a.max_missing < len(missing):
        sys.exit(f"plan_cog: {len(missing)} missing {unit}, more than --max-missing {a.max_missing}; "
                 "no plan written (check the listing, or raise the limit)")
    with open(a.vrt, "w") as f:
        f.write(text)
    print(f"plan_cog: {nfiles} files over {nt} {unit} -> {a.vrt}")


if __name__ == "__main__":
    main()

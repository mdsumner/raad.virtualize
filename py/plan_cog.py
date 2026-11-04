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
--pattern applied to the file name, as YYYYMMDD (--cadence day, the default),
YYYYMMDD (--cadence 5day), or YYYYMM (--cadence month).

--cadence month: one time step per calendar month, the time value the first
day of the month in days since 1970-01-01, written as InlineValues (months
are not evenly spaced in days). The time index of a file is its month minus
the first month. --cadence 5day: one step per 5-day period, by either of the
calendars axis() recognises from the file dates (per month, per year, or
continuous). Steps evenly spaced in days
are written as RegularlySpacedValues, others as InlineValues.

Steps (days or months) between the first and last date with no file are
listed on stderr. --max-missing N stops (exit 1, no plan written) when more
than N steps are missing: a listing that dropped directories (HTTP 503 from
the server, for example) then fails instead of planning a shorter series.
Default -1, no limit.

--overviews: each overview level of the first file becomes one more array,
<array>_x<f> (f the size ratio to full resolution, rounded), on its own
dims y_x<f> and x_x<f> and the same time axis, with one source per file:
GTIFF_DIR:<k>:<file>, the overview's own IFD, which GDAL opens as an
ordinary GeoTIFF, so the plan reads every level and the harvest lists that
IFD's tiles. Sizes come from the IFD (GDAL rounds overview sizes up); the
cell size is the full-resolution one times the exact size ratio, so a level
covers the same extent. Each level carries attributes overview_of,
overview_factor ([y, x] size ratios) and overview_resampling (--resampling,
default unknown: GDAL does not record it in the file). Mask IFDs are not
levels. Every file must have the same levels (the harvest stops otherwise).

Usage:
  python plan_cog.py --sources sources.txt --array analysed_sst \
    --pattern '^(\\d{8})090000-.*\\.tif$' plan.vrt
  python plan_cog.py ... --overviews --resampling AVERAGE plan.vrt
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


PENTAD_DAYS = (1, 6, 11, 16, 21, 26)


def axis(dates, cadence):
    """(index of a date, first date of every step) for the sorted file dates.

    day    one step per day
    month  one step per calendar month (dates are the first of the month)
    5day   one step per 5-day period. Three calendars are recognised from
           the dates themselves: periods starting on days 1, 6, 11, 16, 21,
           26 of each month (the last one runs to the month end); periods
           starting on day of year 1, 6, ..., 361 of each year, and 366 in a
           leap year (the ESA OC-CCI 5-day product); or a
           continuous 5-day sequence from the first date. Dates fitting none
           stop the plan."""
    t0, t1 = dates[0], dates[-1]
    if cadence == "day":
        steps = [t0 + dt.timedelta(i) for i in range((t1 - t0).days + 1)]
    elif cadence == "month":
        n = month_index(t1, t0) + 1
        steps = [dt.date(t0.year + (t0.month - 1 + i) // 12, (t0.month - 1 + i) % 12 + 1, 1)
                 for i in range(n)]
    elif all(d.day in PENTAD_DAYS for d in dates):
        steps, y, m = [], t0.year, t0.month
        while (y, m) <= (t1.year, t1.month):
            steps += [dt.date(y, m, k) for k in PENTAD_DAYS]
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        steps = [d for d in steps if t0 <= d <= t1]
    elif all((d.timetuple().tm_yday - 1) % 5 == 0 for d in dates):
        # 73 periods a year, and a 74th starting on day 366 of a leap year
        steps = [d for y in range(t0.year, t1.year + 1)
                 for d in (dt.date(y, 1, 1) + dt.timedelta(5 * k) for k in range(74))
                 if d.year == y and t0 <= d <= t1]
    elif all((d - t0).days % 5 == 0 for d in dates):
        steps = [t0 + dt.timedelta(5 * i) for i in range((t1 - t0).days // 5 + 1)]
    else:
        bad = ", ".join(str(d) for d in dates[:12])
        sys.exit(f"plan_cog: 5day dates fit none of days {PENTAD_DAYS} of each month, "
                 f"day of year 1, 6, ..., 361, or a continuous 5-day sequence (first dates: {bad})")
    pos = {d: i for i, d in enumerate(steps)}
    return pos.__getitem__, steps


def dated(sources, pattern, cadence="day"):
    rx = re.compile(pattern)
    fmt = "%Y%m" if cadence == "month" else "%Y%m%d"
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


def overview_dirs(path):
    """[(k, xsize, ysize)] for the overview levels of band 1 of a GeoTIFF, in
    GDAL's overview order, with k the TIFF directory (GTIFF_DIR:<k>:, 1 is
    full resolution) holding each. A directory is a level when its size is an
    overview's and its type and band count are the full-resolution ones (a
    mask IFD of the same size is Byte with one band); found by probing the
    directories in order, not by assuming k = level + 2."""
    ds = gdal.Open(path)
    b = ds.GetRasterBand(1)
    want = [(b.GetOverview(i).XSize, b.GetOverview(i).YSize) for i in range(b.GetOverviewCount())]
    if not want:
        return []
    out, k, i = [], 2, 0
    while i < len(want):
        try:
            d = gdal.Open(f"GTIFF_DIR:{k}:{path}")
        except RuntimeError:
            sys.exit(f"plan_cog: {path}: overview {i} ({want[i][0]} x {want[i][1]}) has no TIFF directory")
        db = d.GetRasterBand(1)
        if ((d.RasterXSize, d.RasterYSize) == want[i] and d.RasterCount == ds.RasterCount
                and db.DataType == b.DataType):
            out.append((k, d.RasterXSize, d.RasterYSize))
            i += 1
        k += 1
    return out


def attribute(name, value):
    """A multidim VRT <Attribute>: a string, or a list of numbers."""
    if isinstance(value, str):
        return [f'      <Attribute name="{name}">', "        <DataType>String</DataType>",
                f"        <Value>{escape(value)}</Value>", "      </Attribute>"]
    return ([f'      <Attribute name="{name}">', "        <DataType>Float64</DataType>"]
            + [f"        <Value>{v:.17g}</Value>" for v in value] + ["      </Attribute>"])


def plan(sources, array, pattern, cadence="day", overviews=False, resampling="unknown"):
    files = dated(sources, pattern, cadence)
    if not files:
        sys.exit("plan_cog: no source matches the pattern")
    ds = gdal.Open(files[0][1])
    b = ds.GetRasterBand(1)
    nx, ny = ds.RasterXSize, ds.RasterYSize
    bx, by = b.GetBlockSize()
    x0, dx, _, y0, _, dy = ds.GetGeoTransform()
    t0 = files[0][0]
    index, steps = axis([d for d, _ in files], cadence)
    nt = len(steps)
    days = [(d - EPOCH).days for d in steps]
    inc = days[1] - days[0] if nt > 1 else 1
    if all(b - a == inc for a, b in zip(days, days[1:])):
        tvals = f'      <RegularlySpacedValues start="{days[0]}" increment="{inc}"/>'
    else:
        tvals = (f'      <InlineValues offset="0" count="{nt}">'
                 + " ".join(str(v) for v in days) + "</InlineValues>")
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
    def grid(suffix, nyl, nxl, dyl, dxl):
        out = []
        if suffix:
            out += [f'    <Dimension name="y{suffix}" size="{nyl}" type="HORIZONTAL_Y" indexingVariable="y{suffix}"/>',
                    f'    <Dimension name="x{suffix}" size="{nxl}" type="HORIZONTAL_X" indexingVariable="x{suffix}"/>']
        for name, start, inc in ((f"y{suffix}", y0 + dyl / 2, dyl), (f"x{suffix}", x0 + dxl / 2, dxl)):
            out += [
                f'    <Array name="{name}">',
                "      <DataType>Float64</DataType>",
                f'      <DimensionRef ref="{name}"/>',
                f'      <RegularlySpacedValues start="{start:.10g}" increment="{inc:.10g}"/>',
                "    </Array>",
            ]
        return out

    def data_array(name, suffix, nyl, nxl, prefix="", attrs=()):
        out = [
            f'    <Array name="{name}">',
            f"      <DataType>{VRT_TYPE[b.DataType]}</DataType>",
            '      <DimensionRef ref="time"/>',
            f'      <DimensionRef ref="y{suffix}"/>',
            f'      <DimensionRef ref="x{suffix}"/>',
            f"      <BlockSize>1,{by},{bx}</BlockSize>",
        ]
        if srs is not None:
            out.append(f'      <SRS dataAxisToSRSAxisMapping="2,1">{escape(srs.ExportToWkt())}</SRS>')
        if b.GetUnitType():
            out.append(f"      <Unit>{escape(b.GetUnitType())}</Unit>")
        if b.GetNoDataValue() is not None:
            out.append(f"      <NoDataValue>{b.GetNoDataValue():.17g}</NoDataValue>")
        if b.GetOffset():
            out.append(f"      <Offset>{b.GetOffset():.17g}</Offset>")
        if b.GetScale() not in (None, 1):
            out.append(f"      <Scale>{b.GetScale():.17g}</Scale>")
        for k, v in attrs:
            out += attribute(k, v)
        for d, s in files:
            out += [
                "      <Source>",
                f"        <SourceFilename>{escape(prefix + s)}</SourceFilename>",
                "        <SourceBand>1</SourceBand>",
                "        <SourceTranspose>-1,0,1</SourceTranspose>",
                f'        <SourceSlab offset="0,0,0" count="1,{nyl},{nxl}" step="1,1,1"/>',
                f'        <DestSlab offset="{index(d)},0,0"/>',
                "      </Source>",
            ]
        return out + ["    </Array>"]

    levels = overview_dirs(files[0][1]) if overviews else []
    seen = set()
    for k, ox, oy in levels:
        fx, fy = nx / ox, ny / oy
        f = round(fx)
        if f in seen:
            sys.exit(f"plan_cog: two overview levels round to factor {f}")
        seen.add(f)
    # level dimensions go with the others, ahead of every array
    lines[5:5] = [ln for k, ox, oy in levels for ln in grid(f"_x{round(nx / ox)}", oy, ox, dy * ny / oy, dx * nx / ox)[:2]]
    lines += grid("", ny, nx, dy, dx)
    lines += data_array(array, "", ny, nx)
    for k, ox, oy in levels:
        sfx = f"_x{round(nx / ox)}"
        lines += grid(sfx, oy, ox, dy * ny / oy, dx * nx / ox)[2:]
        lines += data_array(array + sfx, sfx, oy, ox, prefix=f"GTIFF_DIR:{k}:",
                            attrs=[("overview_of", array), ("overview_factor", [ny / oy, nx / ox]),
                                   ("overview_resampling", resampling)])
    lines += ["  </Group>", "</VRTDataset>", ""]
    missing = sorted(set(steps) - {d for d, _ in files})
    return "\n".join(lines), len(files), nt, missing, len(levels)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True, help="file of sources, one per line")
    ap.add_argument("--array", required=True)
    ap.add_argument("--pattern", required=True,
                    help="regex on the file name; group 1 is YYYYMMDD (day) or YYYYMM (month)")
    ap.add_argument("--cadence", choices=("day", "5day", "month"), default="day")
    ap.add_argument("--max-missing", type=int, default=-1,
                    help="fail when more steps than this have no file (-1: no limit)")
    ap.add_argument("--overviews", action="store_true",
                    help="add each overview level as an array <array>_x<factor>")
    ap.add_argument("--resampling", default="unknown",
                    help="overview resampling to record (GDAL does not store it)")
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    text, nfiles, nt, missing, nlev = plan(sources, a.array, a.pattern, a.cadence,
                                           a.overviews, a.resampling)
    unit = {"day": "days", "5day": "5-day periods", "month": "months"}[a.cadence]
    if missing:
        shown = ", ".join(str(d) for d in missing[:200]) + (" ..." if len(missing) > 200 else "")
        print(f"plan_cog: {len(missing)} of {nt} {unit} have no file: {shown}", file=sys.stderr)
    if 0 <= a.max_missing < len(missing):
        sys.exit(f"plan_cog: {len(missing)} missing {unit}, more than --max-missing {a.max_missing}; "
                 "no plan written (check the listing, or raise the limit)")
    with open(a.vrt, "w") as f:
        f.write(text)
    lev = f", {nlev} overview levels" if a.overviews else ""
    print(f"plan_cog: {nfiles} files over {nt} {unit}{lev} -> {a.vrt}")


if __name__ == "__main__":
    main()

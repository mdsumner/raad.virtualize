"""plan_static.py -- mdim VRT plan for static 2D rasters, one array per file.

For a set of single-band GeoTIFFs on one grid with no time axis (Bedmap3).
Each file is one array of dimensions (y, x), named by its file name without
the extension, or by NAME on a sources line of the form NAME<TAB>SOURCE. Sources are <SourceBand> with no <SourceTranspose>; the
<SourceSlab> states the extent so a read opens only the sources it touches.

Every file must share the grid, type, nodata and tiling of the first; all
are opened and any difference stops the plan.

--overviews: each overview level of the files (every file must have the
same ones) becomes one more array per file, <name>_x<f>, on dims y_x<f> and
x_x<f> shared by all files, with the source GTIFF_DIR:<k>:<file> (see
py/plan_cog.py --overviews). --resampling NAME=METHOD records each array's
overview resampling (repeatable; --resampling METHOD for every array without
its own; default unknown).

Usage:
  python plan_static.py --sources sources.txt plan.vrt
  python plan_static.py --sources sources.txt --overviews \
    --resampling AVERAGE --resampling mask=NEAREST plan.vrt
"""
import argparse
import os
import sys
from xml.sax.saxutils import escape

from osgeo import gdal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_cog import attribute, overview_dirs  # noqa: E402

gdal.UseExceptions()
VRT_TYPE = {gdal.GDT_Byte: "Byte", gdal.GDT_Int16: "Int16", gdal.GDT_UInt16: "UInt16",
            gdal.GDT_Int32: "Int32", gdal.GDT_Float32: "Float32", gdal.GDT_Float64: "Float64"}


def grid(ds):
    b = ds.GetRasterBand(1)
    return ds.RasterXSize, ds.RasterYSize, ds.GetGeoTransform(), ds.GetSpatialRef().ExportToWkt(), \
        b.DataType, b.GetNoDataValue(), tuple(b.GetBlockSize())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True, help="file of sources, one per line")
    ap.add_argument("--overviews", action="store_true",
                    help="add each overview level as an array <name>_x<factor>")
    ap.add_argument("--resampling", action="append", default=[],
                    help="METHOD, or NAME=METHOD: overview resampling to record")
    ap.add_argument("vrt")
    a = ap.parse_args()
    how = dict(r.split("=", 1) if "=" in r else ("", r) for r in a.resampling)
    if a.resampling and not a.overviews:
        sys.exit("plan_static: --resampling needs --overviews")
    with open(a.sources) as f:
        lines_in = [s.strip() for s in f if s.strip()]
    # NAME<TAB>SOURCE names the array; a bare SOURCE is named by its file
    named = [ln.split("\t", 1) if "\t" in ln else
             [os.path.splitext(os.path.basename(ln))[0], ln] for ln in lines_in]
    names = {n: s for n, s in named}
    sources = [s for _, s in named]
    if len(names) < len(named):
        sys.exit("plan_static: two sources have the same array name")
    nx, ny, gt, wkt, dtype, nodata, block = first = grid(gdal.Open(sources[0]))
    x0, dx, _, y0, _, dy = gt
    levels = overview_dirs(sources[0]) if a.overviews else []
    if len({round(nx / ox) for _, ox, _ in levels}) < len(levels):
        sys.exit("plan_static: two overview levels round to the same factor")
    grids = [("", ny, nx, dy, dx)] + [(f"_x{round(nx / ox)}", oy, ox, dy * ny / oy, dx * nx / ox)
                                      for _, ox, oy in levels]
    lines = ["<VRTDataset>", '  <Group name="/">']
    for sfx, nyl, nxl, _, _ in grids:
        lines += [f'    <Dimension name="y{sfx}" size="{nyl}" type="HORIZONTAL_Y" indexingVariable="y{sfx}"/>',
                  f'    <Dimension name="x{sfx}" size="{nxl}" type="HORIZONTAL_X" indexingVariable="x{sfx}"/>']
    for sfx, _, _, dyl, dxl in grids:
        for name, start, inc in ((f"y{sfx}", y0 + dyl / 2, dyl), (f"x{sfx}", x0 + dxl / 2, dxl)):
            lines += [f'    <Array name="{name}">', "      <DataType>Float64</DataType>",
                      f'      <DimensionRef ref="{name}"/>',
                      f'      <RegularlySpacedValues start="{start:.17g}" increment="{inc:.17g}"/>',
                      "    </Array>"]
    for name, s in named:
        ds = gdal.Open(s)
        if grid(ds) != first:
            sys.exit(f"plan_static: {s} differs from {sources[0]} in grid, type, nodata or tiling")
        unit = ds.GetRasterBand(1).GetUnitType()
        mine = overview_dirs(s) if a.overviews else []
        if [(ox, oy) for _, ox, oy in mine] != [(ox, oy) for _, ox, oy in levels]:
            sys.exit(f"plan_static: {s} has other overview levels than {sources[0]}")
        for (sfx, nyl, nxl, _, _), k in zip(grids, [None] + [k for k, _, _ in mine]):
            lines += [f'    <Array name="{name}{sfx}">', f"      <DataType>{VRT_TYPE[dtype]}</DataType>",
                      f'      <DimensionRef ref="y{sfx}"/>', f'      <DimensionRef ref="x{sfx}"/>',
                      f"      <BlockSize>{block[1]},{block[0]}</BlockSize>",
                      f'      <SRS dataAxisToSRSAxisMapping="2,1">{escape(wkt)}</SRS>']
            if unit:
                lines.append(f"      <Unit>{escape(unit)}</Unit>")
            if nodata is not None:
                lines.append(f"      <NoDataValue>{nodata:.17g}</NoDataValue>")
            if k is not None:
                lines += attribute("overview_of", name)
                lines += attribute("overview_factor", [ny / nyl, nx / nxl])
                lines += attribute("overview_resampling", how.get(name, how.get("", "unknown")))
            src = s if k is None else f"GTIFF_DIR:{k}:{s}"
            lines += ["      <Source>", f"        <SourceFilename>{escape(src)}</SourceFilename>",
                      "        <SourceBand>1</SourceBand>",
                      f'        <SourceSlab offset="0,0" count="{nyl},{nxl}" step="1,1"/>',
                      '        <DestSlab offset="0,0"/>', "      </Source>", "    </Array>"]
    lines += ["  </Group>", "</VRTDataset>", ""]
    with open(a.vrt, "w") as f:
        f.write("\n".join(lines))
    lev = f", {len(levels)} overview levels each" if levels else ""
    print(f"plan_static: {len(sources)} arrays of {ny} x {nx}{lev} -> {a.vrt}")


if __name__ == "__main__":
    main()

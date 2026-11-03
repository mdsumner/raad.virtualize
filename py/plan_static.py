"""plan_static.py -- mdim VRT plan for static 2D rasters, one array per file.

For a set of single-band GeoTIFFs on one grid with no time axis (Bedmap3).
Each file is one array of dimensions (y, x), named by its file name without
the extension. Sources are <SourceBand> with no <SourceTranspose>; the
<SourceSlab> states the extent so a read opens only the sources it touches.

Every file must share the grid, type, nodata and tiling of the first; all
are opened and any difference stops the plan.

Usage:
  python plan_static.py --sources sources.txt plan.vrt
"""
import argparse
import os
import sys
from xml.sax.saxutils import escape

from osgeo import gdal

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
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    nx, ny, gt, wkt, dtype, nodata, block = first = grid(gdal.Open(sources[0]))
    x0, dx, _, y0, _, dy = gt
    lines = ["<VRTDataset>", '  <Group name="/">',
             f'    <Dimension name="y" size="{ny}" type="HORIZONTAL_Y" indexingVariable="y"/>',
             f'    <Dimension name="x" size="{nx}" type="HORIZONTAL_X" indexingVariable="x"/>']
    for name, start, inc in (("y", y0 + dy / 2, dy), ("x", x0 + dx / 2, dx)):
        lines += [f'    <Array name="{name}">', "      <DataType>Float64</DataType>",
                  f'      <DimensionRef ref="{name}"/>',
                  f'      <RegularlySpacedValues start="{start:.17g}" increment="{inc:.17g}"/>',
                  "    </Array>"]
    for s in sources:
        ds = gdal.Open(s)
        if grid(ds) != first:
            sys.exit(f"plan_static: {s} differs from {sources[0]} in grid, type, nodata or tiling")
        name = os.path.splitext(os.path.basename(s))[0]
        unit = ds.GetRasterBand(1).GetUnitType()
        lines += [f'    <Array name="{name}">', f"      <DataType>{VRT_TYPE[dtype]}</DataType>",
                  '      <DimensionRef ref="y"/>', '      <DimensionRef ref="x"/>',
                  f"      <BlockSize>{block[1]},{block[0]}</BlockSize>",
                  f'      <SRS dataAxisToSRSAxisMapping="2,1">{escape(wkt)}</SRS>']
        if unit:
            lines.append(f"      <Unit>{escape(unit)}</Unit>")
        if nodata is not None:
            lines.append(f"      <NoDataValue>{nodata:.17g}</NoDataValue>")
        lines += ["      <Source>", f"        <SourceFilename>{escape(s)}</SourceFilename>",
                  "        <SourceBand>1</SourceBand>",
                  f'        <SourceSlab offset="0,0" count="{ny},{nx}" step="1,1"/>',
                  '        <DestSlab offset="0,0"/>', "      </Source>", "    </Array>"]
    lines += ["  </Group>", "</VRTDataset>", ""]
    with open(a.vrt, "w") as f:
        f.write("\n".join(lines))
    print(f"plan_static: {len(sources)} arrays of {ny} x {nx} -> {a.vrt}")


if __name__ == "__main__":
    main()

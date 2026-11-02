"""plan_bbox.py -- lon/lat bounding box of a projected grid in a plan VRT.

For the STAC render (R/stac.R), which computes a bbox only for lon/lat
grids and writes the globe otherwise. Reads the plan's first <SRS> and the
x/y coordinate arrays (RegularlySpacedValues or InlineValues of the
HORIZONTAL_X / HORIZONTAL_Y dimensions), takes the cell-edge outline of the
grid, densified (--n points a side), transforms it to EPSG:4326 and prints
west,south,east,north. When a pole lies inside the grid (polar
stereographic sea ice grids), the box runs to that pole over every
longitude: -180,south,180,90 or -180,-90,180,north. Prints nothing (exit 0)
when the plan has no SRS or no x/y coordinates, or the SRS is geographic.

Usage:
  python plan_bbox.py plan.vrt [--n 200]
"""
import argparse
import sys
import xml.etree.ElementTree as ET

import numpy as np
from osgeo import osr


def coord(group, dim):
    arr = next((a for a in group.findall("Array") if a.get("name") == dim), None)
    if arr is None:
        return None
    rs = arr.find("RegularlySpacedValues")
    n = next(int(d.get("size")) for d in group.findall("Dimension") if d.get("name") == dim)
    if rs is not None:
        return float(rs.get("start")) + float(rs.get("increment")) * np.arange(n)
    iv = arr.find("InlineValues")
    if iv is not None:
        return np.array([float(x) for x in iv.text.split()])
    return None


def edges(v):
    s = abs(v[1] - v[0]) if v.size > 1 else 0.0
    return v.min() - s / 2, v.max() + s / 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan")
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    g = ET.parse(a.plan).getroot().find("Group")
    srs_el = g.find(".//Array/SRS")
    if srs_el is None or not (srs_el.text or "").strip():
        return
    src = osr.SpatialReference()
    src.SetFromUserInput(srs_el.text)
    if src.IsGeographic():
        return
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dims = {d.get("type"): d.get("name") for d in g.findall("Dimension")}
    xv = coord(g, dims.get("HORIZONTAL_X", "x"))
    yv = coord(g, dims.get("HORIZONTAL_Y", "y"))
    if xv is None or yv is None:
        return
    (x0, x1), (y0, y1) = edges(xv), edges(yv)
    t = np.linspace(0, 1, a.n)
    xs = np.concatenate([x0 + (x1 - x0) * t, np.full(a.n, x1), x1 - (x1 - x0) * t, np.full(a.n, x0)])
    ys = np.concatenate([np.full(a.n, y0), y0 + (y1 - y0) * t, np.full(a.n, y1), y1 - (y1 - y0) * t])
    ll = osr.SpatialReference()
    ll.ImportFromEPSG(4326)
    ll.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    fwd = osr.CoordinateTransformation(src, ll)
    pts = np.array(fwd.TransformPoints(np.column_stack([xs, ys]).tolist()))[:, :2]
    pts = pts[np.isfinite(pts).all(axis=1)]
    if not len(pts):
        sys.exit("plan_bbox: no edge point transforms to lon/lat")
    w, e = float(pts[:, 0].min()), float(pts[:, 0].max())
    s, n = float(pts[:, 1].min()), float(pts[:, 1].max())
    inv = osr.CoordinateTransformation(ll, src)
    for lat in (90.0, -90.0):
        try:
            px, py, _ = inv.TransformPoint(0.0, lat)
        except RuntimeError:
            continue
        if np.isfinite(px) and x0 <= px <= x1 and y0 <= py <= y1:
            w, e = -180.0, 180.0
            if lat > 0:
                n = 90.0
            else:
                s = -90.0
    print(",".join(f"{v:.6f}" for v in (w, s, e, n)))


if __name__ == "__main__":
    main()

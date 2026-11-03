"""thumbnail.py -- overview PNG of one field of a byterefs/0.1 store.

  python py/thumbnail.py STORE OUT.png [--array A] [--width 512]
                         [--palette viridis|topo|ice] [--log10]

Reads the source that holds the last placement of ARRAY (default the first
referenced data array) at its verbatim path, as the build sees it, and draws
one 2D field: the first element of every dimension other than the last two
(y, x) within that source's slab, which is the surface level and first time
step of the source. A raster source (GeoTIFF, COG) is read with the classic
API, so its overviews serve the reduction; any other source through the
multidimensional API. Values are stretched between the 2nd and 98th
percentiles of the valid cells (log10 first with --log10) onto the palette;
nodata, NaN and values outside the CF valid range are transparent. A south-up grid is flipped and a 0..360
longitude grid is rotated to -180..180.

Prints one line describing the field (array, source, element), which run.sh
passes to the STAC thumbnail asset.

Palettes: viridis (default), topo (blues below 0, earth tones above, for
elevation and bathymetry; the stretch is split at 0), ice (dark blue to
white, for concentration).
"""
import argparse
import json
import os
import sqlite3
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

PALETTES = {
    "viridis": ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c",
                "#28ae80", "#5ec962", "#addc30", "#fde725"],
    "ice": ["#08306b", "#2171b5", "#6baed6", "#c6dbef", "#ffffff"],
    "topo_below": ["#08306b", "#08519c", "#2171b5", "#4292c6", "#6baed6", "#c6dbef"],
    "topo_above": ["#c7e9c0", "#f6e8c3", "#dfc27d", "#bf812d", "#8c510a", "#f0f0f0"],
}


def ramp(hexes, n=256):
    """n x 3 uint8 colour table by linear interpolation between anchors."""
    rgb = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in hexes], float)
    t = np.linspace(0, 1, len(hexes))
    u = np.linspace(0, 1, n)
    return np.stack([np.interp(u, t, rgb[:, k]) for k in range(3)], 1).round().astype(np.uint8)


def pick(store, array):
    con = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    if array is None:
        row = con.execute("SELECT array FROM arrays WHERE kind = 'data' AND storage = 'referenced' "
                          "ORDER BY array LIMIT 1").fetchone()
        if row is None:
            sys.exit("thumbnail: no referenced data array in the store")
        array = row[0]
    rows = con.execute("SELECT s.source, p.source_array, p.src_offset, p.dest FROM placements p "
                       "JOIN sources s USING (source_id) WHERE p.array = ?", (array,)).fetchall()
    con.close()
    if not rows:
        sys.exit(f"thumbnail: array {array} has no placements")
    src, src_array, off, _ = max(rows, key=lambda r: json.loads(r[3]))
    return array, src, src_array, json.loads(off)


def valid_range(md):
    """(min, max) from CF valid_range, valid_min and valid_max, in stored
    (packed) units, so flag values such as land and pole hole are not drawn."""
    def num(x):
        if x is None:
            return []
        if isinstance(x, str):
            x = x.replace("{", " ").replace("}", " ").replace(",", " ").split()
        try:
            return [float(u) for u in (x if isinstance(x, (list, tuple)) else [x])]
        except (TypeError, ValueError):
            return []
    lo, hi = -np.inf, np.inf
    vr = num(md.get("valid_range"))
    if len(vr) == 2:
        lo, hi = vr
    if num(md.get("valid_min")):
        lo = num(md.get("valid_min"))[0]
    if num(md.get("valid_max")):
        hi = num(md.get("valid_max"))[0]
    return lo, hi


def read_classic(src, src_array, width):
    ds = gdal.OpenEx(src, gdal.OF_RASTER)
    if ds.RasterCount < 1 or ds.GetMetadata("SUBDATASETS"):
        return None
    band = int(src_array) if str(src_array).isdigit() else 1
    b = ds.GetRasterBand(band)
    small = gdal.Translate("", ds, format="MEM", bandList=[band], width=min(width, ds.RasterXSize),
                           resampleAlg="average")
    v = small.GetRasterBand(1).ReadAsArray().astype("float64")
    gt = ds.GetGeoTransform()
    md = {k.split("#")[-1]: val for k, val in b.GetMetadata().items()}
    return v, b.GetNoDataValue(), b.GetScale(), b.GetOffset(), gt[5] > 0, None, valid_range(md)


def read_mdim(src, src_array, off, width):
    ds = gdal.OpenEx(src, gdal.OF_MULTIDIM_RASTER)
    rg = ds.GetRootGroup()
    name = src_array if str(src_array).startswith("/") else "/" + str(src_array)
    arr = rg.OpenMDArrayFromFullname(name)
    if arr is None:
        sys.exit(f"thumbnail: {src} has no array {src_array}")
    n = arr.GetDimensionCount()
    if n < 2:
        sys.exit(f"thumbnail: {src_array} has fewer than two dimensions")
    view = arr.GetView("[" + ",".join([str(off[i]) for i in range(n - 2)] + [":", ":"]) + "]") \
        if n > 2 else arr
    dims = view.GetDimensions()
    classic = view.AsClassicDataset(1, 0)
    small = gdal.Translate("", classic, format="MEM", width=min(width, classic.RasterXSize),
                           resampleAlg="average")
    v = small.GetRasterBand(1).ReadAsArray().astype("float64")

    def coords(d):
        iv = d.GetIndexingVariable()
        return None if iv is None else np.asarray(iv.ReadAsArray(), dtype="float64").ravel()

    yv, xv = coords(dims[0]), coords(dims[1])
    south_up = yv is not None and len(yv) > 1 and yv[1] > yv[0]
    nd = arr.GetNoDataValueAsDouble() if arr.GetNoDataValueAsRaw() is not None else None
    md = {at.GetName(): at.Read() for at in (arr.GetAttributes() or [])}
    return v, nd, arr.GetScale(), arr.GetOffset(), south_up, xv, valid_range(md)


def colour(v, valid, palette, log10):
    rgba = np.zeros(v.shape + (4,), np.uint8)
    if not valid.any():
        return rgba, (np.nan, np.nan)
    if log10:
        valid &= v > 0
        v = np.where(valid, np.log10(np.where(valid, v, 1)), np.nan)
    lo, hi = np.percentile(v[valid], [2, 98])
    if palette == "topo":
        below, above = ramp(PALETTES["topo_below"]), ramp(PALETTES["topo_above"])
        lo_ = min(lo, -1.0)
        hi_ = max(hi, 1.0)
        neg = valid & (v < 0)
        pos = valid & (v >= 0)
        i = np.clip((v[neg] - lo_) / -lo_ * 255, 0, 255).astype(int)
        rgba[neg, :3] = below[i]
        j = np.clip(v[pos] / hi_ * 255, 0, 255).astype(int)
        rgba[pos, :3] = above[j]
    else:
        lut = ramp(PALETTES[palette])
        span = hi - lo if hi > lo else 1.0
        i = np.clip((v[valid] - lo) / span * 255, 0, 255).astype(int)
        rgba[valid, :3] = lut[i]
    rgba[valid, 3] = 255
    return rgba, (lo, hi)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("store")
    ap.add_argument("png")
    ap.add_argument("--array")
    ap.add_argument("--width", type=int, default=512)
    ap.add_argument("--palette", default="viridis", choices=["viridis", "topo", "ice"])
    ap.add_argument("--log10", action="store_true")
    a = ap.parse_args()

    array, src, src_array, off = pick(a.store, a.array)
    got = read_classic(src, src_array, a.width)
    if got is None:
        got = read_mdim(src, src_array, off, a.width)
    v, nodata, scale, offset, south_up, xv, (vmin, vmax) = got
    valid = np.isfinite(v) & (v >= vmin) & (v <= vmax)
    if nodata is not None and np.isfinite(nodata):
        valid &= v != nodata
    if scale not in (None, 1) or offset not in (None, 0):
        v = v * (scale or 1) + (offset or 0)
    if south_up:
        v, valid = v[::-1], valid[::-1]
    if xv is not None and len(xv) > 1 and xv.max() > 180 and xv.max() - xv.min() > 350:
        # 0..360 longitudes: columns east of 180 go first
        xs = np.linspace(xv[0], xv[-1], v.shape[1])
        east = xs > 180
        v = np.concatenate([v[:, east], v[:, ~east]], 1)
        valid = np.concatenate([valid[:, east], valid[:, ~east]], 1)
    rgba, (lo, hi) = colour(v, valid, a.palette, a.log10)

    mem = gdal.GetDriverByName("MEM").Create("", v.shape[1], v.shape[0], 4, gdal.GDT_Byte)
    for k in range(4):
        mem.GetRasterBand(k + 1).WriteArray(rgba[:, :, k])
    os.makedirs(os.path.dirname(os.path.abspath(a.png)), exist_ok=True)
    gdal.GetDriverByName("PNG").CreateCopy(a.png, mem)
    for ext in (".aux.xml",):
        if os.path.exists(a.png + ext):
            os.remove(a.png + ext)
    elem = ",".join(str(i) for i in off[:-2]) if len(off) > 2 else ""
    what = f"{array}{' [' + elem + ']' if elem else ''} from {os.path.basename(src)}"
    stretch = f"{'log10 ' if a.log10 else ''}{lo:.4g} to {hi:.4g}"
    print(f"{what}; {a.palette}, {stretch}")


if __name__ == "__main__":
    main()

"""thumbnail.py -- overview PNG of one field of a byterefs/0.1 store.

  python py/thumbnail.py STORE OUT.png [--array A] [--width 512]
                         [--palette viridis|topo|ice] [--log10]
                         [--source REGEX] [--transpose]

Reads the source that holds the last placement of ARRAY (default the first
referenced data array) at its verbatim path, as the build sees it, and draws
one 2D field: the first element of every dimension other than the last two
(y, x) within that source's slab, which is the surface level and first time
step of the source. A raster source (GeoTIFF, COG) is read with the classic
API, so its overviews serve the reduction; any other source through the
multidimensional API. Values are stretched between the 2nd and 98th
percentiles of the valid cells (log10 first with --log10) onto the palette;
nodata, NaN and values outside the CF valid range are transparent. A south-up grid is flipped; columns are
drawn in stored order (a 0..360 longitude grid is not rotated).

--source REGEX takes the last placement among the sources whose path
matches, rather than the last of all (a source with data, where the last
file holds only fill); --transpose draws the last dimension down the image
and the one before it across (profiles by level: levels down).

Prints one line describing the field (array, source, element), which run.sh
passes to the STAC thumbnail asset.

Palettes: viridis (default), topo (blues below 0, earth tones above, for
elevation and bathymetry; the stretch is split at 0), ice (dark blue to
white, for concentration).
"""
import argparse
import json
import os
import re
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


def pick(store, array, source_rx=None):
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
    if source_rx:
        rows = [r for r in rows if re.search(source_rx, r[0])]
        if not rows:
            sys.exit(f"thumbnail: no source of {array} matches {source_rx!r}")
    src, src_array, off, _ = max(rows, key=lambda r: json.loads(r[3]))
    return array, src, src_array, json.loads(off)


def num(x):
    """The numbers in an attribute value: a number, a list, or a string such
    as "{-1,1}"."""
    if x is None:
        return []
    if isinstance(x, str):
        x = x.replace("{", " ").replace("}", " ").replace(",", " ").split()
    try:
        return [float(u) for u in (x if isinstance(x, (list, tuple)) else [x])]
    except (TypeError, ValueError):
        return []


def packing(scale, offset, md):
    """The driver's scale and offset, else CF scale_factor and add_offset from
    the attributes (the HDF5 driver leaves them there)."""
    if scale is None and num(md.get("scale_factor")):
        scale = num(md.get("scale_factor"))[0]
    if offset is None and num(md.get("add_offset")):
        offset = num(md.get("add_offset"))[0]
    return scale, offset


def valid_range(md):
    """(min, max) from CF valid_range, valid_min and valid_max, in stored
    (packed) units, so flag values such as land and pole hole are not drawn."""
    lo, hi = -np.inf, np.inf
    vr = num(md.get("valid_range"))
    if len(vr) == 2:
        lo, hi = vr
    if num(md.get("valid_min")):
        lo = num(md.get("valid_min"))[0]
    if num(md.get("valid_max")):
        hi = num(md.get("valid_max"))[0]
    return lo, hi


def own_subdataset(desc, src, src_array):
    """False when a driver opened a subdataset of its own choosing that is not
    src_array. The HDF5 driver lists only 2D and 3D datasets, so a BRAN file
    with a 4D field opens as its one 2D dataset, Time_bnds (description
    HDF5:"<file>"://Time_bnds)."""
    if desc == src or str(src_array).isdigit():
        return True
    leaf = str(src_array).strip("/").split("/")[-1]
    return re.search(r"[:/]" + re.escape(leaf) + r"$", desc) is not None


def read_classic(src, src_array, width):
    ds = gdal.OpenEx(src, gdal.OF_RASTER)
    if ds.RasterCount < 1 or ds.GetMetadata("SUBDATASETS"):
        return None
    if not own_subdataset(ds.GetDescription(), src, src_array):
        return None
    band = int(src_array) if str(src_array).isdigit() else 1
    b = ds.GetRasterBand(band)
    small = gdal.Translate("", ds, format="MEM", bandList=[band], width=min(width, ds.RasterXSize),
                           resampleAlg="average")
    v = small.GetRasterBand(1).ReadAsArray().astype("float64")
    gt = ds.GetGeoTransform()
    md = {k.split("#")[-1]: val for k, val in b.GetMetadata().items()}
    return (v, b.GetNoDataValue(), *packing(b.GetScale(), b.GetOffset(), md), gt[5] > 0, None,
            valid_range(md))


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
    return v, nd, *packing(arr.GetScale(), arr.GetOffset(), md), south_up, xv, valid_range(md)


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
    ap.add_argument("--source", help="regex: draw the last placement among matching sources")
    ap.add_argument("--transpose", action="store_true", help="last dimension down the image")
    ap.add_argument("--render", metavar="PATH",
                    help="also write a STAC `renders` object (render extension) with the "
                         "thumbnail's stretch, for viewers that draw the store (run.sh: "
                         "STAC_RENDERS when the config sets none)")
    ap.add_argument("--render-assets", default="icechunk",
                    help="comma-separated asset keys the render targets")
    ap.add_argument("--source-remap", action="append", default=[], metavar="FROM=TO",
                    help="open the source with the path prefix FROM replaced by TO, for a source "
                         "not mounted here (run.sh: SOURCE_READ_REMAP)")
    a = ap.parse_args()

    array, src, src_array, off = pick(a.store, a.array, a.source)
    for rule in a.source_remap:
        frm, sep, to = rule.partition("=")
        if not sep or not frm:
            sys.exit(f"thumbnail: --source-remap {rule!r} is not FROM=TO")
        if src.startswith(frm):
            src = to + src[len(frm):]
    def read():
        got = read_classic(src, src_array, a.width)
        return got if got is not None else read_mdim(src, src_array, off, a.width)
    try:
        got = read()
    except RuntimeError as e:
        # netCDF over /vsi needs userfaultfd, which docker's default seccomp
        # blocks; a netCDF-4 source opens with the HDF5 driver instead
        if "userfaultfd" not in str(e):
            raise
        # GDAL_SKIP is read only when drivers register: deregister instead
        gdal.GetDriverByName("netCDF").Deregister()
        got = read()
    v, nodata, scale, offset, south_up, xv, (vmin, vmax) = got
    valid = np.isfinite(v) & (v >= vmin) & (v <= vmax)
    if nodata is not None and np.isfinite(nodata):
        valid &= v != nodata
    if scale not in (None, 1) or offset not in (None, 0):
        v = v * (scale or 1) + (offset or 0)
    if south_up:
        v, valid = v[::-1], valid[::-1]
    if a.transpose:
        v, valid = v.T, valid.T
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
    if a.render:
        write_render(a.render, array, (lo, hi), scale, offset, a.palette, a.log10,
                     [k for k in a.render_assets.split(",") if k], what)
    print(f"{what}; {a.palette}, {stretch}")


def write_render(path, array, stretch, scale, offset, palette, log10, assets, what):
    """A STAC `renders` object (render extension v2) for array, from the
    thumbnail's stretch. `rescale` applies to the stored values: the
    collection declares no `raster:bands` scale and offset for a renderer to
    unscale by, and the viewers that read it (portolan-browser, docs/viewer)
    colour stored values. The stretch is in physical units, so a CF-packed
    array's is converted back with its scale_factor and add_offset. Written
    only for the viridis palette (the one colormap name both viewers share)
    and not for a log10 stretch, which `rescale` cannot state."""
    if os.path.exists(path):
        os.remove(path)
    lo, hi = stretch
    if palette != "viridis" or log10 or not assets or not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return
    s, o = (scale or 1.0), (offset or 0.0)
    stored = sorted(((lo - o) / s, (hi - o) / s))
    render = {array: {
        "title": f"{array}, 2nd to 98th percentile of {what}",
        "assets": assets,
        "rescale": [[float(f"{v:.6g}") for v in stored]],
        "colormap_name": palette,
    }}
    with open(path, "w") as f:
        json.dump(render, f)


if __name__ == "__main__":
    main()

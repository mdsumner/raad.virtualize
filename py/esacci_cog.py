"""esacci_cog.py -- Cloud Optimized GeoTIFFs of ESA CCI Ocean Colour netCDF files.

Lists the netCDF files of a THREDDS catalog of the ESA Ocean Colour CCI
release (www.oceancolour.org), downloads each, and writes one COG per
requested variable, then reads each COG back and compares it with the
netCDF array; a file with any differing pixel is a failure and its COG is
removed. Re-running skips every COG already written, locally (--out) or in
the bucket (--done, a listing of COG names already uploaded).

The geographic grids are 8640 x 4320 (1/24 degree, -180..180, -90..90).
The netCDF files carry no CRS; the COGs are EPSG:4326 with the geotransform
(-180, 1/24, 0, 90, 0, -1/24), after checking that the file's own
coordinates agree to 1e-6 degree.

COG settings, for the byte-reference forms built on these files (see
docs/esacci-oc.md):

  COMPRESS=ZSTD LEVEL=17   write-once product (--level)
  PREDICTOR=NO             a predictor (2 or 3) is written as a filter that
                           GDAL's Zarr driver does not read, so the kerchunk
                           and Icechunk forms would be unreadable by GDAL
  BLOCKSIZE=512            one tile is one Zarr chunk
  SPARSE_OK=FALSE          every tile has a reference; an all-nodata tile
                           compresses to a few hundred bytes
  AVERAGE overviews        not indexed
  values and type          as in the netCDF; for a floating point variable
                           the netCDF _FillValue (9.96921e+36) becomes NaN,
                           the COG nodata (--fill source keeps it)

Output layout, under --out, from the THREDDS path after the release:

  <release>/<projection>/<cadence>/<variable>/<YYYY>/<stem>_<variable>.tif
  manifest/<UTC time>.tsv     one row per COG written by this run

Every COG carries SOURCE_URL, SOURCE_FILE, SOURCE_BYTES and SOURCE_SHA256
(the netCDF it was made from) as dataset metadata, with the variable's
long_name, standard_name and units. A COG is written to a temporary name
and renamed when it has been verified, so an interrupted run leaves no
partial COG under its final name.

Usage:
  python py/esacci_cog.py \\
    --catalog https://www.oceancolour.org/thredds/catalog/cci/v6.0-release/geographic/monthly/chlor_a/catalog.xml \\
    --var chlor_a --out $MYSCRATCH/esacci-oc/cog --tmp $MYSCRATCH/esacci-oc/download \\
    --workers 8 [--years 2024 2025] [--done done.txt] [--list-only]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import os
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

NS = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0",
      "x": "http://www.w3.org/1999/xlink"}
NX, NY, RES = 8640, 4320, 1 / 24
GT = (-180.0, RES, 0.0, 90.0, 0.0, -RES)
UA = "raad.virtualize esacci_cog.py"
COLUMNS = ["cog", "variable", "source_url", "source_bytes", "source_sha256",
           "cog_bytes", "cog_sha256", "pixels_compared", "pixels_nodata", "seconds"]


def fetch(url, tries=5):
    """Body of url, retried with backoff."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def thredds_files(catalog, years=None):
    """(url, urlPath) of every .nc dataset under a THREDDS catalog.xml.

    Follows catalogRef links (one level per year in the CCI catalogs); with
    years, only catalogRefs whose title is one of them."""
    root = ET.fromstring(fetch(catalog))
    base = catalog.split("/thredds/")[0] + "/thredds/fileServer/"
    out = []
    for d in root.iter(f"{{{NS['t']}}}dataset"):
        path = d.get("urlPath")
        if path and path.endswith(".nc"):
            out.append((base + path, path))
    for ref in root.iter(f"{{{NS['t']}}}catalogRef"):
        title = ref.get(f"{{{NS['x']}}}title") or ""
        if years and title not in years:
            continue
        href = ref.get(f"{{{NS['x']}}}href")
        out += thredds_files(urllib.parse.urljoin(catalog, href), years)
    return sorted(set(out))


def cog_path(out, url_path, var):
    """<out>/<path after cci/>/<YYYY>/<stem>_<var>.tif, the upstream folder
    (chlor_a, the product of the file) replaced by the variable."""
    parts = url_path.split("/")
    # cci/v6.0-release/geographic/monthly/chlor_a/2025/<file>.nc
    i = parts.index("cci") if "cci" in parts else -1
    rel = parts[i + 1:]
    stem = os.path.splitext(rel[-1])[0]
    rel = rel[:-3] + [var, rel[-2], f"{stem}_{var}.tif"]
    return os.path.join(out, *rel)


def download(url, dest, tries=5):
    """Download url to dest (via dest.part), checking Content-Length. Returns
    (bytes, sha256)."""
    part = dest + ".part"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
                want = r.headers.get("Content-Length")
                n = 0
                for b in iter(lambda: r.read(1 << 22), b""):
                    f.write(b)
                    h.update(b)
                    n += len(b)
            if want is not None and int(want) != n:
                raise IOError(f"{url}: got {n} bytes, Content-Length {want}")
            os.replace(part, dest)
            return n, h.hexdigest()
        except Exception:
            if os.path.exists(part):
                os.remove(part)
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def convert(task):
    """Download one netCDF and write a COG for each variable not yet done.
    Returns (manifest rows, error text or None)."""
    url, path, todo, a = task
    t0 = time.time()
    nc = os.path.join(a.tmp, os.path.basename(path))
    rows = []
    try:
        nbytes, nc_hash = download(url, nc)
        for var, out in todo:
            t1 = time.time()
            ds = gdal.Open(f'NETCDF:"{nc}":{var}')
            b = ds.GetRasterBand(1)
            if (ds.RasterXSize, ds.RasterYSize, ds.RasterCount) != (NX, NY, 1):
                raise ValueError(f"{var}: grid {ds.RasterXSize} x {ds.RasterYSize} x "
                                 f"{ds.RasterCount}, expected {NX} x {NY} x 1")
            gt = ds.GetGeoTransform()
            if max(abs(p - q) for p, q in zip(gt, GT)) > 1e-6:
                raise ValueError(f"{var}: geotransform {gt}, expected {GT}")
            if b.GetScale() not in (None, 1) or b.GetOffset() not in (None, 0):
                raise ValueError(f"{var}: scale/offset {b.GetScale()}/{b.GetOffset()} not handled")
            v = b.ReadAsArray()
            fill = b.GetNoDataValue()
            src = v.copy()
            floating = np.issubdtype(v.dtype, np.floating)
            if floating and a.fill == "nan":
                if fill is not None:
                    v[v == np.asarray(fill, v.dtype)] = np.nan
                nodata = float("nan")
            else:
                nodata = fill
            md = ds.GetMetadata()
            tags = {"SOURCE_URL": url, "SOURCE_FILE": os.path.basename(path),
                    "SOURCE_BYTES": str(nbytes), "SOURCE_SHA256": nc_hash, "SOURCE_VARIABLE": var}
            for k in ("long_name", "standard_name", "units"):
                if f"{var}#{k}" in md:
                    tags[k] = md[f"{var}#{k}"]
            for k in ("product_version", "time_coverage_start", "time_coverage_end",
                      "time_coverage_resolution", "title", "license", "creator_url"):
                if f"NC_GLOBAL#{k}" in md:
                    tags[k] = md[f"NC_GLOBAL#{k}"]
            mem = gdal.GetDriverByName("MEM").Create("", NX, NY, 1, b.DataType)
            mem.SetGeoTransform(GT)
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            mem.SetSpatialRef(srs)
            mem.SetMetadata(tags)
            mb = mem.GetRasterBand(1)
            mb.SetDescription(var)
            if "units" in tags:
                mb.SetUnitType(tags["units"])
            if nodata is not None:
                mb.SetNoDataValue(nodata)
            mb.WriteArray(v)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = out + ".part"
            gdal.GetDriverByName("COG").CreateCopy(tmp, mem, options=[
                "COMPRESS=ZSTD", f"LEVEL={a.level}", "PREDICTOR=NO", "BLOCKSIZE=512",
                "SPARSE_OK=FALSE", "OVERVIEW_RESAMPLING=AVERAGE", f"NUM_THREADS={a.threads}"])
            mem = ds = None
            got = gdal.Open(tmp)
            gb = got.GetRasterBand(1)
            w = gb.ReadAsArray()
            gnd = gb.GetNoDataValue()
            same_nd = (gnd is None and nodata is None) or (
                gnd is not None and nodata is not None and
                (gnd == nodata or (np.isnan(gnd) and np.isnan(nodata))))
            if floating:
                diff = int((~((w == v) | (np.isnan(w) & np.isnan(v)))).sum())
            else:
                diff = int((w != v).sum())
            ggt = got.GetGeoTransform()
            if diff or w.dtype != v.dtype or ggt != GT or not same_nd:
                got = None
                os.remove(tmp)
                raise ValueError(f"{var}: {diff} pixels differ from the netCDF, type {w.dtype}, "
                                 f"nodata {gnd}, geotransform {ggt}")
            if floating and a.fill == "nan" and fill is not None:
                # the NaN pixels are exactly the netCDF fill pixels
                if int((np.isnan(w) != ((src == np.asarray(fill, src.dtype)) | np.isnan(src))).sum()):
                    got = None
                    os.remove(tmp)
                    raise ValueError(f"{var}: NaN pixels do not match the netCDF fill")
            nnd = int(np.isnan(w).sum()) if floating and nodata is not None and np.isnan(nodata) \
                else (int((w == nodata).sum()) if nodata is not None else 0)
            got = None
            os.replace(tmp, out)
            rows.append([os.path.relpath(out, a.out), var, url, nbytes, nc_hash,
                         os.path.getsize(out), sha256(out), int(w.size), nnd,
                         round(time.time() - t1, 1)])
        return rows, None
    except Exception:
        return rows, f"{url}\n{traceback.format_exc()}"
    finally:
        if os.path.exists(nc):
            os.remove(nc)
        print(f"{os.path.basename(path)}: {len(rows)} of {len(todo)} COGs, "
              f"{time.time() - t0:.0f} s", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--catalog", required=True, help="THREDDS catalog.xml URL")
    p.add_argument("--var", action="append", required=True, help="netCDF variable (repeatable)")
    p.add_argument("--out", required=True, help="COG root directory")
    p.add_argument("--tmp", required=True, help="download directory")
    p.add_argument("--years", nargs="*", help="only these years (catalogRef titles)")
    p.add_argument("--done", help="file of COG names (basename or path) already uploaded; skipped")
    p.add_argument("--workers", type=int, default=4, help="files converted at once")
    p.add_argument("--threads", type=int, default=2, help="COG compression threads per worker")
    p.add_argument("--level", type=int, default=17, help="ZSTD level")
    p.add_argument("--fill", choices=("nan", "source"), default="nan",
                   help="floating point fill: NaN (default) or the netCDF _FillValue")
    p.add_argument("--limit", type=int, help="convert at most N files (smoke test)")
    p.add_argument("--list-only", action="store_true", help="print the plan, convert nothing")
    a = p.parse_args()
    a.out, a.tmp = os.path.abspath(a.out), os.path.abspath(a.tmp)
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.tmp, exist_ok=True)

    done = set()
    if a.done:
        with open(a.done) as f:
            done = {os.path.basename(l.strip()) for l in f if l.strip()}
    files = thredds_files(a.catalog, set(a.years) if a.years else None)
    if not files:
        sys.exit(f"esacci_cog: no .nc datasets under {a.catalog}")
    tasks = []
    for url, path in files:
        todo = [(v, cog_path(a.out, path, v)) for v in a.var]
        todo = [(v, o) for v, o in todo if not os.path.exists(o) and os.path.basename(o) not in done]
        if todo:
            tasks.append((url, path, todo, a))
    print(f"esacci_cog: {len(files)} netCDF files, {len(tasks)} with COGs to write", flush=True)
    if a.limit is not None:
        tasks = tasks[:a.limit]
    if a.list_only:
        for url, _, todo, _ in tasks:
            print(url, *[os.path.relpath(o, a.out) for _, o in todo], sep="\t")
        return
    if not tasks:
        return
    for f in os.listdir(a.tmp):  # downloads left by an interrupted run
        if f.endswith((".nc", ".nc.part")):
            os.remove(os.path.join(a.tmp, f))

    os.makedirs(os.path.join(a.out, "manifest"), exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = os.path.join(a.out, "manifest", f"{stamp}.tsv")
    errors = []
    n = 0
    with open(manifest, "w") as mf:
        mf.write("\t".join(COLUMNS) + "\n")
        with cf.ProcessPoolExecutor(a.workers) as ex:
            for rows, err in ex.map(convert, tasks):
                for r in rows:
                    mf.write("\t".join(str(x) for x in r) + "\n")
                mf.flush()
                n += len(rows)
                if err:
                    errors.append(err)
                    print(err, file=sys.stderr, flush=True)
    print(f"esacci_cog: {n} COGs written, {len(errors)} files failed; manifest {manifest}", flush=True)
    if not n:
        os.remove(manifest)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

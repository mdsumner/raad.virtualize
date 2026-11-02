"""verify_grist.py -- the grist catalog reads the same 2D fields as the source
granules.

For a selection of catalog rows (the first and last row of each array and
level, and the first row after a change of `source`), opens `dsn` with the
GDAL multidimensional API, resolves `index` to positions against the
indexing variables of the dsn (as grist does: ISO dates at day resolution,
numbers within a relative 1e-6, exactly one match), reads the 2D slice, and
compares it with the same field read from `source`, its index resolved
against the source's own coordinate variables. Values are compared raw (no
scale/offset), by checksum and element by element.

Usage:
  python verify_grist.py --catalog CATALOG [--vrt LOCAL_VRT] [--boundaries N|all]

CATALOG is grist/catalog.parquet: a local path, a GDAL path (/vsis3/...),
or an https URL (read through /vsicurl/).
--vrt opens this file in place of every row's dsn: the local render, for a
check before publish (the dsn names the published URL).
--boundaries: how many source changes to check per array and level (default
8, evenly spaced; every change where the source directory changes, such as
BRAN2020 to BRAN2023, is checked as well). "all" checks every change.
A source that has no multidimensional array of the catalog's name (a COG) is
read as band 1 of the classic raster API.
Exit status 1 on any mismatch or read error.
"""
import argparse
import hashlib
import io
import os
import re
import sys
import time

import numpy as np
import pyarrow.parquet as pq
from osgeo import gdal

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

UNIT_SECONDS = {"second": 1, "seconds": 1, "s": 1, "sec": 1, "secs": 1,
                "minute": 60, "minutes": 60, "min": 60, "mins": 60,
                "hour": 3600, "hours": 3600, "h": 3600, "hr": 3600, "hrs": 3600,
                "day": 86400, "days": 86400, "d": 86400}


def gdal_path(p):
    return "/vsicurl/" + p if re.match(r"^https?://", p) else p


def read_bytes(path):
    if os.path.exists(path):
        return open(path, "rb").read()
    path = gdal_path(path)
    f = gdal.VSIFOpenL(path, "rb")
    if f is None:
        raise RuntimeError(f"cannot open {path}")
    try:
        gdal.VSIFSeekL(f, 0, 2)
        n = gdal.VSIFTellL(f)
        gdal.VSIFSeekL(f, 0, 0)
        return gdal.VSIFReadL(1, n, f)
    finally:
        gdal.VSIFCloseL(f)


def parse_index(s):
    out = {}
    for kv in s.split(","):
        k, v = kv.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cf_days(values, units):
    """CF time values -> numpy datetime64[D] (day of each step)."""
    m = re.match(r"^\s*(\w+)\s+since\s+(.+?)\s*$", units or "")
    if not m or m.group(1).lower() not in UNIT_SECONDS:
        raise ValueError(f"time units not handled: {units!r}")
    origin = m.group(2).replace("T", " ").rstrip("Z").strip()
    date, _, clock = origin.partition(" ")
    y, mo, d = (int(x) for x in date.split("-"))
    hh, mm, ss = ([float(x) for x in clock.split(":")] + [0, 0, 0])[:3] if clock else (0, 0, 0)
    o = (np.datetime64(f"{y:04d}-{mo:02d}-{d:02d}", "s") - np.datetime64("1970-01-01", "s")).astype(np.int64)
    o = o + hh * 3600 + mm * 60 + ss
    secs = o + np.asarray(values, dtype="f8") * UNIT_SECONDS[m.group(1).lower()]
    return np.floor(secs / 86400).astype("i8").astype("datetime64[D]")


def resolve(arr, index):
    """Positions of `index` (dim -> value text) on a GDAL MDArray: a start and
    count per dimension, the dimensions not in `index` read whole."""
    start, count, used = [], [], set()
    for dim in arr.GetDimensions():
        name = dim.GetName()
        if name not in index:
            start.append(0)
            count.append(dim.GetSize())
            continue
        iv = dim.GetIndexingVariable()
        if iv is None:
            raise ValueError(f"dimension {name} has no indexing variable")
        vals = np.asarray(iv.ReadAsArray()).ravel()
        want = index[name]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", want):
            unit = iv.GetUnit()
            if not unit:
                at = iv.GetAttribute("units")
                unit = at.Read() if at is not None else ""
            hit = np.nonzero(cf_days(vals, unit) == np.datetime64(want, "D"))[0]
        else:
            w = float(want)
            hit = np.nonzero(np.abs(vals.astype("f8") - w) <= 1e-6 * max(abs(w), 1e-12))[0]
        if len(hit) != 1:
            raise ValueError(f"{name}={want} matches {len(hit)} values")
        start.append(int(hit[0]))
        count.append(1)
        used.add(name)
    miss = set(index) - used
    if miss:
        raise ValueError(f"index names dimensions the array lacks: {sorted(miss)}")
    if len(start) - len(used) != 2:
        raise ValueError(f"{len(start) - len(used)} dimensions left after the index, not 2")
    return start, count, tuple(i for i, d in enumerate(arr.GetDimensions()) if d.GetName() in used)


def read_mdim(ds_path, array, index, cache):
    if ds_path not in cache:
        if len(cache) > 4:  # sources change along the catalog: keep a few open
            cache.clear()
        cache[ds_path] = gdal.OpenEx(ds_path, gdal.OF_MULTIDIM_RASTER)
    arr = cache[ds_path].GetRootGroup().OpenMDArray(array)
    if arr is None:
        raise ValueError(f"no array {array} in {ds_path}")
    start, count, axes = resolve(arr, index)
    v = np.asarray(arr.ReadAsArray(array_start_idx=start, count=count))
    return np.squeeze(v, axis=axes) if axes else v


def read_source(src, array, index, cache):
    try:
        return read_mdim(src, array, index, cache)
    except Exception as e:
        ds = gdal.Open(src)  # a classic raster (COG): band 1, no index
        if ds is None:
            raise e
        return ds.GetRasterBand(1).ReadAsArray()


def checksum(v):
    v = np.ascontiguousarray(v)
    return hashlib.sha256(v.astype(v.dtype.newbyteorder("<")).tobytes()).hexdigest()[:16]


def select(rows, nb):
    """Row numbers to check: per (array, level) the first and last row and
    the first row after each change of source (all of them, or nb evenly
    spaced plus every change of source directory)."""
    groups = {}
    for i, r in enumerate(rows):
        lv = ",".join(kv for kv in r["index"].split(",") if not re.search(r"=\d{4}-\d{2}-\d{2}$", kv))
        groups.setdefault((r["array"], lv), []).append(i)
    pick = []
    for _, ix in groups.items():
        ix = sorted(ix, key=lambda i: rows[i]["date"])
        sel = {ix[0], ix[-1]}
        ch = [ix[k] for k in range(1, len(ix)) if rows[ix[k]]["source"] != rows[ix[k - 1]]["source"]]
        if nb == "all" or len(ch) <= int(nb):
            sel.update(ch)
        else:
            n = int(nb)
            if n > 0:
                sel.update(ch[int(round(j))] for j in np.linspace(0, len(ch) - 1, n))
            sel.update(i for i in ch
                       if os.path.dirname(rows[i]["source"]) != os.path.dirname(rows[ix[ix.index(i) - 1]]["source"]))
        pick.extend(sorted(sel, key=lambda i: rows[i]["date"]))
    return pick


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--catalog", required=True)
    p.add_argument("--vrt", help="open this VRT in place of each row's dsn")
    p.add_argument("--boundaries", default="8", help="source changes to check per array and level, or all")
    a = p.parse_args()

    t = pq.read_table(io.BytesIO(read_bytes(a.catalog)))
    md = {k.decode(): v.decode() for k, v in (t.schema.metadata or {}).items()}
    rows = t.to_pylist()
    need = {"date", "dsn", "array", "index", "source"}
    if not need <= set(t.column_names):
        print("verify-grist: catalog lacks columns", sorted(need - set(t.column_names)))
        sys.exit(1)
    print(f"grist catalog {a.catalog}: {len(rows)} rows, contract {md.get('contract')}, "
          f"dataset {md.get('rv:dataset')}")
    if a.vrt:
        print(f"  reading {a.vrt} in place of dsn {rows[0]['dsn']}")
    bad = 0
    vcache, scache = {}, {}
    for i in select(rows, a.boundaries):
        r = rows[i]
        index = parse_index(r["index"])
        dsn = a.vrt or r["dsn"]
        res = {}
        for k, f, path in (("dsn", read_mdim, dsn), ("source", read_source, r["source"].split(";")[0])):
            t0 = time.time()
            try:
                v = f(path, r["array"], index, vcache if k == "dsn" else scache)
                res[k] = (v, checksum(v), time.time() - t0)
            except Exception as e:
                res[k] = (None, f"ERROR {e}"[:70], time.time() - t0)
        (v1, h1, s1), (v2, h2, s2) = res["dsn"], res["source"]
        same = v1 is not None and v2 is not None and v1.shape == v2.shape and \
            v1.dtype == v2.dtype and h1 == h2 and np.array_equal(v1, v2, equal_nan=v1.dtype.kind == "f")
        bad += not same
        shape = "x".join(map(str, v1.shape)) if v1 is not None else "-"
        print(f"\n{r['date']} {r['array']} {r['index']}  ({shape})\n"
              f"  dsn     {h1:18s} {s1:6.2f} s\n"
              f"  source  {h2:18s} {s2:6.2f} s  {os.path.basename(r['source'])}\n"
              f"  {'SAME' if same else 'DIFFERENT'}")
    print("\nverify-grist:", "all rows agree" if not bad else f"{bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

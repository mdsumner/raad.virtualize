"""verify.py -- step 6: every rendered form reads the same values as GDAL on
the sources.

Readers, all raw (no scale/offset applied):
  plan      GDAL multidim on the `gdal mdim mosaic` VRT (reads the sources:
            the oracle)
  vrt       GDAL multidim on the VRT rendered from the store (R/render.R)
            (both VRT readers keep only the sources a window touches; see
            windowed_vrt_reader)
  kerchunk  GDAL on ZARR:"/vsikerchunk_parquet_ref/<dir>" (kerchunk Parquet)
  kerchunk-py  fsspec + zarr-python on the same Parquet, only when an array
            carries an imagecodecs filter (TIFF predictor), which GDAL's Zarr
            driver cannot decode; local OUT_DIR only
  icechunk  zarr-python on the Icechunk repository (virtual refs)

Usage:
  python verify.py --plan plan.vrt --out OUT_DIR [--window ARRAY:START:COUNT ...]
                   [--published /vsis3/BUCKET/PREFIX]

OUT_DIR is the render directory (flat/, mdim.vrt, kerchunk/, icechunk/).
With --published, vrt, kerchunk and icechunk are read from that copy of
OUT_DIR on S3 (as written by `run.sh ... publish`) instead; the endpoint and
credentials come from the usual GDAL / AWS env (AWS_S3_ENDPOINT, AWS_HTTPS,
AWS_VIRTUAL_HOSTING, AWS_ACCESS_KEY_ID, ...). OUT_DIR/flat is still read
locally for the window list.
START and COUNT are comma lists over the array's dims. Without --window, per
referenced array: the first chunk; one row across every chunk of the last dim
at the last step of the first dim (middle of the others); --sample random
present chunks (default 4) and one absent chunk if the table has any.

Also checks the CF attributes the earlier BRAN indexes got wrong:
scale_factor and fill value against GDAL on the plan. Exit status 1 on any
mismatch.
"""
import argparse
import copy
import hashlib
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")


def gdal_reader(path):
    ds = gdal.OpenEx(path, gdal.OF_MULTIDIM_RASTER)
    rg = ds.GetRootGroup()

    def read(name, start, count):
        return rg.OpenMDArray(name).ReadAsArray(array_start_idx=start, count=count)
    read.group = rg
    return read


def read_text(path):
    f = gdal.VSIFOpenL(path, "rb")
    try:
        gdal.VSIFSeekL(f, 0, 2)
        n = gdal.VSIFTellL(f)
        gdal.VSIFSeekL(f, 0, 0)
        return gdal.VSIFReadL(1, n, f).decode()
    finally:
        gdal.VSIFCloseL(f)


def source_extent(src, shape):
    """(offset, count) of a VRT <Source> in the destination array, or None
    when the count is not written in the source element."""
    off = [int(x) for x in src.find("DestSlab").get("offset").split(",")]
    if src.find("SourceBand") is not None:
        # a raster band given a leading length-1 axis (SourceTranspose -1,0,1)
        return off, [1] + list(shape[1:])
    ss = src.find("SourceSlab")
    if ss is None or not ss.get("count"):
        return None
    return off, [int(x) for x in ss.get("count").split(",")]


def windowed_vrt_reader(path, many=64):
    """GDAL multidim on a VRT, reading each window through a copy of the VRT
    that keeps only the <Source> elements the window touches.

    GDAL's multidim VRT opens every source of an array, in order, on each read
    (for /vsicurl/ sources a HEAD and a 16 KB header GET each, about 1 s per
    source to us-west-2), so a window read over 8909 daily COGs takes hours.
    The subset VRT reads the same bytes through the same source entries.
    Arrays with fewer than `many` sources are read through the VRT as is.
    """
    text = read_text(path)
    root = ET.fromstring(text)
    base = os.path.dirname(path)
    for fn in root.iter("SourceFilename"):
        if fn.get("relativeToVRT") == "1":
            fn.text = base + "/" + fn.text
            del fn.attrib["relativeToVRT"]
    group = root.find("Group")
    dims = {d.get("name"): int(d.get("size")) for d in group.findall("Dimension")}
    arrays = {a.get("name"): a for a in group.findall("Array")}
    tag = f"/vsimem/verify_{os.getpid()}_{abs(hash(path))}"

    # a sourceless copy for the attribute checks (scale, nodata)
    bare = ET.fromstring(ET.tostring(root))
    for a in bare.find("Group").findall("Array"):
        for s in a.findall("Source"):
            a.remove(s)
    gdal.FileFromMemBuffer(tag + "_bare.vrt", ET.tostring(bare))
    header = gdal_reader(tag + "_bare.vrt")

    def read(name, start, count):
        arr = arrays[name]
        srcs = arr.findall("Source")
        if len(srcs) < many:
            return gdal_reader(path)(name, start, count)
        shape = [dims[d.get("ref")] for d in arr.findall("DimensionRef")]
        drop = set()
        for i, src in enumerate(srcs):
            ext = source_extent(src, shape)
            if ext is not None and not all(o < st + c and st < o + n
                                           for o, n, st, c in zip(*ext, start, count)):
                drop.add(i)
        sub = copy.deepcopy(root)
        sub_arr = [x for x in sub.find("Group").findall("Array") if x.get("name") == name][0]
        for i, src in enumerate(sub_arr.findall("Source")):
            if i in drop:
                sub_arr.remove(src)
        gdal.FileFromMemBuffer(tag + ".vrt", ET.tostring(sub))
        try:
            return gdal_reader(tag + ".vrt")(name, start, count)
        finally:
            gdal.Unlink(tag + ".vrt")
    read.group = header.group
    return read


def uses_imagecodecs(doc):
    return any(f.get("id", "").startswith("imagecodecs_")
               for r in doc["arrays"] for f in ((r.get("codec") or {}).get("filters") or []))


def kerchunk_py_reader(path):
    import fsspec
    import imagecodecs.numcodecs
    import zarr
    imagecodecs.numcodecs.register_codecs(verbose=False)
    # asynchronous throughout, as zarr-python 3 stores expect: the reference
    # filesystem and its target (inferred from the first ref, https or a local
    # path) must agree, or fsspec refuses the pair
    fs = fsspec.filesystem("reference", fo=path, lazy=True, asynchronous=True,
                           skip_instance_cache=True, remote_options={"asynchronous": True})
    g = zarr.open_group(zarr.storage.FsspecStore(fs, read_only=True, path=""), mode="r",
                        zarr_format=2)

    def read(name, start, count):
        return g[name][tuple(slice(s, s + c) for s, c in zip(start, count))]
    read.attrs = lambda name: dict(g[name].attrs)
    return read


def s3_storage(vsis3):
    """Icechunk storage for a /vsis3/bucket/prefix path, using GDAL's S3 env."""
    import icechunk
    bucket, _, prefix = vsis3[len("/vsis3/"):].partition("/")
    ep = os.environ.get("AWS_S3_ENDPOINT")
    if ep and "://" not in ep:
        ep = ("http://" if os.environ.get("AWS_HTTPS", "YES").upper() in ("NO", "FALSE", "OFF") else "https://") + ep
    return icechunk.s3_storage(bucket=bucket, prefix=prefix.rstrip("/"), endpoint_url=ep,
                               region=os.environ.get("AWS_REGION", "us-east-1"),
                               force_path_style=os.environ.get("AWS_VIRTUAL_HOSTING", "TRUE").upper()
                               in ("NO", "FALSE", "OFF"),
                               allow_http=bool(ep and ep.startswith("http://")), from_env=True)


def icechunk_reader(repo):
    import icechunk
    import zarr
    try:  # imagecodecs_delta (TIFF PREDICTOR=2) and friends, if installed
        import imagecodecs.zarr
        imagecodecs.zarr.register_codecs(verbose=False)
    except ImportError:
        pass
    storage = s3_storage(repo) if repo.startswith("/vsis3/") else icechunk.local_filesystem_storage(repo)
    cfg = icechunk.Repository.fetch_config(storage)
    auth = {c.url_prefix: (icechunk.s3_anonymous_credentials() if c.url_prefix.startswith("s3://")
                           else icechunk.credentials.HttpAccess if c.url_prefix.startswith("http")
                           else icechunk.credentials.LocalFileSystemAccess)
            for c in cfg.virtual_chunk_containers.values()}
    repo = icechunk.Repository.open(storage, authorize_virtual_chunk_access=auth)
    g = zarr.open_group(repo.readonly_session("main").store, mode="r")

    def read(name, start, count):
        # THREDDS resets connections when zarr opens many at once (12 for a
        # row of chunks), every time, so retry with less concurrency.
        sl = tuple(slice(s, s + c) for s, c in zip(start, count))
        for n in (None, 4, 2, 1):
            try:
                if n is None:
                    return g[name][sl]
                with zarr.config.set({"async.concurrency": n}):
                    v = g[name][sl]
                print(f"  icechunk: read ok with zarr async.concurrency={n}")
                return v
            except Exception as e:
                if n == 1 or "HTTP" not in str(e):
                    raise
                print(f"  icechunk: {str(e).splitlines()[0][:70]}; concurrency -> {4 if n is None else n // 2}")
                time.sleep(1)
    read.attrs = lambda name: dict(g[name].attrs)
    return read


def default_windows(doc, flat, nsample):
    """First chunk, a row across the last dim, and `nsample` random chunks
    per array (present ones, plus one absent one when the table has any)."""
    import pyarrow.parquet as pq
    rng = np.random.default_rng(42)
    out = []
    for r in doc["arrays"]:
        if r["storage"] != "referenced":
            continue
        sh, ch = r["shape"], r["chunks"]
        out.append((r["array"], [0] * len(sh), [min(c, s) for c, s in zip(ch, sh)]))
        start = [sh[0] - 1] + [s // 2 for s in sh[1:-1]] + [0]
        out.append((r["array"], start, [1] * (len(sh) - 1) + [sh[-1]]))
        t = pq.read_table(os.path.join(flat, f"refs_{r['array']}.parquet"),
                          columns=[f"dim_{i}" for i in range(len(sh))] + ["present"]).to_pandas()
        picks = []
        pres, absn = t[t.present == 1], t[t.present == 0]
        if len(pres):
            picks += [pres.iloc[i] for i in rng.choice(len(pres), min(nsample, len(pres)), replace=False)]
        if len(absn):
            picks.append(absn.iloc[int(rng.integers(len(absn)))])
        for row in picks:
            st = [int(row[f"dim_{i}"]) * c for i, c in enumerate(ch)]
            out.append((r["array"], st, [min(c, s - o) for c, s, o in zip(ch, sh, st)]))
    return out


def absent_chunks(doc, flat):
    """Per array, the set of chunk index tuples the table marks absent."""
    import pyarrow.parquet as pq
    out = {}
    for r in doc["arrays"]:
        if r["storage"] != "referenced":
            continue
        cols = [f"dim_{i}" for i in range(len(r["shape"]))]
        t = pq.read_table(os.path.join(flat, f"refs_{r['array']}.parquet"),
                          columns=cols + ["present"]).to_pandas()
        out[r["array"]] = set(map(tuple, t.loc[t.present == 0, cols].to_numpy().tolist()))
    return out


def touches_absent(absent, chunks, start, count):
    lo = [s // c for s, c in zip(start, chunks)]
    hi = [(s + n - 1) // c for s, n, c in zip(start, count, chunks)]
    return any(all(l <= i <= h for i, l, h in zip(ix, lo, hi)) for ix in absent)


def source_scale(plan, name):
    """scale_factor of NAME in the first source listed beside the plan."""
    lst = os.path.join(os.path.dirname(os.path.abspath(plan)), "sources.txt")
    src = open(lst).readline().strip()
    m = gdal.OpenEx(src, gdal.OF_MULTIDIM_RASTER).GetRootGroup().OpenMDArray(name)
    if m.GetScale() is not None:
        return m.GetScale()
    try:
        at = m.GetAttribute("scale_factor")
    except RuntimeError:  # unpacked array (e.g. BRAN w); raised under UseExceptions
        at = None
    return at.ReadAsDouble() if at is not None else 1.0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--window", action="append", default=[])
    p.add_argument("--skip", action="append", default=[], help="reader to skip")
    p.add_argument("--sample", type=int, default=4, help="random chunks per array")
    p.add_argument("--published", help="read the forms from this /vsis3/ copy of OUT_DIR")
    a = p.parse_args()

    doc = json.load(open(os.path.join(a.out, "flat", "arrays.json")))
    windows = default_windows(doc, os.path.join(a.out, "flat"), a.sample) if not a.window else [
        (w.split(":")[0], [int(x) for x in w.split(":")[1].split(",")],
         [int(x) for x in w.split(":")[2].split(",")]) for w in a.window]

    base = a.published.rstrip("/") if a.published else os.path.abspath(a.out)
    readers = {"plan": lambda: windowed_vrt_reader(a.plan),
               "vrt": lambda: windowed_vrt_reader(base + "/mdim.vrt"),
               "kerchunk": lambda: gdal_reader('ZARR:"/vsikerchunk_parquet_ref/{' + base + '/kerchunk}"'),
               "icechunk": lambda: icechunk_reader(base + "/icechunk")}
    predictor = uses_imagecodecs(doc)
    if predictor and not a.published:
        readers["kerchunk-py"] = lambda: kerchunk_py_reader(base + "/kerchunk")
    if a.published:
        print("reading vrt, kerchunk, icechunk from", base)
    opened = {}
    for k, f in readers.items():
        if k in a.skip:
            continue
        try:
            opened[k] = f()
        except Exception as e:  # report and carry on with the other readers
            print(f"{k}: cannot open ({e})")
    absent = absent_chunks(doc, os.path.join(a.out, "flat"))
    chunks = {r["array"]: r["chunks"] for r in doc["arrays"]}
    bad = known = 0
    errors = []
    for name, start, count in windows:
        res = {}
        for k, read in opened.items():
            t0 = time.time()
            try:
                v = np.asarray(read(name, start, count))
                res[k] = (hashlib.sha256(np.ascontiguousarray(v).astype(v.dtype.newbyteorder("<")).tobytes())
                          .hexdigest()[:16], v.dtype.str, time.time() - t0, v)
            except Exception as e:
                res[k] = (f"ERROR {e}"[:60], "", time.time() - t0, None)
                errors.append(f"{k} {name} {start} {count}: {e}")
        ref = res.get("plan")
        print(f"\n{name} start={start} count={count}")
        for k, (h, dt, sec, v) in res.items():
            same = ref is not None and v is not None and ref[3] is not None and \
                v.shape == ref[3].shape and np.array_equal(v.astype("f8"), ref[3].astype("f8"))
            flag = "oracle" if k == "plan" else ("SAME" if same else "DIFFERENT")
            if k == "kerchunk" and v is None and predictor:
                # imagecodecs_delta (TIFF PREDICTOR=2) is not a GDAL Zarr filter
                flag = "KNOWN GDAL LIMIT (imagecodecs filter)"
                known += 1
            elif k == "kerchunk" and v is None and touches_absent(absent.get(name, ()), chunks[name], start, count):
                # GDAL 3.13 /vsikerchunk_parquet_ref treats a row with null
                # path and null raw (fsspec's "no such chunk") as a path to
                # open, instead of a missing chunk read as fill ("Too large
                # tile" locally, "Could not read tile" over /vsis3/).
                flag = "KNOWN GDAL BUG (absent chunk)"
                known += 1
            bad += flag == "DIFFERENT"
            print(f"  {k:11s} {h:18s} {dt:4s} {sec:6.2f} s  {flag}")

    if "plan" in opened:
        print("\nscale_factor and fill (GDAL on the plan vs the store and each form)")
        for r in doc["arrays"]:
            if r["storage"] != "referenced":
                continue
            g = opened["plan"].group.OpenMDArray(r["array"])
            sf = g.GetScale()
            if sf is None:
                # The HDF5 driver does not lift scale_factor to GetScale (the
                # netCDF driver does), and the mosaic VRT then keeps it as a
                # text attribute at reduced precision. Read it from the first
                # source instead, as the harvest does.
                sf = source_scale(a.plan, r["array"])
            want = (sf, g.GetNoDataValue())
            got = {"store": ((r["attrs"] or {}).get("scale_factor", 1.0),
                             None if r.get("fill") is None else float(r["fill"]))}
            for k, rd in opened.items():
                if k == "plan":
                    continue
                if hasattr(rd, "group"):
                    try:
                        m = rd.group.OpenMDArray(r["array"])
                    except RuntimeError as e:
                        print(f"    {k:11s} cannot open: {e}")
                        continue
                    got[k] = (m.GetScale() if m.GetScale() is not None else 1.0, m.GetNoDataValue())
                elif hasattr(rd, "attrs"):
                    at = rd.attrs(r["array"])
                    got[k] = (at.get("scale_factor", 1.0), at.get("_FillValue"))
            print(f"  {r['array']}: GDAL scale {want[0]!r} fill {want[1]!r}")
            for k, (sf, nd) in got.items():
                ok = sf == want[0] and (nd == want[1] or (nd is None and want[1] is None))
                bad += not ok
                print(f"    {k:11s} scale {sf!r} fill {nd!r} {'ok' if ok else 'MISMATCH'}")
    if errors:
        print("\nread errors (full text)")
        for e in errors:
            print("  " + e)
    print("\nverify:", "all readers agree" if not bad else f"{bad} mismatches",
          f"({known} GDAL kerchunk reads hit a known bug or limit)" if known else "")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

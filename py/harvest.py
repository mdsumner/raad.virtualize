"""harvest.py -- byte-reference harvest of every source in a mosaic plan.

Step 2 of the end-to-end example (README.md). Reads the `gdal mdim mosaic`
VRT (the plan), and for every distinct source of the requested arrays lists
the byte range of every chunk of the source's own chunk grid. One row per
chunk, keyed on the chunk's position WITHIN the source (the physical layer
of mdim-refs/0.2): source, dim_0..dim_{n-1}, present, offset, size, info,
data.

Engines (--engine):
  gdal  stock GDAL MDArray.GetRawBlockInfo() per chunk (GDAL >= 3.12), any
        driver that implements it. For netCDF4/HDF5 it is slow (about 2 ms
        a chunk, the cost grows with chunks per file) and wrong for files
        with unwritten chunks (see walk()); such files are rescanned with h5py.
  h5py  one pass over the HDF5 chunk index (H5Dchunk_iter), for netCDF4 and
        HDF5 sources: local paths, or /vsicurl/ and https URLs through fsspec.
  auto  (default) h5py for local netCDF4/HDF5 sources when h5py is
        installed, gdal otherwise (remote: GDAL fetched far fewer bytes from
        THREDDS). GDAL still supplies the metadata and codec info.
  HARVEST_BLOCK_SIZE (env, default 65536): fsspec read block for remote h5py.

Output layout (--out), one fragment per (source, array), so a long run is
memory-bounded and restartable (a source whose fragments all exist is
skipped; fragments are written to a temp name and renamed):

  sources/<key>.json            {source, size, mtime}       (VSIStatL)
  chunks_<array>/<key>.parquet  source, dim_*, present, offset, size, info, data
  arrays.json                   physical description of every array in the
                                first source (dims, shape, chunks, dtype,
                                nodata, scale, offset, unit, attrs, scanned);
                                the CF attrs the mosaic VRT drops come from here

<key> is the SHA-1 of the source string. Same row shape and arrays.json as
byteref/python/blockinfo_scan.py, so R/mdimrefs.R ingests either.

Usage:
  python harvest.py --plan plan.vrt --out scan/ --array temp [--workers 8] [--engine auto]

Workers are processes, not threads: the netCDF and HDF5 drivers hold a
global lock, so threads do not overlap.
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed

import pyarrow as pa
import pyarrow.parquet as pq
from osgeo import gdal

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

NUMPY = {gdal.GDT_Byte: "u1", gdal.GDT_Int8: "i1", gdal.GDT_UInt16: "u2",
         gdal.GDT_Int16: "i2", gdal.GDT_UInt32: "u4", gdal.GDT_Int32: "i4",
         gdal.GDT_UInt64: "u8", gdal.GDT_Int64: "i8", gdal.GDT_Float32: "f4",
         gdal.GDT_Float64: "f8"}


def key_of(source):
    return hashlib.sha1(source.encode()).hexdigest()


def plan_sources(vrt, arrays):
    """Distinct sources of `arrays` in plan order, as GDAL opens them."""
    root = ET.parse(vrt).getroot()
    base = os.path.dirname(os.path.abspath(vrt))
    out = []
    for arr in root.findall("Group/Array"):
        if arr.get("name") not in arrays:
            continue
        for s in arr.findall("Source/SourceFilename"):
            f = s.text
            if not (f.startswith("/") or "://" in f):
                f = os.path.join(base, f)
            if f not in out:
                out.append(f)
    return out


def numpy_dtype(arr, info):
    code = NUMPY[arr.GetDataType().GetNumericDataType()]
    if code.endswith("1"):
        return "|" + code
    return (">" if "ENDIANNESS=BIG" in (info or []) else "<") + code


def chunk_grid(arr):
    shape = [d.GetSize() for d in arr.GetDimensions()]
    block = [b if b > 0 else s for b, s in zip(arr.GetBlockSize(), shape)]
    return shape, block, [math.ceil(s / b) for s, b in zip(shape, block)]


def walk(arr):
    """Yield (coords, present, offset, size, info, data) per chunk.

    GDAL 3.13 (frmts/hdf5/hdf5multidim.cpp) turns block coordinates into a
    C-order linear index and calls H5Dget_chunk_info(index). HDF5 counts that
    index over ALLOCATED chunks only, so in a file where any chunk was never
    written every later chunk gets its neighbour's offset, and the last ones
    raise. The answers are right only when every chunk is allocated. So a
    source where any call raises is sparse, and is rescanned by coordinate
    (H5Dget_chunk_info_by_coord, through h5py) in walk_h5py()."""
    _, _, counts = chunk_grid(arr)
    rows = []
    for c in itertools.product(*[range(n) for n in counts]):
        try:
            bi = arr.GetRawBlockInfo(list(c))
        except RuntimeError as e:
            raise SparseSource(str(e))
        if bi is None:
            rows.append((c, 0, None, None, None, None))
            continue
        info = list(bi.GetInfo() or [])
        inline = bi.GetInlineData()
        if bi.GetFilename() and bi.GetSize():
            rows.append((c, 1, bi.GetOffset(), bi.GetSize(), info, None))
        elif inline is not None:
            rows.append((c, 1, None, len(inline), info, bytes(inline)))
        else:
            rows.append((c, 0, None, None, info, None))
    return rows


class SparseSource(Exception):
    pass


def have_h5py():
    try:
        import h5py  # noqa: F401
        return True
    except ImportError:
        return False


def h5_open(source):
    """h5py File for a local path, or for /vsicurl/ and http(s) URLs through
    fsspec (needs fsspec and aiohttp)."""
    import h5py
    if source.startswith("/vsicurl/"):
        source = source[len("/vsicurl/"):]
    if "://" in source:
        import fsspec
        bs = int(os.environ.get("HARVEST_BLOCK_SIZE", 65536))
        f = fsspec.open(source, "rb", block_size=bs, cache_type="blockcache").open()
        return h5py.File(f, "r")
    if source.startswith("/vsi"):
        sys.exit(f"{source}: the h5py engine takes local paths and http(s) URLs only")
    return h5py.File(source, "r")


def walk_h5py(source, arr):
    """Rows for a netCDF4/HDF5 source from one pass over its chunk index
    (H5Dchunk_iter through h5py, HDF5 >= 1.14): every allocated chunk with
    its coordinate, so unallocated chunks are absent rows, and it is three
    orders of magnitude faster than GetRawBlockInfo per chunk (0.1 s against
    200 s for 95k chunks, local file). The codec info is GDAL's for the
    array; a chunk whose filter mask is not 0 (a filter skipped) gets a
    distinct info so the one-codec rule in collate stops the array."""
    first = list(arr.GetRawBlockInfo([0] * arr.GetDimensionCount()).GetInfo() or [])
    shape, block, counts = chunk_grid(arr)
    found = {}
    with h5_open(source) as f:
        d = f[arr.GetFullName()]
        if d.chunks is None or list(d.chunks) != block:
            sys.exit(f"{source}: h5py chunks {d.chunks} differ from GDAL blocks {block}")
        d.id.chunk_iter(lambda ci: found.__setitem__(
            tuple(o // b for o, b in zip(ci.chunk_offset, block)),
            (ci.byte_offset, ci.size, ci.filter_mask)))
    rows = []
    for c in itertools.product(*[range(n) for n in counts]):
        hit = found.get(c)
        if hit is None:
            rows.append((c, 0, None, None, None, None))
        else:
            off, size, mask = hit
            info = first if mask == 0 else first + [f"FILTER_MASK={mask}"]
            rows.append((c, 1, off, size, info, None))
    return rows


def cf_packing(arr):
    """scale_factor, add_offset and fill of an array. The netCDF driver lifts
    them to GetScale/GetOffset; the HDF5 driver leaves them as attributes, so
    read those too. gdal mdim mosaic checks only nodata across sources, and
    takes scale and offset from the first, so collate compares these."""
    at = {a.GetName(): a.Read() for a in arr.GetAttributes()}
    one = lambda v: v[0] if isinstance(v, (list, tuple)) and len(v) == 1 else v
    sc = arr.GetScale() if arr.GetScale() is not None else one(at.get("scale_factor"))
    of = arr.GetOffset() if arr.GetOffset() is not None else one(at.get("add_offset"))
    return {"scale": sc, "offset": of, "nodata": arr.GetNoDataValue()}


def describe(arr, info):
    shape, block, _ = chunk_grid(arr)
    attrs = {}
    for a in arr.GetAttributes():
        v = a.Read()
        attrs[a.GetName()] = v[0] if isinstance(v, (list, tuple)) and len(v) == 1 else v
    return {
        "dims": [d.GetName() for d in arr.GetDimensions()],
        "shape": shape, "chunks": block, "dtype": numpy_dtype(arr, info),
        "nodata": arr.GetNoDataValue(), "scale": arr.GetScale(),
        "offset": arr.GetOffset(), "unit": arr.GetUnit() or None,
        "attrs": attrs, "info": info,
    }


def write_atomic(path, writer):
    tmp = path + ".tmp"
    writer(tmp)
    os.replace(tmp, path)


def scan_source(source, arrays, out, want_meta, engine="auto", tries=4):
    """scan_source_once() with retries: remote opens fail now and then."""
    for i in range(tries):
        try:
            return scan_source_once(source, arrays, out, want_meta, engine)
        except RuntimeError as e:
            if i == tries - 1:
                raise
            print(f"  {source}: {e}; retry in {2 ** (i + 1)} s", file=sys.stderr)
            time.sleep(2 ** (i + 1))


def scan_source_once(source, arrays, out, want_meta, engine):
    """Scan one source; returns (source, nrows, seconds, arrays meta or None)."""
    t0 = time.time()
    k = key_of(source)
    ds = gdal.OpenEx(source, gdal.OF_MULTIDIM_RASTER)
    rg = ds.GetRootGroup()
    meta, n, sparse, packing = {}, 0, [], {}
    for nm in arrays:
        arr = rg.OpenMDArray(nm)
        rank = arr.GetDimensionCount()
        cols = {"source": []}
        cols.update({f"dim_{i}": [] for i in range(rank)})
        cols.update(present=[], offset=[], size=[], info=[], data=[])
        first = None
        packing[nm] = cf_packing(arr)
        h5 = ds.GetDriver().ShortName in ("netCDF", "HDF5")
        remote = source.startswith("/vsi") or "://" in source
        # auto: h5py for local netCDF4/HDF5 (0.1 s a file); GDAL for remote
        # ones, which on THREDDS (BRAN month, 2026-10-21) fetched ~35 MB in
        # ~1.7k GETs against h5py's 115 MB (64 KB blocks) or 500+ MB (1 MB).
        if engine == "h5py" or (engine == "auto" and h5 and not remote and have_h5py()):
            used = "h5py"
            rows = walk_h5py(source, arr)
        else:
            used = "gdal"
            try:
                rows = walk(arr)
            except SparseSource:
                if not h5:
                    raise
                rows = walk_h5py(source, arr)
                sparse.append(nm)
        for c, present, off, size, info, data in rows:
            if first is None and present:
                first = info
            cols["source"].append(source)
            for i in range(rank):
                cols[f"dim_{i}"].append(c[i])
            cols["present"].append(present)
            cols["offset"].append(off)
            cols["size"].append(size)
            cols["info"].append("; ".join(info) if info else None)
            cols["data"].append(data)
        types = {"source": pa.string(), "present": pa.int8(), "offset": pa.int64(),
                 "size": pa.int64(), "info": pa.string(), "data": pa.binary()}
        tbl = pa.table({c: pa.array(v, types.get(c, pa.int64())) for c, v in cols.items()})
        write_atomic(os.path.join(out, f"chunks_{nm}", f"{k}.parquet"),
                     lambda p: pq.write_table(tbl, p, compression="zstd"))
        n += tbl.num_rows
        if want_meta:
            meta[nm] = describe(arr, first or [])
            meta[nm]["scanned"] = True
    if want_meta:
        for nm in rg.GetMDArrayNames():
            if nm not in meta:
                a = rg.OpenMDArray(nm)
                meta[nm] = describe(a, [])
                meta[nm]["scanned"] = False
    st = gdal.VSIStatL(source)
    write_atomic(os.path.join(out, "sources", f"{k}.json"), lambda p: json.dump(
        {"source": source, "size": st.size if st else None,
         "mtime": st.mtime if st else None, "driver": ds.GetDriver().ShortName,
         "packing": packing}, open(p, "w")))
    print(f"  {os.path.basename(source)}: engine {used}", file=sys.stderr)
    if sparse:
        print(f"  {source}: sparse ({', '.join(sparse)}), rescanned with h5py",
              file=sys.stderr)
    return source, n, time.time() - t0, meta if want_meta else None


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--plan", required=True, help="gdal mdim mosaic VRT")
    p.add_argument("--out", required=True)
    p.add_argument("--array", action="append", required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0, help="scan only the first N sources")
    p.add_argument("--engine", choices=["auto", "gdal", "h5py"], default="auto",
                   help="auto: h5py chunk_iter for netCDF4/HDF5 when h5py is installed, "
                        "else GDAL GetRawBlockInfo (with an h5py rescan of sparse files)")
    a = p.parse_args()

    for d in ["sources"] + [f"chunks_{nm}" for nm in a.array]:
        os.makedirs(os.path.join(a.out, d), exist_ok=True)
    srcs = plan_sources(a.plan, a.array)
    if a.limit:
        srcs = srcs[:a.limit]
    have_meta = os.path.exists(os.path.join(a.out, "arrays.json"))

    def done(s):
        k = key_of(s)
        return os.path.exists(os.path.join(a.out, "sources", f"{k}.json")) and all(
            os.path.exists(os.path.join(a.out, f"chunks_{nm}", f"{k}.parquet")) for nm in a.array)

    todo = [s for s in srcs if not done(s)]
    print(f"{len(srcs)} sources in plan, {len(srcs) - len(todo)} already scanned, "
          f"{len(todo)} to scan with {a.workers} workers", file=sys.stderr)
    if not have_meta:
        # arrays.json from the first source, scanned in this process
        first = todo.pop(0) if todo else srcs[0]
        _, n, dt, meta = scan_source(first, a.array, a.out, True, a.engine)
        with open(os.path.join(a.out, "arrays.json"), "w") as f:
            json.dump(meta, f, indent=1, default=str)
        print(f"  {first}: {n} chunks in {dt:.1f} s (arrays.json written)", file=sys.stderr)

    t0, total = time.time(), 0
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(scan_source, s, a.array, a.out, False, a.engine) for s in todo]
        for i, f in enumerate(as_completed(futs), 1):
            s, n, dt, _ = f.result()
            total += n
            print(f"  [{i}/{len(todo)}] {os.path.basename(s)}: {n} chunks in {dt:.1f} s",
                  file=sys.stderr)
    print(f"harvest: {total} chunk rows from {len(todo)} sources in {time.time() - t0:.1f} s",
          file=sys.stderr)


if __name__ == "__main__":
    main()

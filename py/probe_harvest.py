"""probe_harvest.py -- which harvest engine is fast on this source, in about a minute.

usage: python probe_harvest.py SOURCE [ARRAY]
  SOURCE as in the plan, e.g. /vsicurl/https://thredds.nci.org.au/.../ocean_temp_2010_01.nc

Each probe stops after --budget seconds (default 30) and extrapolates to the
whole chunk grid. gdal: the first call on block 0 (GDAL >= 3.14 reads the
whole chunk index there in one H5Dchunk_iter pass), then per-block calls.
h5py: one H5Dchunk_iter pass through fsspec, at 16 KB and 64 KB read blocks
(1 MB blocks pulled 500 MB in 60 s from THREDDS on a BRAN month: avoid).

Each probe also reports HTTP range requests and bytes fetched, to compare how
hard each method leans on the server (GDAL's /vsicurl network stats; a
counter on fsspec's range fetcher).
"""
import itertools
import os
import math
import sys
import threading
import time

from osgeo import gdal

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption("CPL_VSIL_NETWORK_STATS_ENABLED", "YES")


def gdal_net():
    import json
    st = json.loads(gdal.NetworkStatsGetAsSerializedJSON() or "{}")
    m = st.get("methods", {}).get("GET", {})
    return m.get("count", 0), m.get("downloaded_bytes", 0)
src = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "temp"
budget = 30.0

gdal.NetworkStatsReset()  # counts include opening the file, as h5py's do
a = gdal.OpenEx(src, gdal.OF_MULTIDIM_RASTER).GetRootGroup().OpenMDArray(name)
shape = [d.GetSize() for d in a.GetDimensions()]
block = a.GetBlockSize()
total = math.prod(math.ceil(s / b) for s, b in zip(shape, block))
print(f"GDAL {gdal.__version__}; {name} {shape} blocks {block}: {total} chunks")

t0 = time.time()
a.GetRawBlockInfo([0] * len(shape))
t_first = time.time() - t0
n, t0 = 0, time.time()
grid = itertools.product(*[range(math.ceil(s / b)) for s, b in zip(shape, block)])
next(grid)
for c in grid:
    a.GetRawBlockInfo(list(c))
    n += 1
    if time.time() - t0 > budget:
        break
per = (time.time() - t0) / max(n, 1)
req, nb = gdal_net()
print(f"gdal: block 0 {t_first:.1f} s, then {n} blocks at {per * 1e3:.2f} ms "
      f"-> about {t_first + per * (total - 1):.0f} s per file; "
      f"{req} GETs, {nb / 1e6:.1f} MB for {n + 1} blocks")

try:
    import fsspec
    import h5py
except ImportError as e:
    sys.exit(f"h5py engine unavailable: {e}")
url = src[len("/vsicurl/"):] if src.startswith("/vsicurl/") else src
for bs in (16384, 65536):
    out = {}

    def run():
        t0 = time.time()
        f = url
        if "://" in url:
            f = fsspec.open(url, "rb", block_size=bs, cache_type="blockcache").open()
            fetch = f.cache.fetcher

            def counted(start, end):
                out["req"] = out.get("req", 0) + 1
                b = fetch(start, end)
                out["bytes"] = out.get("bytes", 0) + len(b)
                return b
            f.cache.fetcher = counted
        with h5py.File(f, "r") as h:
            cnt = []
            h[a.GetFullName()].id.chunk_iter(lambda ci: cnt.append(1))
        out["t"], out["n"] = time.time() - t0, len(cnt)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(budget * 2)
    if "t" in out:
        print(f"h5py, {bs // 1024} KB blocks: {out['n']} chunks in {out['t']:.1f} s; "
              f"{out.get('req', 0)} GETs, {out.get('bytes', 0) / 1e6:.1f} MB")
    else:
        print(f"h5py, {bs // 1024} KB blocks: not done after {budget * 2:.0f} s; "
              f"{out.get('req', 0)} GETs, {out.get('bytes', 0) / 1e6:.1f} MB so far")
sys.stdout.flush()
os._exit(0)  # a probe still running in its thread would otherwise hold up exit

"""bench_mdim_vrt.py -- open and subset timings for a GDAL multidim VRT over
remote sources (such as the cogger GHRSST VRT on source.coop), by number of
arrays and by GDAL configuration.

  python py/bench_mdim_vrt.py VRT [--arrays analysed_sst] [--series 10,100]
      [--procs 1,8] [--configs default,emptydir,nohead] [--out DIR]

VRT is a local path or a /vsicurl/ URL. The VRT is fetched once and timed,
then reduced to the arrays named in --arrays (coordinate arrays are kept),
written to --out, and checked for sources without a <SourceSlab count=...>
(without it GDAL opens every source of an array before any read).

For each configuration in --configs, a fresh process times:

  open             gdal.OpenEx(OF_MULTIDIM_RASTER) and OpenMDArray
  tile first/last  one block on the first and on the last time step
  series N         one pixel over the first N time steps, for each N in
                   --series, split over P processes for each P in --procs
                   (separate dataset handles; Python threads do not help,
                   the MDArray read holds the GIL)

and the HTTP requests GDAL made (CPL_VSIL_NETWORK_STATS_ENABLED; requests
made in the --procs worker processes are not counted). Every step starts
with cleared caches. Results go
to stdout as a Markdown table and to OUT/results.jsonl.

Configurations (each adds to the environment of the run):

  default    nothing set
  emptydir   GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
  nohead     emptydir + CPL_VSIL_CURL_USE_HEAD=NO
  http2      nohead + GDAL_HTTP_VERSION=2 + GDAL_HTTP_MULTIPLEX=YES
"""
import argparse
import json
import multiprocessing
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

CONFIGS = {
    "default": {},
    "emptydir": {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"},
    "nohead": {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_USE_HEAD": "NO"},
    "http2": {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_USE_HEAD": "NO",
              "GDAL_HTTP_VERSION": "2", "GDAL_HTTP_MULTIPLEX": "YES"},
}


def fetch(vrt):
    from osgeo import gdal
    gdal.UseExceptions()
    t0 = time.time()
    f = gdal.VSIFOpenL(vrt, "rb")
    gdal.VSIFSeekL(f, 0, 2)
    n = gdal.VSIFTellL(f)
    gdal.VSIFSeekL(f, 0, 0)
    data = gdal.VSIFReadL(1, n, f)
    gdal.VSIFCloseL(f)
    return data, time.time() - t0


def reduce(data, keep, base):
    """Drop data arrays not in keep; report sources without a SourceSlab count;
    make relative source names absolute (the reduced copy is written locally)."""
    root = ET.fromstring(data)
    for fn in root.iter("SourceFilename"):
        if fn.get("relativeToVRT") == "1":
            fn.text = f"{base}/{fn.text}"
            fn.set("relativeToVRT", "0")
    group = root.find("Group")
    info = {}
    for arr in list(group.findall("Array")):
        sources = arr.findall("Source")
        if not sources:  # coordinate array
            continue
        name = arr.get("name")
        if keep and name not in keep:
            group.remove(arr)
            continue
        nocount = sum(1 for s in sources
                      if s.find("SourceSlab") is None or s.find("SourceSlab").get("count") is None)
        info[name] = {"sources": len(sources), "without_count": nocount}
    return ET.tostring(root), info


def child(vrt, array, series, procs):
    """One configuration, in its own process (fresh GDAL caches)."""
    from concurrent.futures import ProcessPoolExecutor
    from osgeo import gdal
    import numpy as np
    gdal.UseExceptions()
    out = []

    def timed(name, f, **extra):
        gdal.NetworkStatsReset()
        t0 = time.time()
        f()
        s = json.loads(gdal.NetworkStatsGetAsSerializedJSON() or "{}").get("methods", {})
        out.append({"step": name, "seconds": round(time.time() - t0, 3),
                    "HEAD": s.get("HEAD", {}).get("count", 0), "GET": s.get("GET", {}).get("count", 0),
                    "MB": round(s.get("GET", {}).get("downloaded_bytes", 0) / 1e6, 3), **extra})

    def fresh():
        # every step starts cold: no cached sources, headers or blocks
        gdal.VSICurlClearCache()
        return gdal.OpenEx(vrt, gdal.OF_MULTIDIM_RASTER).GetRootGroup().OpenMDArray(array)

    timed("open", fresh)
    a = fresh()
    dims = [d.GetSize() for d in a.GetDimensions()]
    blk = [int(b) or 1 for b in a.GetBlockSize()] or [1] * len(dims)
    cnt = [1] + [min(b, d) for b, d in zip(blk[1:], dims[1:])]
    zero = [0] * (len(dims) - 1)
    a = fresh()
    timed("tile first", lambda: a.Read(array_start_idx=[0] + zero, count=cnt))
    a = fresh()
    timed("tile last", lambda: a.Read(array_start_idx=[dims[0] - 1] + zero, count=cnt))
    px = [d // 3 for d in dims[1:]]
    spawn = multiprocessing.get_context("spawn")  # children start with empty caches
    for n in series:
        n = min(n, dims[0])
        for p in procs:
            cuts = np.linspace(0, n, p + 1).astype(int).tolist()
            a = fresh()
            if p == 1:
                f = lambda: a.Read(array_start_idx=[0] + px, count=[n] + [1] * len(px))
            else:
                def f():
                    with ProcessPoolExecutor(p, mp_context=spawn) as ex:
                        list(ex.map(_part, [vrt] * p, [array] * p, cuts[:-1], cuts[1:], [px] * p))
            timed(f"series {n}", f, procs=p)
    print(json.dumps(out))


def _part(vrt, array, lo, hi, px):
    from osgeo import gdal
    gdal.UseExceptions()
    a = gdal.OpenEx(vrt, gdal.OF_MULTIDIM_RASTER).GetRootGroup().OpenMDArray(array)
    return a.Read(array_start_idx=[lo] + px, count=[hi - lo] + [1] * len(px))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("vrt")
    ap.add_argument("--arrays", default="analysed_sst", help="comma separated; empty for all")
    ap.add_argument("--series", default="10,100")
    ap.add_argument("--procs", default="1")
    ap.add_argument("--configs", default="default,emptydir,nohead")
    ap.add_argument("--out", default="bench-out")
    ap.add_argument("--child", nargs=4, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.child:
        vrt, array, series, procs = a.child
        return child(vrt, array, [int(x) for x in series.split(",")], [int(x) for x in procs.split(",")])

    os.makedirs(a.out, exist_ok=True)
    keep = [x for x in a.arrays.split(",") if x]
    data, sec = fetch(a.vrt)
    print(f"fetched {a.vrt}: {len(data) / 1e6:.1f} MB in {sec:.1f} s")
    xml, info = reduce(data, keep, os.path.dirname(a.vrt) if a.vrt.startswith("/vsi") else os.path.dirname(os.path.abspath(a.vrt)))
    for k, v in info.items():
        print(f"  {k}: {v['sources']} sources, {v['without_count']} without SourceSlab count")
    local = os.path.join(a.out, "subset.vrt")
    with open(local, "wb") as f:
        f.write(xml)
    print(f"kept {', '.join(info)} -> {local} ({len(xml) / 1e6:.1f} MB)\n")
    first = next(iter(info))

    rows = []
    for c in a.configs.split(","):
        env = {**os.environ, **CONFIGS[c], "CPL_VSIL_NETWORK_STATS_ENABLED": "YES"}
        r = subprocess.run([sys.executable, __file__, "x", "--child", local, first, a.series, a.procs],
                           env=env, capture_output=True, text=True)
        if r.returncode:
            print(f"{c}: failed\n{r.stderr[-2000:]}")
            continue
        for row in json.loads(r.stdout.strip().splitlines()[-1]):
            rows.append({"config": c, "arrays": len(info), **row})
    with open(os.path.join(a.out, "results.jsonl"), "a") as f:
        for row in rows:
            f.write(json.dumps({"vrt": a.vrt, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}) + "\n")
    print("| config | step | procs | seconds | HEAD | GET | MB |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['config']} | {r['step']} | {r.get('procs', '')} | {r['seconds']} | {r['HEAD']} | {r['GET']} | {r['MB']} |")


if __name__ == "__main__":
    main()

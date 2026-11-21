"""flat_regroup.py -- rewrite the refs files of a flat refs store with small row groups.

  python py/flat_regroup.py SRC OUT [--rows N] [--arrays a,b]

SRC is a flat/ directory, local or https:// (arrays.json beside the
refs_<array>.parquet files). OUT is a local directory: arrays.json,
sources.parquet and every refs_<array>.parquet of a referenced array are
written there, the refs files with row groups of whole steps of the leading
dimension, the same layout R/mdimrefs_pipeline.R mr_write_flat() writes
(row_group_rows). Rows, columns and values are unchanged; only the row
groups, the codec (zstd) and the statistics (dim_* and present only) differ.

For a store published before mr_write_flat() took row_group_rows: rewrite,
then upload only the refs files (py/s3_sync.py, one file at a time).

  --rows N    target rows a row group (default 20000; 0 keeps one group per
              writer default, about 1M rows)
  --arrays    referenced arrays to rewrite (default all)

The layout rule: chunks a step = product of the chunk grid over every
dimension after the first; steps a group = max(1, round(N / chunks a step));
a row's group is floor(dim_0 / steps), so groups start at multiples of
`steps` in global dim_0 and a lookup by dim_0 reads only the groups that
hold its keys.
"""
import argparse
import json
import math
import os
import shutil
import struct
import sys
import time
import urllib.request

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def fetch(src, name, out):
    dst = os.path.join(out, name)
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(f"{src.rstrip('/')}/{name}") as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    else:
        shutil.copyfile(os.path.join(src, name), dst)
    return dst


def steps_per_group(shape, chunks, rows):
    per = math.prod(math.ceil(s / c) for s, c in zip(shape[1:], chunks[1:])) if len(shape) > 1 else 1
    return max(1, round(rows / per)), per


def footer_bytes(path):
    with open(path, "rb") as f:
        f.seek(-8, 2)
        return struct.unpack("<i", f.read(4))[0]


def regroup(tbl, path, steps, stats):
    """Write tbl (sorted by dim_0) to path, one row group per run of dim_0 // steps."""
    g = tbl["dim_0"].to_numpy() // steps
    cut = np.flatnonzero(np.diff(g)) + 1
    starts, ends = np.r_[0, cut], np.r_[cut, len(g)]
    with pq.ParquetWriter(path, tbl.schema, compression="zstd", write_statistics=stats) as w:
        for s, e in zip(starts, ends):
            w.write_table(tbl.slice(int(s), int(e - s)), row_group_size=int(e - s))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--arrays", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    doc = json.load(open(fetch(a.src, "arrays.json", a.out)))
    fetch(a.src, "sources.parquet", a.out)
    want = set(filter(None, a.arrays.split(",")))
    for r in doc["arrays"]:
        if r.get("storage") != "referenced" or (want and r["array"] not in want):
            continue
        name = f"refs_{r['array']}.parquet"
        t0 = time.time()
        raw = fetch(a.src, name, a.out)
        tbl = pq.read_table(raw)
        os.replace(raw, raw + ".orig")
        d0 = tbl["dim_0"].to_numpy()
        if len(d0) > 1 and np.any(np.diff(d0) < 0):
            sys.exit(f"{name}: rows are not sorted by dim_0")
        dims = [f"dim_{i}" for i in range(len(r["shape"]))]
        stats = [c for c in dims + ["present"] if c in tbl.column_names]
        if a.rows > 0:
            steps, per = steps_per_group(r["shape"], r["chunks"], a.rows)
            regroup(tbl, raw, steps, stats)
        else:
            steps, per = None, None
            pq.write_table(tbl, raw, compression="zstd", write_statistics=stats)
        back = pq.read_table(raw)
        if not back.equals(tbl):
            sys.exit(f"{name}: rewritten table differs from the source")
        os.remove(raw + ".orig")
        md = pq.ParquetFile(raw).metadata
        print(f"  {name}: {tbl.num_rows} rows, {per} chunks a step, {steps} steps a group, "
              f"{md.num_row_groups} row groups, {os.path.getsize(raw) / 1e6:.1f} MB, "
              f"footer {footer_bytes(raw) / 1e3:.0f} KB, {time.time() - t0:.1f} s", file=sys.stderr)


if __name__ == "__main__":
    main()

"""lookup_cost.py -- bytes and requests a chunk-key lookup costs on a flat refs file.

  python py/lookup_cost.py URL_OR_PATH [--time T] [--repeat 3]

Opens refs_<array>.parquet through a file object that sends one ranged GET
(or local read) per read call and counts them, then runs three lookups the
way a reader that prunes on row-group statistics does: read the footer,
keep the row groups whose dim_* min/max can hold the keys, read only those
row groups and the columns a reader needs (dim_*, present, path, offset,
size), filter rows.

  point  one chunk at time T
  bbox   4 x 6 chunks at time T
  cube   the bbox over 30 steps from T

"cold" is a new handle (footer included); "warm" reuses the handle of the
cold point lookup with other keys. Prints one JSON line per lookup with
requests, bytes, seconds, row groups read and rows returned. Needs pyarrow
only; https URLs are read anonymously with urllib.
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.request

import pyarrow.compute as pc
import pyarrow.parquet as pq


class Counted(io.RawIOBase):
    def __init__(self, src):
        self.src, self.pos, self.requests, self.bytes = src, 0, 0, 0
        if src.startswith(("http://", "https://")):
            req = urllib.request.Request(src, method="HEAD")
            with urllib.request.urlopen(req) as r:
                self.size = int(r.headers["Content-Length"])
            self.f = None
        else:
            self.f = open(src, "rb")
            self.size = os.fstat(self.f.fileno()).st_size

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        self.requests += 1
        if self.f is None:
            req = urllib.request.Request(self.src, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
            with urllib.request.urlopen(req) as r:
                b = r.read()
        else:
            self.f.seek(self.pos)
            b = self.f.read(n)
        self.pos += len(b)
        self.bytes += len(b)
        return b

    def readinto(self, buf):
        b = self.read(len(buf))
        buf[:len(b)] = b
        return len(b)


def stats_range(rg, col):
    for j in range(rg.num_columns):
        c = rg.column(j)
        if c.path_in_schema == col and c.is_stats_set and c.statistics.has_min_max:
            return c.statistics.min, c.statistics.max
    return None


def lookup(pf, lo, hi, cols):
    """Rows with lo[i] <= dim_i <= hi[i], reading only row groups whose stats overlap."""
    md = pf.metadata
    keep = []
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        ok = True
        for i in range(len(lo)):
            s = stats_range(rg, f"dim_{i}")
            if s is not None and (s[1] < lo[i] or s[0] > hi[i]):
                ok = False
                break
        if ok:
            keep.append(g)
    t = pf.read_row_groups(keep, columns=cols)
    m = None
    for i in range(len(lo)):
        x = pc.and_(pc.greater_equal(t[f"dim_{i}"], lo[i]), pc.less_equal(t[f"dim_{i}"], hi[i]))
        m = x if m is None else pc.and_(m, x)
    return len(keep), t.filter(m).num_rows


def run(src, name, state, query, lo, hi, out):
    f0 = state.get("f")
    cold = f0 is None
    if cold:
        f0 = Counted(src)
    r0, b0, t0 = f0.requests, f0.bytes, time.time()
    if cold:
        state["pf"] = pq.ParquetFile(f0)
        state["f"] = f0
    pf = state["pf"]
    n = len([c for c in pf.schema_arrow.names if c.startswith("dim_")])
    cols = [f"dim_{i}" for i in range(n)] + ["present", "path", "offset", "size"]
    ngroups, nrows = lookup(pf, lo[:n], hi[:n], cols)
    out.append(dict(file=name, query=query, state="cold" if cold else "warm",
                    requests=f0.requests - r0, mb=round((f0.bytes - b0) / 1e6, 3),
                    seconds=round(time.time() - t0, 2), row_groups=ngroups, rows=nrows,
                    file_row_groups=pf.metadata.num_row_groups))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--time", type=int, default=4000)
    ap.add_argument("--y", type=int, default=20, help="dim_1 of the bbox corner")
    ap.add_argument("--x", type=int, default=40, help="dim_2 of the bbox corner")
    a = ap.parse_args()
    name = os.path.basename(a.src.rstrip("/"))
    out = []
    T, Y, X = a.time, a.y, a.x
    # cold: one new handle per query
    for q, lo, hi in [("point", [T, Y, X], [T, Y, X]),
                      ("bbox", [T, Y, X], [T, Y + 3, X + 5]),
                      ("cube", [T, Y, X], [T + 29, Y + 3, X + 5])]:
        run(a.src, name, {}, q, lo, hi, out)
    # warm: one handle, opened by a point lookup, then other keys
    st = {}
    run(a.src, name, st, "point", [T, Y, X], [T, Y, X], [])
    for q, lo, hi in [("point", [T + 101, Y + 3, X + 5], [T + 101, Y + 3, X + 5]),
                      ("bbox", [T + 202, Y, X], [T + 202, Y + 3, X + 5]),
                      ("cube", [T + 303, Y, X], [T + 332, Y + 3, X + 5])]:
        run(a.src, name, st, q, lo, hi, out)
    for o in out:
        print(json.dumps(o))


if __name__ == "__main__":
    main()

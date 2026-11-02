"""filelist.py -- source list from an aad-filelist Parquet file list.

mdsumner/aad-filelist publishes one Parquet file per collection of the raad
mirror (release `latest`), with a `url` column holding the original HTTPS
URL of every file. This script prints the selected URLs, one per line, in
date order, for a dataset config's sources() function.

  --filelist   local path or https URL of the Parquet file
  --cache      where to keep a copy of a fetched URL (a record of the list
               the plan was made from; it is fetched again on every run)
  --match      regular expression the URL must match (repeatable: all must
               match)
  --date       regular expression with one group capturing the file date
               (digits, e.g. YYYYMMDD) from the file name; the output is
               sorted on it and --first/--last compare against it
  --first, --last
               inclusive bounds on the captured date (string comparison,
               same width as the capture)
  --prefix OLD NEW
               replace a leading OLD of each URL by NEW (e.g. a local mirror
               root, or /vsicurl/https://)

Usage:
  python filelist.py --filelist https://.../cdr_sic_G02202_V6.parquet \
      --match '/south/daily/' --date '_([0-9]{8})_' \
      --prefix https:// /vsicurl/https://
"""
import argparse
import collections
import io
import os
import re
import sys
import urllib.request

import pyarrow.parquet as pq


def read_urls(filelist, cache):
    if re.match(r"^https?://", filelist):
        with urllib.request.urlopen(filelist) as r:
            data = r.read()
        if cache:
            tmp = cache + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, cache)
        src = io.BytesIO(data)
    else:
        src = filelist
    return pq.read_table(src, columns=["url"]).column("url").to_pylist()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--filelist", required=True)
    ap.add_argument("--cache", default="")
    ap.add_argument("--match", action="append", default=[])
    ap.add_argument("--date", required=True)
    ap.add_argument("--first", default="")
    ap.add_argument("--last", default="")
    ap.add_argument("--prefix", nargs=2, metavar=("OLD", "NEW"))
    a = ap.parse_args()

    pats = [re.compile(m) for m in a.match]
    date = re.compile(a.date)
    out = []
    for u in read_urls(a.filelist, a.cache):
        if not u or not all(p.search(u) for p in pats):
            continue
        m = date.search(u.rsplit("/", 1)[-1])
        if not m:
            continue
        d = m.group(1)
        if (a.first and d < a.first) or (a.last and d > a.last):
            continue
        if a.prefix and u.startswith(a.prefix[0]):
            u = a.prefix[1] + u[len(a.prefix[0]):]
        out.append((d, u))
    out.sort()
    dup = sorted(d for d, n in collections.Counter(d for d, _ in out).items() if n > 1)
    if dup:
        sys.exit(f"filelist: more than one file for date(s) {', '.join(dup[:5])}"
                 f"{' ...' if len(dup) > 5 else ''}; add a --match to choose")
    if not out:
        sys.exit("filelist: no URL selected")
    sys.stdout.write("".join(u + "\n" for _, u in out))


if __name__ == "__main__":
    main()

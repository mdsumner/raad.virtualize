"""corpus.py -- source list from the aad-filelist listing corpus.

mdsumner/aad-filelist keeps every run's listing of every source and
publishes what each one offers now as `current__<source_id>.parquet` on its
`corpus` release (columns url, size, mtime, etag, how, first_seen,
last_changed, last_seen; see corpus/README.md there). This script prints
the selected URLs, one per line, in date order, for a dataset config's
sources() function. It replaces py/filelist.py (same selection flags) and
can also write what the corpus knows about each selected file (--meta), the
record a later staleness check compares against the corpus `changes`.

  --source     corpus source id (e.g. cdr_sic_G02202_V6); read from
               --corpus/current__<id>.parquet
  --corpus     base URL or local directory of the corpus release (default
               the aad-filelist `corpus` release); a local directory may
               hold current__<id>.parquet or current/<id>.parquet
  --listing    a current__<id>.parquet path or URL, instead of --source
  --cache      where to keep a copy of a fetched listing (a record of the
               list the plan was made from; fetched again on every run)
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
  --exists     keep only entries that exist as local files after the prefix
               swap (a mirror that lags the list); the count dropped goes to
               stderr
  --meta FILE  write the build record (write_meta): one row per selected
               file, with what the corpus knew of it; py/stale.py compares
               it with the corpus later

Usage:
  python corpus.py --source cdr_sic_G02202_V6 \
      --match '/south/daily/' --date '_([0-9]{8})_' \
      --prefix https:// /vsicurl/https://
"""
import argparse
import collections
import csv
import io
import os
import re
import sys
import urllib.request

import pyarrow.parquet as pq

CORPUS = "https://github.com/mdsumner/aad-filelist/releases/download/corpus"
COLS = ["url", "size", "mtime", "etag", "last_changed"]


def _is_url(s):
    return re.match(r"^https?://", s) is not None


def listing_location(a):
    if a.listing:
        return a.listing
    if not a.source:
        sys.exit("corpus: give --source or --listing")
    return current_location(a.source, a.corpus)


def read_listing(loc, cache):
    if _is_url(loc):
        req = urllib.request.Request(loc, headers={"User-Agent": "raad.virtualize corpus.py"})
        with urllib.request.urlopen(req) as r:
            data = r.read()
        if cache:
            tmp = cache + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, cache)
        src = io.BytesIO(data)
    else:
        if not os.path.exists(loc):
            sys.exit(f"corpus: no listing at {loc}")
        src = loc
    t = pq.read_table(src)
    have = [c for c in COLS if c in t.column_names]
    if "url" not in have:
        sys.exit(f"corpus: {loc} has no url column")
    d = t.select(have).to_pydict()
    n = t.num_rows
    return [{c: (d[c][i] if c in d else None) for c in COLS} for i in range(n)]


## the build record: what a store was built against, one row per source
## file. source is the path as harvested (a mirror path or /vsicurl/ URL),
## url the file as the corpus lists it (the published reference), and size,
## mtime, etag, last_changed what the corpus (or the lister) knew then.
META_COLS = ["source_id", "source", "url", "date", "size", "mtime", "etag", "last_changed"]


def current_location(source, base=None):
    """Where current__<source>.parquet is: base URL or local directory."""
    base = base or os.environ.get("CORPUS_BASE", CORPUS)
    if _is_url(base):
        return f"{base.rstrip('/')}/current__{source}.parquet"
    flat = os.path.join(base, f"current__{source}.parquet")
    tree = os.path.join(base, "current", f"{source}.parquet")
    return flat if os.path.exists(flat) or not os.path.exists(tree) else tree


def write_meta(path, rows):
    """rows: dicts with META_COLS keys (missing ones are empty)."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(META_COLS)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in META_COLS])
    os.replace(tmp, path)


def _fmt(v):
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", default="")
    ap.add_argument("--corpus", default=os.environ.get("CORPUS_BASE", CORPUS))
    ap.add_argument("--listing", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--match", action="append", default=[])
    ap.add_argument("--date", required=True)
    ap.add_argument("--first", default="")
    ap.add_argument("--last", default="")
    ap.add_argument("--prefix", nargs=2, metavar=("OLD", "NEW"))
    ap.add_argument("--exists", action="store_true")
    ap.add_argument("--meta", default="")
    a = ap.parse_args()

    loc = listing_location(a)
    pats = [re.compile(m) for m in a.match]
    date = re.compile(a.date)
    out = []
    for row in read_listing(loc, a.cache):
        u = row["url"]
        if not u or not all(p.search(u) for p in pats):
            continue
        m = date.search(u.rsplit("/", 1)[-1])
        if not m:
            continue
        d = m.group(1)
        if (a.first and d < a.first) or (a.last and d > a.last):
            continue
        s = u
        if a.prefix and s.startswith(a.prefix[0]):
            s = a.prefix[1] + s[len(a.prefix[0]):]
        out.append((d, s, row))
    if a.exists:
        n = len(out)
        out = [x for x in out if os.path.isfile(x[1])]
        if len(out) < n:
            sys.stderr.write(f"corpus: {n - len(out)} of {n} listed files not found locally, skipped\n")
    out.sort(key=lambda x: (x[0], x[1]))
    dup = sorted(d for d, n in collections.Counter(d for d, _, _ in out).items() if n > 1)
    if dup:
        sys.exit(f"corpus: more than one file for date(s) {', '.join(dup[:5])}"
                 f"{' ...' if len(dup) > 5 else ''}; add a --match to choose")
    if not out:
        sys.exit(f"corpus: no URL selected from {loc}")
    unsized = sum(1 for _, _, r in out if r["size"] is None)
    if unsized:
        sys.stderr.write(f"corpus: {unsized} of {len(out)} selected files have no size in the corpus\n")
    if a.meta:
        sid = a.source or os.path.basename(loc).removeprefix("current__").removesuffix(".parquet")
        write_meta(a.meta, ({**r, "source_id": sid, "source": s, "date": d} for d, s, r in out))
    sys.stdout.write("".join(s + "\n" for _, s, _ in out))


if __name__ == "__main__":
    main()

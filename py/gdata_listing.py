"""gdata_listing.py -- list a local file tree (NCI /g/data) as a corpus source.

For a source the producer holds on a shared filesystem, the filesystem is
the listing: this walks a root, stats every file that matches, and keeps
the result in the shape of the aad-filelist corpus, so py/corpus.py
(--corpus DIR --source ID) selects sources from it and py/stale.py
(--corpus DIR) checks a build record against it. Each run is kept.

Written under --corpus DIR:

  current__<id>.parquet   url, size, mtime, etag, how, first_seen,
                          last_changed, last_seen (the files there now)
  changes__<id>.parquet   op (add, change, remove), url, run_id, signal;
                          appended on every run that sees a difference
  runs/<id>/<run_id>.parquet
                          the listing of that run, as taken
  heartbeat__<id>.json    listed_at, run_id, root, n_files, bytes,
                          listing_hash, changed, n_add, n_change, n_remove,
                          previous_run_id

url is the absolute path as listed (a config's REMAPS rewrite it to the
public URL at render). A filesystem has no etag, so etag is
"stat:<size>:<mtime_ns>": a file rewritten in place at the same size
counts as changed. listing_hash is the sha256 of the sorted
(url, size, mtime_ns) lines, so two runs over an unchanged tree give the
same hash.

  --root      directory to walk (repeatable)
  --source    source id (e.g. gdata_gb6_bran)
  --corpus    directory holding the listings (created if absent)
  --match     regular expression the path must match (repeatable: all must
              match); default every file
  --run-id    default the UTC time of the run, %Y%m%dT%H%M%SZ
  --dry-run   print the counts, write nothing

Exit status 0 = no change since the last run, 3 = changed (or first run),
1 = error. The heartbeat is written either way.

Usage:
  python gdata_listing.py --root /g/data/gb6/BRAN --source gdata_gb6_bran \
      --match '/(daily|month)/ocean_[a-z_]+_[0-9]{4}_[0-9]{2}\\.nc$' \
      --corpus /g/data/jk72/$USER/listings
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema([
    ("url", pa.string()), ("size", pa.int64()), ("mtime", pa.timestamp("s", tz="UTC")),
    ("etag", pa.string()), ("how", pa.string()), ("first_seen", pa.string()),
    ("last_changed", pa.string()), ("last_seen", pa.string()),
])
CHANGES = pa.schema([
    ("op", pa.string()), ("url", pa.string()), ("run_id", pa.string()), ("signal", pa.string()),
])


def walk(root, pats):
    """Yield (path, size, mtime_ns) for regular files under root."""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except PermissionError as e:
            sys.stderr.write(f"gdata_listing: skipped {d}: {e}\n")
            continue
        with it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    if all(p.search(e.path) for p in pats):
                        st = e.stat(follow_symlinks=False)
                        yield e.path, st.st_size, st.st_mtime_ns


def read_current(path):
    if not os.path.exists(path):
        return {}
    d = pq.read_table(path).to_pylist()
    return {r["url"]: r for r in d}


def write_atomic(table, path):
    tmp = path + ".tmp"
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--match", action="append", default=[])
    ap.add_argument("--run-id", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", a.source):
        sys.exit(f"gdata_listing: bad source id {a.source!r}")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    run_id = a.run_id or now.strftime("%Y%m%dT%H%M%SZ")
    pats = [re.compile(m) for m in a.match]

    files = {}
    for root in a.root:
        if not os.path.isdir(root):
            sys.exit(f"gdata_listing: no directory {root} (missing -l storage=gdata/<project>?)")
        for p, s, m in walk(os.path.abspath(root), pats):
            files[p] = (s, m)
    if not files:
        sys.exit(f"gdata_listing: no files matched under {', '.join(a.root)}")

    h = hashlib.sha256()
    for p in sorted(files):
        s, m = files[p]
        h.update(f"{p}\t{s}\t{m}\n".encode())
    listing_hash = h.hexdigest()

    cur_path = os.path.join(a.corpus, f"current__{a.source}.parquet")
    hb_path = os.path.join(a.corpus, f"heartbeat__{a.source}.json")
    prev = read_current(cur_path)
    prev_hb = {}
    if os.path.exists(hb_path):
        with open(hb_path) as f:
            prev_hb = json.load(f)

    rows, changes = [], []
    for p in sorted(files):
        s, m = files[p]
        etag = f"stat:{s}:{m}"
        old = prev.get(p)
        if old is None:
            first, last_changed = run_id, run_id
            if prev:
                changes.append({"op": "add", "url": p, "run_id": run_id, "signal": "new"})
        else:
            first = old["first_seen"]
            last_changed = old["last_changed"]
            if old["etag"] != etag:
                last_changed = run_id
                sig = "size" if old["size"] != s else "mtime"
                changes.append({"op": "change", "url": p, "run_id": run_id, "signal": sig})
        rows.append({"url": p, "size": s,
                     "mtime": dt.datetime.fromtimestamp(m / 1e9, dt.timezone.utc).replace(microsecond=0),
                     "etag": etag, "how": "gdata-stat", "first_seen": first,
                     "last_changed": last_changed, "last_seen": run_id})
    for p in sorted(set(prev) - set(files)):
        changes.append({"op": "remove", "url": p, "run_id": run_id, "signal": "gone"})

    n = {op: sum(1 for c in changes if c["op"] == op) for op in ("add", "change", "remove")}
    changed = (not prev) or bool(changes)
    hb = {"source_id": a.source, "listed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
          "run_id": run_id, "root": a.root, "match": a.match, "n_files": len(files),
          "bytes": sum(s for s, _ in files.values()), "listing_hash": listing_hash,
          "changed": changed, "n_add": n["add"], "n_change": n["change"],
          "n_remove": n["remove"], "previous_run_id": prev_hb.get("run_id", "")}
    print(json.dumps(hb))
    if a.dry_run:
        return 3 if changed else 0

    os.makedirs(os.path.join(a.corpus, "runs", a.source), exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    if changed:
        write_atomic(table, os.path.join(a.corpus, "runs", a.source, f"{run_id}.parquet"))
        write_atomic(table, cur_path)
    else:
        # same files: carry last_seen forward without a new run file
        write_atomic(table, cur_path)
    if changes:
        ch_path = os.path.join(a.corpus, f"changes__{a.source}.parquet")
        new = pa.Table.from_pylist(changes, schema=CHANGES)
        if os.path.exists(ch_path):
            new = pa.concat_tables([pq.read_table(ch_path).cast(CHANGES), new])
        write_atomic(new, ch_path)
    tmp = hb_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(hb, f, indent=1)
        f.write("\n")
    os.replace(tmp, hb_path)
    return 3 if changed else 0


if __name__ == "__main__":
    sys.exit(main())

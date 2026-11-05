"""stale.py -- source files of a store that changed or went away since it was built.

A build writes its record of every source file it references
(sources.meta.tsv: source_id, source, url, date, size, mtime, etag,
last_changed; py/corpus.py write_meta, from the config's sources()). This
compares that record with what the aad-filelist listing corpus holds now
(current__<source_id>.parquet) and reports, per referenced url:

  removed   the corpus no longer lists it (withdrawn, or renamed)
  changed   listed with a different etag, or the same etag missing and a
            different size: the file was replaced at the same URL, so the
            byte offsets in the store may point at the wrong bytes

The first pair present on both sides decides (etag, then size), the corpus
change rule. A url the corpus shows a later `last_changed` for but with the
same etag and size is not stale (the corpus saw a change and a change
back, or the record predates the corpus fill of that value). The corpus
`changes` table, when readable, adds when and on what signal it saw each
stale url change.

  --meta     the build record: a local path or URL (a published store keeps
             it beside plan.vrt as sources.meta.tsv); repeatable
  --corpus   corpus base URL or local directory (default CORPUS_BASE, else
             the aad-filelist `corpus` release)
  --out      write the stale rows as TSV
  --warn     report but exit 0 (default: exit 1 when anything is stale)

Exit status 0 = nothing stale, 1 = stale files found, 2 = could not check
(a source id with no corpus listing).

Usage:
  python stale.py --meta work/g02202-v6-daily-south/sources.meta.tsv
  python stale.py --meta https://data.source.coop/ausantarctic/ausantarctic-scratch/seaice/<dataset>/sources.meta.tsv
"""
import argparse
import csv
import io
import os
import re
import sys
import urllib.error
import urllib.request

import pyarrow.parquet as pq

import corpus


def read_meta(loc):
    if re.match(r"^https?://", loc):
        req = urllib.request.Request(loc, headers={"User-Agent": "raad.virtualize stale.py"})
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
    else:
        with open(loc) as f:
            text = f.read()
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def read_changes(source_id, base):
    """{url: (run_id, signal)} of the latest change or remove event, or {}."""
    loc = corpus.current_location(source_id, base).replace("current__", "changes__", 1)
    if "/current/" in loc:
        loc = loc.replace("/current/", "/changes/")
    try:
        if re.match(r"^https?://", loc):
            req = urllib.request.Request(loc, headers={"User-Agent": "raad.virtualize stale.py"})
            with urllib.request.urlopen(req) as r:
                t = pq.read_table(io.BytesIO(r.read()))
        elif os.path.exists(loc):
            t = pq.read_table(loc)
        else:
            return {}
    except (OSError, urllib.error.URLError):
        return {}
    d = t.select([c for c in ["op", "url", "run_id", "signal"] if c in t.column_names]).to_pydict()
    sig = d.get("signal")
    out = {}
    for i, op in enumerate(d.get("op", [])):
        if op in ("change", "remove"):
            out[d["url"][i]] = (d["run_id"][i], (sig[i] if sig else None) or op)
    return out


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def verdict(rec, cur):
    """None (same), 'changed' or 'removed', and the evidence."""
    if cur is None:
        return "removed", ""
    e0, e1 = rec.get("etag") or None, cur.get("etag") or None
    if e0 and e1:
        return (None, "") if e0 == e1 else ("changed", f"etag {e0} -> {e1}")
    s0, s1 = _num(rec.get("size")), _num(cur.get("size"))
    if s0 is not None and s1 is not None:
        return (None, "") if s0 == s1 else ("changed", f"size {s0:.0f} -> {s1:.0f}")
    return None, "no etag or size on both sides"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--meta", action="append", required=True)
    ap.add_argument("--corpus", default=os.environ.get("CORPUS_BASE", corpus.CORPUS))
    ap.add_argument("--out", default="")
    ap.add_argument("--warn", action="store_true")
    a = ap.parse_args()

    rows = [r for m in a.meta for r in read_meta(m)]
    if not rows:
        sys.exit("stale: empty build record")
    by_source = {}
    for r in rows:
        by_source.setdefault(r["source_id"], []).append(r)

    stale, unknown, missing = [], 0, []
    for sid, recs in sorted(by_source.items()):
        loc = corpus.current_location(sid, a.corpus)
        try:
            cur = {x["url"]: x for x in corpus.read_listing(loc, "")}
        except (SystemExit, OSError, urllib.error.URLError) as e:
            print(f"stale: {sid}: no corpus listing at {loc} ({e})", file=sys.stderr)
            missing.append(sid)
            continue
        ch = None
        n = 0
        for r in recs:
            v, why = verdict(r, cur.get(r["url"]))
            if v is None:
                unknown += bool(why)
                continue
            if ch is None:
                ch = read_changes(sid, a.corpus)
            run_id, signal = ch.get(r["url"], ("", ""))
            stale.append({**r, "verdict": v, "evidence": why, "corpus_run_id": run_id,
                          "corpus_signal": signal})
            n += 1
        print(f"stale: {sid}: {len(recs)} referenced, {n} stale"
              f" ({sum(1 for s in stale if s['source_id'] == sid and s['verdict'] == 'removed')} removed)",
              file=sys.stderr)

    for s in stale[:20]:
        print(f"  {s['verdict']:8s} {s['date']} {s['url']} {s['evidence']}"
              f"{' (corpus run ' + s['corpus_run_id'] + ')' if s['corpus_run_id'] else ''}",
              file=sys.stderr)
    if len(stale) > 20:
        print(f"  ... {len(stale) - 20} more", file=sys.stderr)
    if unknown:
        print(f"stale: {unknown} referenced file(s) not checkable (no etag or size on both sides)",
              file=sys.stderr)
    if a.out:
        cols = corpus.META_COLS + ["verdict", "evidence", "corpus_run_id", "corpus_signal"]
        tmp = a.out + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, cols, delimiter="\t", lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(stale)
        os.replace(tmp, a.out)
    if missing:
        sys.exit(2)
    if stale and not a.warn:
        sys.exit(1)
    if not stale:
        print(f"stale: none of {len(rows)} referenced files changed", file=sys.stderr)


if __name__ == "__main__":
    main()

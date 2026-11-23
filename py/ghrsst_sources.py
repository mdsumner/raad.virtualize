"""ghrsst_sources.py -- source list and build record from ghrsst-cogger's own output.

ghrsst-cogger writes the MUR COGs to source.coop ausantarctic/ghrsst-mur-v2
on its own schedule, one directory per day (YYYY/MM/DD/) holding one COG
per variable and a STAC item (<stem>.stac-item.json). The item says what
cogger made the day from: `ghrsst:status` is "preliminary" for the interim
near-real-time MUR file and "final" once cogger has rewritten the day from
the final MUR file (at the same keys, a few days after the date), with
`updated` the time of that write.

This lists the bucket (S3 ListObjectsV2 on the public data.source.coop
endpoint, path style, no credentials), keeps the COGs of one variable, and
prints them in date order as sources. A day is indexed only when

  - its STAC item says ghrsst:status final (read for the days dated within
    --status-days of the newest day; older days are taken as final), and
  - its COG was last written at least --quiet days before the listing
    (cogger's own LastModified), so a rewrite in progress is not indexed.

Every day after the first one held back is held back too, so the series
ends cleanly. What is held back goes to stderr.

  --meta FILE   write the build record (py/corpus.py META_COLS) with
                source_id ghrsst-cogger: size, mtime, etag as listed
  --stale FILE  compare a build record with the bucket now instead (etag,
                then size, the py/stale.py rule): print each url that is
                removed or changed, exit 1 when any is (0 when none)

Usage:
  python ghrsst_sources.py --var analysed_sst --meta sources.meta.tsv > sources.txt
  python ghrsst_sources.py --var analysed_sst --stale sources.meta.tsv
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus import write_meta  # noqa: E402

NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
UA = {"User-Agent": "raad.virtualize ghrsst_sources.py"}
STEM = "090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv04.1"


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except OSError:
            if attempt == 4:
                raise
            # data.source.coop answers 503 under load
            time.sleep(2 ** attempt)


def list_objects(endpoint, bucket, prefix):
    """[(key, size, last_modified, etag)] under prefix (key without bucket)."""
    out, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(get(f"{endpoint}/{bucket}?{urllib.parse.urlencode(q)}"))
        for c in root.findall(f"{NS}Contents"):
            out.append((c.findtext(f"{NS}Key"), int(c.findtext(f"{NS}Size")),
                        c.findtext(f"{NS}LastModified"), (c.findtext(f"{NS}ETag") or "").strip('"')))
        if root.findtext(f"{NS}IsTruncated") != "true":
            return out
        token = root.findtext(f"{NS}NextContinuationToken")


def parse_time(s):
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--var", default="analysed_sst")
    ap.add_argument("--endpoint", default="https://data.source.coop")
    ap.add_argument("--bucket", default="ausantarctic")
    ap.add_argument("--prefix", default="ghrsst-mur-v2/")
    ap.add_argument("--years", default="", help="space separated years (default all)")
    ap.add_argument("--quiet", type=float, default=3,
                    help="days since cogger last wrote a COG before it is indexed")
    ap.add_argument("--status-days", type=int, default=60,
                    help="read the STAC item of days dated within this many days of the newest")
    ap.add_argument("--url-base", default="", help="source prefix (default /vsicurl/ + the public base)")
    ap.add_argument("--meta")
    ap.add_argument("--stale")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()

    public = f"{a.endpoint}/{a.bucket}/"
    base = a.url_base or "/vsicurl/" + public
    rx = re.compile(r"(^|/)([0-9]{4})/[0-9]{2}/[0-9]{2}/([0-9]{8})" + re.escape(STEM)
                    + "_" + re.escape(a.var) + r"\.tif$")
    prefixes = [a.prefix + y + "/" for y in a.years.split()] or [a.prefix]
    with ThreadPoolExecutor(min(a.workers, len(prefixes))) as ex:
        listed = [o for part in ex.map(lambda p: list_objects(a.endpoint, a.bucket, p), prefixes) for o in part]
    now = datetime.datetime.now(datetime.timezone.utc)
    objs = []
    for k, size, lm, etag in listed:
        m = rx.search(k)
        if m and m.group(2) == m.group(3)[:4]:
            objs.append((m.group(3), k, size, lm, etag))
    objs.sort()
    if not objs:
        sys.exit(f"ghrsst_sources: no {a.var} COG under {public}{a.prefix}")

    if a.stale:
        cur = {public + k: (size, etag) for _, k, size, _, etag in objs}
        bad = 0
        with open(a.stale) as f:
            for rec in csv.DictReader(f, delimiter="\t"):
                c = cur.get(rec["url"])
                if c is None:
                    verdict = "removed"
                elif rec["etag"] and c[1]:
                    verdict = "changed" if rec["etag"] != c[1] else ""
                else:
                    verdict = "changed" if str(rec["size"]) != str(c[0]) else ""
                if verdict:
                    bad += 1
                    print(f"{verdict}\t{rec['url']}")
        print(f"ghrsst_sources: {bad} stale of the build record", file=sys.stderr)
        sys.exit(1 if bad else 0)

    newest = datetime.datetime.strptime(objs[-1][0], "%Y%m%d")
    first_status = (newest - datetime.timedelta(days=a.status_days)).strftime("%Y%m%d")

    def status(o):
        d, k = o[0], o[1]
        if d < first_status:
            return "final"
        item = k.rsplit("/", 1)[0] + "/" + d + STEM + ".stac-item.json"
        try:
            return json.loads(get(public + item)).get("properties", {}).get("ghrsst:status") or "unknown"
        except OSError:
            return "no item"

    with ThreadPoolExecutor(a.workers) as ex:
        stats = list(ex.map(status, objs))
    keep, held = [], []
    for o, st in zip(objs, stats):
        age = (now - parse_time(o[3])).total_seconds() / 86400
        why = ("" if st == "final" else f"status {st}") or ("" if age >= a.quiet else f"written {age:.1f} days ago")
        if why or held:
            held.append((o[0], why or "after a held day"))
        else:
            keep.append(o)
    for d, why in held:
        print(f"ghrsst_sources: held back {d}: {why}", file=sys.stderr)
    if not keep:
        sys.exit("ghrsst_sources: every day held back")
    for _, k, *_ in keep:
        print(base + k)
    if a.meta:
        write_meta(a.meta, ({"source_id": "ghrsst-cogger", "source": base + k, "url": public + k, "date": d,
                             "size": size, "mtime": lm, "etag": etag, "last_changed": lm}
                            for d, k, size, lm, etag in keep))
    print(f"ghrsst_sources: {len(keep)} days {keep[0][0]}..{keep[-1][0]}, {len(held)} held back",
          file=sys.stderr)


if __name__ == "__main__":
    main()

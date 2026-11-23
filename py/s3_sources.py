"""s3_sources.py -- source list and build record from an anonymous S3 listing.

For public buckets listed directly rather than through the aad-filelist
corpus (IMOS imos-data, which the corpus lists as imos_aatams_meop_ctd).
Lists s3://BUCKET/PREFIX with ListObjectsV2 over https (no credentials, no
SDK), keeps the keys that match --match (a regex on the key), sorted by
key, and prints each as a source: URL_BASE + key, where URL_BASE defaults to
the bucket's virtual-hosted https endpoint with GDAL's /vsicurl/ prefix.

  --meta FILE   write the build record (py/corpus.py META_COLS: source_id,
                source, url, date, size, mtime, etag, last_changed), with
                source_id --source-id (default "s3:BUCKET"); give the
                corpus source id that lists the same objects, and the
                stale step (py/stale.py) reads the corpus for it
  --stale FILE  compare a build record with the bucket now instead (the
                py/stale.py rule: etag, then size): print each url that is
                removed or changed, and exit 1 when any is (0 when none)

Usage:
  python s3_sources.py --bucket imos-data --region ap-southeast-2 \\
    --prefix IMOS/AATAMS/satellite_tagging/MEOP_QC_CTD/ --match '_hr1_prof\\.nc$' \\
    [--meta sources.meta.tsv] > sources.txt
  python s3_sources.py --bucket imos-data --region ap-southeast-2 \\
    --prefix IMOS/AATAMS/satellite_tagging/MEOP_QC_CTD/ --stale sources.meta.tsv
"""
import argparse
import csv
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus import write_meta  # noqa: E402

NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def endpoint(bucket, region):
    return f"https://{bucket}.s3.{region}.amazonaws.com/"


def list_objects(bucket, region, prefix):
    """[(key, size, last_modified, etag)] of every object under prefix."""
    out, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        url = endpoint(bucket, region) + "?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(url, timeout=60) as r:
            root = ET.fromstring(r.read())
        for c in root.findall(f"{NS}Contents"):
            out.append((c.findtext(f"{NS}Key"), int(c.findtext(f"{NS}Size")),
                        c.findtext(f"{NS}LastModified"), (c.findtext(f"{NS}ETag") or "").strip('"')))
        if root.findtext(f"{NS}IsTruncated") != "true":
            return out
        token = root.findtext(f"{NS}NextContinuationToken")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--region", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--match", default="", help="regex the key must match")
    ap.add_argument("--url-base", help="source prefix (default /vsicurl/ + the https endpoint)")
    ap.add_argument("--meta", help="write the build record here")
    ap.add_argument("--source-id", help="source_id of the build record: the aad-filelist corpus "
                                        "source that lists these objects (default s3:BUCKET)")
    ap.add_argument("--stale", help="compare this build record with the bucket now")
    a = ap.parse_args()
    https = endpoint(a.bucket, a.region)
    base = a.url_base or "/vsicurl/" + https
    rx = re.compile(a.match)
    objs = sorted(o for o in list_objects(a.bucket, a.region, a.prefix) if rx.search(o[0]))
    if a.stale:
        now = {https + k: (size, etag) for k, size, _, etag in objs}
        bad = 0
        with open(a.stale) as f:
            for rec in csv.DictReader(f, delimiter="\t"):
                cur = now.get(rec["url"])
                if cur is None:
                    verdict = "removed"
                elif rec["etag"] and cur[1]:
                    verdict = "changed" if rec["etag"] != cur[1] else ""
                else:
                    verdict = "changed" if str(rec["size"]) != str(cur[0]) else ""
                if verdict:
                    bad += 1
                    print(f"{verdict}\t{rec['url']}")
        print(f"s3_sources: {bad} stale of the build record", file=sys.stderr)
        sys.exit(1 if bad else 0)
    if not objs:
        sys.exit(f"s3_sources: nothing under s3://{a.bucket}/{a.prefix} matches {a.match!r}")
    for k, *_ in objs:
        print(base + k)
    if a.meta:
        sid = a.source_id or f"s3:{a.bucket}"
        write_meta(a.meta, ({"source_id": sid, "source": base + k, "url": https + k,
                             "size": size, "mtime": lm, "etag": etag, "last_changed": lm}
                            for k, size, lm, etag in objs))
    print(f"s3_sources: {len(objs)} objects", file=sys.stderr)


if __name__ == "__main__":
    main()

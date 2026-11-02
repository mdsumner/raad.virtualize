"""oisst_sources.py -- the OISST v2.1 daily file list, one source per date.

Lists the public NOAA bucket (S3 ListObjectsV2 over HTTPS, anonymous; no GDAL
needed) and prints one source per date in date order: the final file, or
with --preliminary the preliminary file of a date that has no final file yet.
NOAA keeps preliminary files beside the final ones.

With --mirror DIR (a local copy holding the YYYYMM/ folders, such as the raad
collection), a date whose file in DIR has the same name and the same size as
the bucket object is read from DIR; any other date is read from the bucket.
The harvest then reads local files, and run.sh remaps DIR back to the bucket
URL at publish. Byte offsets are only valid if the two copies are the same
file, so size is the gate here and verify-published (which reads the
published forms from the bucket) is the check; --md5 also compares the MD5 of
each local file with the bucket ETag (reads every local file).

Usage:
  python oisst_sources.py [--months 198109,198110] [--preliminary]
                          [--mirror DIR [--md5]] > sources.txt
"""
import argparse
import hashlib
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BUCKET = "noaa-cdr-sea-surface-temp-optimum-interpolation-pds"
ROOT = "data/v2.1/avhrr"
URL = f"https://{BUCKET}.s3.amazonaws.com"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
NAME = re.compile(r"(\d{6})/(oisst-avhrr-v02r01\.(\d{8})(_preliminary)?\.nc)$")


def listing(prefix):
    """(key, size, etag) of every object under prefix."""
    tok = None
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if tok:
            q["continuation-token"] = tok
        with urllib.request.urlopen(f"{URL}/?{urllib.parse.urlencode(q)}", timeout=60) as r:
            doc = ET.fromstring(r.read())
        for c in doc.findall("s:Contents", NS):
            yield (c.find("s:Key", NS).text, int(c.find("s:Size", NS).text),
                   c.find("s:ETag", NS).text.strip('"'))
        t = doc.find("s:NextContinuationToken", NS)
        if t is None:
            return
        tok = t.text


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--months", default="", help="YYYYMM folders, comma or space separated (default all)")
    ap.add_argument("--preliminary", action="store_true",
                    help="add the preliminary file of dates with no final file")
    ap.add_argument("--mirror", help="local directory holding the YYYYMM/ folders")
    ap.add_argument("--md5", action="store_true", help="also compare local MD5 with the bucket ETag")
    a = ap.parse_args()
    months = [m for m in re.split(r"[,\s]+", a.months) if m]
    prefixes = [f"{ROOT}/{m}/" for m in months] or [f"{ROOT}/"]
    final, prel = {}, {}
    for p in prefixes:
        for key, size, etag in listing(p):
            m = NAME.search(key)
            if m:
                (prel if m.group(4) else final)[m.group(3)] = (m.group(1), m.group(2), size, etag)
    pick = dict(final)
    if a.preliminary:
        pick.update({d: v for d, v in prel.items() if d not in final})
    if not pick:
        sys.exit("oisst_sources: no files listed")
    local = remote = 0
    why = {}
    for d in sorted(pick):
        month, name, size, etag = pick[d]
        src = f"/vsicurl/{URL}/{ROOT}/{month}/{name}"
        if a.mirror:
            path = os.path.join(a.mirror, month, name)
            try:
                st = os.stat(path).st_size
            except OSError:
                st = None
            if st is None:
                why["missing"] = why.get("missing", 0) + 1
            elif st != size:
                why["size differs"] = why.get("size differs", 0) + 1
            elif a.md5 and "-" not in etag and md5(path) != etag:
                why["md5 differs"] = why.get("md5 differs", 0) + 1
            else:
                src = path
                local += 1
        remote += src.startswith("/vsicurl/")
        print(src)
    extra = (", ".join(f"{n} {k}" for k, n in sorted(why.items()))) if why else ""
    print(f"oisst_sources: {len(pick)} dates ({len(pick) - len(final) if a.preliminary else 0} preliminary), "
          f"{local} from {a.mirror or 'no mirror'}, {remote} from the bucket"
          f"{' (' + extra + ')' if extra else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()

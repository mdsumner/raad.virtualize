"""bremen_sources.py -- University of Bremen AMSR2 ASI daily netCDF file list.

Lists the public server's per-year folders (Apache directory index over
HTTPS, anonymous; no GDAL needed), for example

  https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/s3125/netcdf/2012/
      asi-AMSR2-s3125-20120801-v5.4.nc

and prints one source per date in date order. The index shows sizes rounded
(5.0M), so the exact size of every file comes from a HEAD request (threads,
--threads), and one ranged GET checks that the server answers byte ranges
(206) and that the file is HDF5 (netCDF4): byte references need both.

With --mirror DIR (a local copy whose layout below DIR matches the URL path
below --base, such as the raad collection
/rdsi/PUBLIC/raad/data/seaice.uni-bremen.de/data/amsr2/asi_daygrid_swath/
s3125/netcdf/), a date whose local file has the same name and the same size
as the server file is read from DIR; any other date is read from the server
(/vsicurl/). run.sh remaps DIR back to --base at publish. Byte offsets are
only valid if the two copies are the same file: Bremen reprocessed the whole
record on 2024-05-29 and 2018 again on 2026-04-25, so a mirror can hold
older files under the same names. Size is the gate here, and verify-published
(which reads the published forms from the server) is the check.

--offline lists the mirror only (no server requests, no size check); the
refs then point at the server unchecked. For a smoke test without network.

A count of dates per source (mirror, server) and of mirror files that differ
from the server goes to stderr.

Usage:
  python bremen_sources.py --base https://data.seaice.uni-bremen.de/amsr2/asi_daygrid_swath/s3125/netcdf \
      [--first 20120801] [--last 20261031] [--mirror DIR] [--offline] > sources.txt
"""
import argparse
import datetime as dt
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

NAME = r"asi-AMSR2-[ns]\d+-(\d{8})-v[0-9.]+\.nc"
HDF5_SIG = b"\x89HDF\r\n\x1a\n"


def get(url, timeout=60, tries=4, **headers):
    req = urllib.request.Request(url, headers=headers)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.headers, r.read()
        except OSError as e:
            # a 4xx answer (a year with no folder) is final
            if i == tries - 1 or 400 <= getattr(e, "code", 0) < 500:
                raise
            print(f"  {url}: {e}; retry", file=sys.stderr)


def head_size(url, tries=4):
    req = urllib.request.Request(url, method="HEAD")
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return int(r.headers["Content-Length"])
        except OSError as e:
            if i == tries - 1:
                raise
            print(f"  HEAD {url}: {e}; retry", file=sys.stderr)


def server_files(base, years, rx):
    """{date: url} from the year folders of the directory index."""
    out = {}
    for y in years:
        url = f"{base}/{y}/"
        try:
            _, _, body = get(url)
        except OSError as e:
            if getattr(e, "code", None) == 404:
                continue
            raise
        for name in sorted(set(re.findall(r'href="(' + rx.pattern + r')"', body.decode()))):
            name = name[0] if isinstance(name, tuple) else name
            out[rx.match(name).group(1)] = f"{url}{name}"
    return out


def mirror_files(mirror, years, rx):
    out = {}
    for y in years:
        d = os.path.join(mirror, str(y))
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            m = rx.fullmatch(name)
            if m:
                out[m.group(1)] = os.path.join(d, name)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="server URL of the folder holding the YYYY/ folders")
    ap.add_argument("--first", default="", help="first date YYYYMMDD (inclusive)")
    ap.add_argument("--last", default="", help="last date YYYYMMDD (inclusive)")
    ap.add_argument("--mirror", help="local directory holding the same YYYY/ folders")
    ap.add_argument("--offline", action="store_true", help="mirror only, no server requests")
    ap.add_argument("--threads", type=int, default=16)
    a = ap.parse_args()
    base = a.base.rstrip("/")
    rx = re.compile(NAME)
    y0 = int(a.first[:4]) if a.first else 2012  # AMSR2 starts 2012-07
    y1 = int(a.last[:4]) if a.last else dt.date.today().year
    years = range(y0, y1 + 1)
    keep = lambda d: (not a.first or d >= a.first) and (not a.last or d <= a.last)
    mirror = os.path.abspath(a.mirror).rstrip("/") if a.mirror else None

    local = {d: p for d, p in mirror_files(mirror, years, rx).items() if keep(d)} if mirror else {}
    if a.offline:
        if not mirror:
            sys.exit("bremen_sources: --offline needs --mirror")
        for d in sorted(local):
            print(local[d])
        print(f"bremen_sources: {len(local)} dates from the mirror (offline, not checked "
              f"against the server)", file=sys.stderr)
        return

    remote = {d: u for d, u in server_files(base, years, rx).items() if keep(d)}
    if not remote:
        sys.exit(f"bremen_sources: no files listed under {base}")
    first = remote[min(remote)]
    status, hdr, body = get(first, **{"Range": "bytes=0-7"})
    if status != 206:
        sys.exit(f"bremen_sources: {first} answered {status} to a byte range request, not 206")
    if body[:8] != HDF5_SIG:
        sys.exit(f"bremen_sources: {first} is not HDF5 (netCDF4): first bytes {body[:8]!r}")

    dates = sorted(remote)
    with ThreadPoolExecutor(a.threads) as ex:
        sizes = dict(zip(dates, ex.map(lambda d: head_size(remote[d]), dates)))
    n_local = differ = 0
    for d in dates:
        p = local.get(d)
        if p and os.path.getsize(p) == sizes[d]:
            print(p)
            n_local += 1
        else:
            differ += bool(p)
            print(f"/vsicurl/{remote[d]}")
    only_mirror = sorted(set(local) - set(remote))
    print(f"bremen_sources: {len(dates)} dates on the server, {n_local} read from the mirror, "
          f"{len(dates) - n_local} from the server ({differ} mirror files differ in size); "
          f"{len(only_mirror)} mirror-only dates left out"
          + (f" (first {only_mirror[0]})" if only_mirror else ""), file=sys.stderr)
    days = [dt.datetime.strptime(d, "%Y%m%d").date() for d in dates]
    gaps = [(p, q) for p, q in zip(days, days[1:]) if (q - p).days > 1]
    if gaps:
        print(f"bremen_sources: {len(gaps)} gaps, longest {max((q - p).days - 1 for p, q in gaps)} days",
              file=sys.stderr)


if __name__ == "__main__":
    main()

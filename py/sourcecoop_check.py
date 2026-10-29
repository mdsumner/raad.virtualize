"""sourcecoop_check.py -- check that a source.coop product takes the writes
that the publish step and Icechunk need.

  python py/sourcecoop_check.py ACCOUNT/PRODUCT [--prefix _write-check]

Writes under ACCOUNT/PRODUCT/PREFIX/<timestamp>/ through the data proxy
(https://data.source.coop, S3 API, path style) and removes what it wrote:

  put        a small object (GDAL /vsis3/, as `gdal vsi copy` does)
  multipart  a 120 MB object (GDAL switches to multipart above 50 MB)
  list       the prefix lists both objects
  public     the small object reads back over https with no credentials
  icechunk   an Icechunk repository created and committed twice directly
             on the proxy (conditional writes), then read anonymously
  delete     every object written is removed and the prefix lists empty

Credentials: the temporary key set from the product page ("View
Credentials") or `source-coop creds`, exported as AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN. They last one hour; GDAL keeps
the first set it reads, so run the check soon after exporting them.
"""
import argparse
import os
import sys
import time
import urllib.request

from osgeo import gdal

gdal.UseExceptions()
ENDPOINT = "data.source.coop"
results = []


def report(name, ok, detail=""):
    results.append((name, ok))
    print(f"{name:10s} {'ok' if ok else 'FAIL'} {detail}", flush=True)


def attempt(name, f):
    t0 = time.time()
    try:
        detail = f() or ""
        report(name, True, f"({time.time() - t0:.1f} s) {detail}")
    except Exception as e:  # report and carry on with the other checks
        report(name, False, f"({time.time() - t0:.1f} s) {e}")


def write_vsi(path, nbytes):
    f = gdal.VSIFOpenL(path, "wb")
    block = os.urandom(1 << 20)
    left = nbytes
    while left > 0:
        n = min(left, len(block))
        gdal.VSIFWriteL(block[:n], 1, n, f)
        left -= n
    if gdal.VSIFCloseL(f) != 0:
        raise RuntimeError("close failed")


def listing(vsi):
    # ReadDirRecursive returns None both for an empty prefix and for a failed
    # request, so tell them apart by the error state
    gdal.ErrorReset()
    out = gdal.ReadDirRecursive(vsi)
    if out is None and gdal.GetLastErrorMsg():
        raise RuntimeError(gdal.GetLastErrorMsg())
    return sorted(out or [])


def icechunk_check(bucket, prefix):
    import icechunk
    import numpy as np
    import zarr

    def storage(anonymous):
        creds = {"anonymous": True} if anonymous else {"from_env": True}
        return icechunk.s3_storage(bucket=bucket, prefix=prefix, endpoint_url=f"https://{ENDPOINT}",
                                   region=os.environ.get("AWS_REGION", "us-west-2"),
                                   force_path_style=True, **creds)

    repo = icechunk.Repository.create(storage(False))
    for i in range(2):
        s = repo.writable_session("main")
        g = zarr.open_group(s.store, mode="a")
        a = g.require_array("x", shape=(4,), chunks=(2,), dtype="i4")
        a[:] = np.arange(4) + i
        s.commit(f"commit {i}")
    ro = icechunk.Repository.open(storage(True))
    v = zarr.open_group(ro.readonly_session("main").store, mode="r")["x"][:]
    if list(v) != [1, 2, 3, 4]:
        raise RuntimeError(f"read back {list(v)}")
    return "2 commits, anonymous read back"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("product", help="ACCOUNT/PRODUCT")
    p.add_argument("--prefix", default="_write-check")
    p.add_argument("--skip", action="append", default=[], help="check to skip")
    a = p.parse_args()
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(k):
            sys.exit(f"export {k} (and AWS_SESSION_TOKEN) from the product's credentials")
    gdal.SetConfigOption("AWS_S3_ENDPOINT", ENDPOINT)
    gdal.SetConfigOption("AWS_VIRTUAL_HOSTING", "FALSE")
    gdal.SetConfigOption("AWS_HTTPS", "YES")
    gdal.SetConfigOption("AWS_REGION", os.environ.get("AWS_REGION", "us-west-2"))
    gdal.SetConfigOption("CPL_AWS_WEB_IDENTITY_ENABLE", "NO")

    bucket, _, product = a.product.strip("/").partition("/")
    run = time.strftime("%Y%m%dT%H%M%S")
    key = f"{product}/{a.prefix.strip('/')}/{run}"
    vsi = f"/vsis3/{bucket}/{key}"
    print("writing under", vsi, flush=True)

    if "put" not in a.skip:
        attempt("put", lambda: write_vsi(f"{vsi}/small.bin", 1024))
    if "multipart" not in a.skip:
        attempt("multipart", lambda: write_vsi(f"{vsi}/large.bin", 120 << 20))
    if "list" not in a.skip:
        attempt("list", lambda: str(listing(vsi)))
    if "public" not in a.skip and dict(results).get("put"):
        url = f"https://{ENDPOINT}/{bucket}/{key}/small.bin"
        attempt("public", lambda: f"{len(urllib.request.urlopen(url, timeout=30).read())} bytes from {url}")
    if "icechunk" not in a.skip:
        attempt("icechunk", lambda: icechunk_check(bucket, f"{key}/icechunk"))

    def delete():
        for name in listing(vsi):
            full = f"{vsi}/{name}"
            if gdal.VSIStatL(full) is not None and not gdal.VSIStatL(full).IsDirectory():
                gdal.Unlink(full)
        gdal.VSICurlClearCache()
        left = listing(vsi)
        if left:
            raise RuntimeError(f"{len(left)} entries left: {left[:5]}")
    if "delete" not in a.skip:
        attempt("delete", delete)

    bad = [n for n, ok in results if not ok]
    print("\nall checks passed" if not bad else f"\nfailed: {' '.join(bad)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

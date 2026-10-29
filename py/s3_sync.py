"""s3_sync.py -- upload a local directory or file to an S3 prefix with obstore.

  python py/s3_sync.py LOCAL /vsis3/BUCKET/PREFIX [--delete] [--workers N]

The publish step for targets that reject GDAL's request signing (the
source.coop data proxy answers GDAL /vsis3/ writes with "missing
SignedHeaders"). LOCAL is a directory (synced under PREFIX) or a file
(written to PREFIX itself). Every local file is uploaded; files larger than
the multipart threshold go up in parts. --delete removes objects under
PREFIX that have no local counterpart (directory mode only).

Connection settings come from the same environment as GDAL: AWS_S3_ENDPOINT,
AWS_HTTPS, AWS_VIRTUAL_HOSTING, AWS_REGION, and the credentials
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN.

Needs obstore (pip install obstore).
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import obstore
from obstore.store import S3Store


def store_for(vsis3):
    if not vsis3.startswith("/vsis3/"):
        sys.exit("s3_sync: target must be /vsis3/BUCKET/PREFIX")
    bucket, _, prefix = vsis3[len("/vsis3/"):].strip("/").partition("/")
    env = os.environ
    cfg = {"region": env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1",
           "virtual_hosted_style_request": env.get("AWS_VIRTUAL_HOSTING", "TRUE").upper()
           not in ("NO", "FALSE", "OFF")}
    ep = env.get("AWS_S3_ENDPOINT")
    if ep:
        http = env.get("AWS_HTTPS", "YES").upper() in ("NO", "FALSE", "OFF")
        cfg["endpoint"] = ep if "://" in ep else ("http://" if http else "https://") + ep
    for k, c in (("AWS_ACCESS_KEY_ID", "access_key_id"), ("AWS_SECRET_ACCESS_KEY", "secret_access_key"),
                 ("AWS_SESSION_TOKEN", "session_token")):
        if env.get(k):
            cfg[c] = env[k]
    opts = {"allow_http": True} if cfg.get("endpoint", "").startswith("http://") else {}
    return S3Store(bucket, prefix=prefix or None, config=cfg, client_options=opts), prefix


def local_files(src):
    if os.path.isfile(src):
        return [(src, "")]
    out = []
    for root, _, files in os.walk(src):
        for f in files:
            full = os.path.join(root, f)
            out.append((full, os.path.relpath(full, src).replace(os.sep, "/")))
    return sorted(out, key=lambda x: x[1])


def remote_files(store):
    return {o["path"]: o["size"] for batch in obstore.list(store) for o in batch}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("src")
    p.add_argument("dest", help="/vsis3/BUCKET/PREFIX")
    p.add_argument("--delete", action="store_true", help="remove remote objects with no local file")
    p.add_argument("--workers", type=int, default=8)
    a = p.parse_args()

    single = os.path.isfile(a.src)
    if single:  # a file: write to the prefix itself, from a store one level up
        parent, _, name = a.dest.rstrip("/").rpartition("/")
        store, _ = store_for(parent)
        files = [(a.src, name)]
    else:
        store, _ = store_for(a.dest)
        files = local_files(a.src)

    t0 = time.time()
    nbytes = sum(os.path.getsize(f) for f, _ in files)

    def put(item):
        f, key = item
        obstore.put(store, key, open(f, "rb"))  # multipart above obstore's threshold
        return key

    with ThreadPoolExecutor(a.workers) as ex:
        for i, key in enumerate(ex.map(put, files), 1):
            if i % 200 == 0 or i == len(files):
                print(f"s3_sync: {i}/{len(files)} {key}", flush=True)
    print(f"s3_sync: {len(files)} files, {nbytes / 1e6:.1f} MB to {a.dest} in {time.time() - t0:.1f} s")

    if a.delete and not single:
        keep = {k for _, k in files}
        stale = [k for k in remote_files(store) if k not in keep]
        if stale:
            obstore.delete(store, stale)
        print(f"s3_sync: removed {len(stale)} stale objects")


if __name__ == "__main__":
    main()

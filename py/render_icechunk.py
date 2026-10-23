"""render_icechunk.py -- step 5: flat refs store -> Icechunk virtual store.

Reads the flat refs store written by R/render.R (arrays.json beside
refs_<array>.parquet) and writes a local Icechunk repository in which every
present chunk is a virtual reference (url, offset, length) to the source
bytes, coordinates are small materialised arrays, and absent chunks are
left unwritten (they read as the fill value).

Usage:
  python render_icechunk.py FLAT_DIR REPO_DIR [--target public] [--batch 200000]
                            [--commit-every 1000000] [--split 365]

--target picks the remap rules in arrays.json that turn the verbatim
sources into URLs Icechunk can fetch (https://, s3://, or file:// for a
local path). One virtual chunk container is registered per scheme+host
(or bucket), with anonymous access; edit `container_for` for credentials.

Manifests are split every --split chunks along the first axis and the
session is committed every --commit-every refs, so the pending change set and
each commit stay bounded: the 22.8M refs of the GHRSST MUR daily series in one
session or one manifest need more than 14 GB.

Zarr v2 codec ids map to Zarr v3: imagecodecs_delta (array to array, TIFF
PREDICTOR=2; needs imagecodecs, and so does every reader), then bytes (dtype
byte order), then numcodecs.shuffle, then numcodecs.zlib / gzip / zstd.
Anything else stops.
"""
import argparse
import json
import os
import shutil
import sys
import time
from urllib.parse import urlparse

import icechunk
import numpy as np
import pyarrow.parquet as pq
import zarr
from zarr.codecs import numcodecs as nc3
from zarr.codecs import BytesCodec


def remap_rules(doc, target):
    if not target:
        return []
    rules = [(r["prefix"], r["replacement"]) for r in doc.get("remap", []) if r["target"] == target]
    if not rules:
        sys.exit(f"no remap rules for target {target!r} in arrays.json")
    return sorted(rules, key=lambda r: -len(r[0]))


def resolve(path, rules):
    for prefix, rep in rules:
        if path.startswith(prefix):
            path = rep + path[len(prefix):]
            break
    if path.startswith("/vsi"):
        sys.exit(f"{path}: still a GDAL /vsi path after remap; pick a --target that gives a URL")
    if path.startswith("/"):
        path = "file://" + path
    return path


def container_for(url):
    u = urlparse(url)
    if u.scheme in ("http", "https"):
        return f"{u.scheme}://{u.netloc}/", icechunk.http_store(), icechunk.credentials.HttpAccess
    if u.scheme == "s3":
        return (f"s3://{u.netloc}/", icechunk.s3_store(region=os.environ.get("AWS_REGION", "us-east-1")),
                icechunk.s3_anonymous_credentials())
    if u.scheme == "file":
        d = os.path.dirname(u.path).rstrip("/") + "/"
        return "file://" + d, icechunk.local_filesystem_store(d), icechunk.credentials.LocalFileSystemAccess
    sys.exit(f"{url}: no virtual chunk container for scheme {u.scheme!r}")


def v3_codecs(row):
    dt = np.dtype(row["dtype"])
    endian = "big" if dt.byteorder == ">" else "little"
    codec = row.get("codec") or {}
    out, pre = [], []
    for f in codec.get("filters") or []:
        if f["id"] == "shuffle":
            out.append(nc3.Shuffle(elementsize=int(f.get("elementsize", dt.itemsize))))
        elif f["id"] == "imagecodecs_delta":
            from imagecodecs.zarr import Delta, register_codecs
            register_codecs()
            pre.append(Delta(axis=int(f.get("axis", -1)), dist=int(f.get("dist", 1))))
        else:
            sys.exit(f"{row['array']}: unsupported filter {f}")
    c = codec.get("compressor")
    if c:
        if c["id"] == "zlib":
            out.append(nc3.Zlib(level=int(c.get("level", 1))))
        elif c["id"] == "gzip":
            out.append(nc3.GZip(level=int(c.get("level", 1))))
        elif c["id"] == "zstd":
            out.append(nc3.Zstd(level=int(c.get("level", 1))))
        else:
            sys.exit(f"{row['array']}: unsupported compressor {c}")
    return pre, BytesCodec(endian=endian) if dt.itemsize > 1 else BytesCodec(), out


def fill_of(row):
    if row.get("fill") is None:
        return None
    v = float(row["fill"])
    return int(v) if np.dtype(row["dtype"]).kind in "iu" else v


def coord_values(row):
    n = row["shape"][0]
    if row["storage"] == "affine":
        a = row["affine"]
        return a["start"] + a["step"] * np.arange(n, dtype="f8")
    return np.asarray(row["values"], dtype="f8")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("flat")
    p.add_argument("repo")
    p.add_argument("--target", default="public")
    p.add_argument("--batch", type=int, default=200_000)
    p.add_argument("--commit-every", type=int, default=1_000_000)
    p.add_argument("--split", type=int, default=365,
                   help="chunks along the first axis per manifest (0: no splitting)")
    a = p.parse_args()

    doc = json.load(open(os.path.join(a.flat, "arrays.json")))
    if not doc["format_version"].startswith("mdim-refs/"):
        sys.exit("not an mdim-refs flat store")
    rules = remap_rules(doc, a.target)
    rows = doc["arrays"]

    # containers from the distinct source prefixes of every referenced array
    containers, auth = {}, {}
    for r in rows:
        if r["storage"] != "referenced":
            continue
        t = pq.read_table(os.path.join(a.flat, f"refs_{r['array']}.parquet"), columns=["path"])
        for path in set(x for x in t.column("path").to_pylist() if x):
            prefix, store, cred = container_for(resolve(path, rules))
            containers[prefix] = store
            auth[prefix] = cred
    cfg = icechunk.RepositoryConfig.default()
    if a.split > 0:
        cfg.manifest = icechunk.ManifestConfig(splitting=icechunk.ManifestSplittingConfig.from_dict(
            {icechunk.ManifestSplitCondition.AnyArray(): {icechunk.ManifestSplitDimCondition.Axis(0): a.split}}))
    for prefix, store in containers.items():
        cfg.set_virtual_chunk_container(icechunk.VirtualChunkContainer(prefix, store))
    shutil.rmtree(a.repo, ignore_errors=True)
    storage = icechunk.local_filesystem_storage(a.repo)
    repo = icechunk.Repository.create(storage, config=cfg, authorize_virtual_chunk_access=auth)
    session = repo.writable_session("main")
    store = session.store
    root = zarr.open_group(store, mode="w", attributes=dict(doc.get("meta") or {}))

    t0 = time.time()
    coords = [r for r in rows if r["storage"] != "referenced"]
    for r in coords:
        v = coord_values(r).astype(np.dtype(r["dtype"]).newbyteorder("="))
        z = root.create_array(r["array"], shape=v.shape, chunks=v.shape, dtype=v.dtype,
                              dimension_names=r["dims"], attributes=r.get("attrs") or {},
                              fill_value=None)
        z[:] = v
    nref, pending, ncommit = 0, 0, 0
    for r in rows:
        if r["storage"] != "referenced":
            continue
        pre, ser, comp = v3_codecs(r)
        attrs = dict(r.get("attrs") or {})
        attrs.pop("_FillValue", None)
        fill = fill_of(r)
        if fill is not None:
            attrs["_FillValue"] = fill  # xarray masks on this attribute for Zarr v3
        root.create_array(r["array"], shape=r["shape"], chunks=r["chunks"],
                          dtype=np.dtype(r["dtype"]).newbyteorder("="),
                          serializer=ser, compressors=comp, filters=pre or None,
                          fill_value=fill if fill is not None else 0,
                          dimension_names=r["dims"], attributes=attrs)
        n = len(r["dims"])
        pf = pq.ParquetFile(os.path.join(a.flat, f"refs_{r['array']}.parquet"))
        cols = [f"dim_{i}" for i in range(n)] + ["present", "path", "offset", "size"]
        for b in pf.iter_batches(batch_size=a.batch, columns=cols):
            d = b.to_pydict()
            specs = [icechunk.VirtualChunkSpec(index=[d[f"dim_{i}"][j] for i in range(n)],
                                               location=resolve(d["path"][j], rules),
                                               offset=d["offset"][j], length=d["size"][j])
                     for j in range(b.num_rows) if d["present"][j] == 1 and d["path"][j]]
            failed = store.set_virtual_refs(r["array"], specs, validate_containers=True)
            if failed:
                sys.exit(f"{r['array']}: {len(failed)} refs rejected, first {failed[:3]}")
            nref += len(specs)
            pending += len(specs)
            if pending >= a.commit_every:
                snap = session.commit(f"mdim-refs flat store refs to {nref}")
                session = repo.writable_session("main")
                store = session.store
                root = zarr.open_group(store, mode="r+")
                pending, ncommit = 0, ncommit + 1
        print(f"  {r['array']}: shape {r['shape']} chunks {r['chunks']}", file=sys.stderr)
    if pending or not ncommit:  # a batch commit may already hold every ref
        snap = session.commit(f"mdim-refs flat store {os.path.abspath(a.flat)}, target {a.target}")
        ncommit += 1
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(a.repo) for f in fs)
    print(f"icechunk: {nref} virtual refs, {len(coords)} coords, containers {sorted(containers)}, "
          f"snapshot {snap} ({ncommit} commits), {size / 1e6:.1f} MB, {time.time() - t0:.1f} s", file=sys.stderr)


if __name__ == "__main__":
    main()

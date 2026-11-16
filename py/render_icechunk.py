"""render_icechunk.py -- step 5: flat refs store -> Icechunk virtual store.

Reads the flat refs store written by R/render.R (arrays.json beside
refs_<array>.parquet) and writes a local Icechunk repository in which every
present chunk is a virtual reference (url, offset, length) to the source
bytes, coordinates are small materialised arrays, and absent chunks are
left unwritten (they read as the fill value).

Usage:
  python render_icechunk.py FLAT_DIR REPO_DIR [--target public] [--batch 200000]
                            [--commit-every 1000000] [--split 365]
                            [--cache-refs 2000000] [--relocatable]

--target picks the remap rules in arrays.json that turn the verbatim
sources into URLs Icechunk can fetch (https://, s3://, or file:// for a
local path). One virtual chunk container is registered per scheme+host
(or bucket), with anonymous access; edit `container_for` for credentials.

Manifests are split every --split chunks along the first axis and the
session is committed every --commit-every refs, so the pending change set and
each commit stay bounded: the 22.8M refs of the GHRSST MUR daily series in one
session or one manifest need more than 14 GB.

The repository is rebuilt from scratch on every run, so the default split
(365) suits this one-shot render. The split is stored in the repository
config and applies to later commits too: a repository that is then extended
one append unit at a time (a day along time) should be rendered with --split
set to that unit. Over one year of daily commits on the GHRSST MUR COGs,
manifests measured 22 MB with a 1-day split, 116 MB with 30 days and 1.84 GB
with 365 days (wxylib/design m16).

While writing, the repository is reopened with an ingest-only cache
(--cache-refs chunk refs, two snapshots) so memory stays flat across many
commits; it is not saved to the repository config, so readers keep the
defaults. The split and cache choices follow the GOES-16 ingest in
Earthmover's icechunk-datacube-ingestion agent skill
(https://github.com/earth-mover/agent-skills/tree/main/icechunk-datacube-ingestion,
notebook https://gist.github.com/TomNicholas/6e908090583c3c4bbed1a305ac8c3bfd).
That skill calls kerchunk deprecated; here it stays an output, because GDAL
and other non-Python readers need it.

--relocatable writes every ref under a remap root as a relative
vcc://<root>/<rest> location against a named virtual chunk container
(Icechunk named containers), instead of an absolute URL. The roots are the
distinct verbatim `prefix` values of the remap rules in arrays.json, across
all targets; a rule's optional `root` field names one, else the name is a
slug of the prefix (/g/data/gb6/ -> g-data-gb6). For the chosen --target a
root's container prefix is that target's replacement (or the root itself
when the target has no rule for it). A reader elsewhere reopens the
repository with a container of the same name and its own prefix and store,
for example file:///g/data/gb6/ on NCI, and reads in place with no rewrite.
The root group attribute `byterefs_roots` lists, per root, its verbatim
prefix and its prefix under every target. Sources under no root stay
absolute. Readers that ignore container names cannot resolve vcc:// refs.

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

# byterefs decision 0003: mdim-refs/0.2 is the same layout, read until byterefs/0.2
FORMATS_READ = ("byterefs/0.1", "mdim-refs/0.2")


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


def root_name(rule_prefix, given=None):
    if given:
        return given
    slug = "".join(c if c.isalnum() else "-" for c in rule_prefix.split("://")[-1]).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "root"


def remap_roots(doc, target):
    """Named roots for --relocatable: {name: (verbatim_prefix, url_prefix)}
    for `target`, plus the per-target table written to `byterefs_roots`."""
    rules = doc.get("remap", [])
    roots, table = {}, {}
    for pre in sorted({r["prefix"] for r in rules}, key=len, reverse=True):
        given = next((r.get("root") for r in rules if r["prefix"] == pre and r.get("root")), None)
        name = root_name(pre, given)
        if name in roots:
            sys.exit(f"remap root name {name!r} used by two prefixes; name them with `root`")
        by_target = {r["target"]: r["replacement"] for r in rules if r["prefix"] == pre}
        url = resolve(by_target.get(target, pre), [])
        if not url.endswith("/"):
            sys.exit(f"remap root {pre!r}: prefix for target {target!r} ({url}) must end in '/'")
        roots[name] = (pre, url)
        table[name] = {"prefix": pre, "targets": by_target}  # as written in arrays.json
    return roots, table


def relative_location(source, roots):
    """vcc://<name>/<rest> for a verbatim source under a root, else None."""
    for name, (pre, _) in roots.items():  # longest prefix first
        if source.startswith(pre):
            return f"vcc://{name}/{source[len(pre):]}"
    return None


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
            register_codecs(verbose=False)
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


def json_safe(x):
    """X with non-finite floats as the strings "NaN", "Infinity", "-Infinity"
    (the Zarr spelling): attributes are written as JSON, which has no NaN."""
    if isinstance(x, float) and not np.isfinite(x):
        return "NaN" if np.isnan(x) else ("Infinity" if x > 0 else "-Infinity")
    if isinstance(x, dict):
        return {k: json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_safe(v) for v in x]
    return x


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
    p.add_argument("--target", default=None,
                   help="remap target (default: meta.default_target, else public)")
    p.add_argument("--batch", type=int, default=200_000)
    p.add_argument("--commit-every", type=int, default=1_000_000)
    p.add_argument("--split", type=int, default=365,
                   help="chunks along the first axis per manifest (0: no splitting)")
    p.add_argument("--relocatable", action="store_true",
                   help="write refs under remap roots as vcc://<root>/... against named containers")
    p.add_argument("--cache-refs", type=int, default=2_000_000,
                   help="chunk refs held in the write-time manifest cache (0: icechunk default)")
    a = p.parse_args()

    doc = json.load(open(os.path.join(a.flat, "arrays.json")))
    if doc.get("format_version") not in FORMATS_READ:
        sys.exit(f"not a byterefs flat store: format_version {doc.get('format_version')!r}")
    if a.target is None:
        a.target = doc.get("meta", {}).get("default_target", "public")
    rules = remap_rules(doc, a.target)
    rows = doc["arrays"]

    roots, roots_table = remap_roots(doc, a.target) if a.relocatable else ({}, {})
    names = {}  # url_prefix -> container name
    for name, (_, url) in roots.items():
        names[url] = name

    def location(path):
        if roots:
            rel = relative_location(path, roots)
            if rel:
                return rel
        return resolve(path, rules)

    # containers from the distinct source prefixes of every referenced array
    containers, auth = {}, {}
    for r in rows:
        if r["storage"] != "referenced":
            continue
        t = pq.read_table(os.path.join(a.flat, f"refs_{r['array']}.parquet"), columns=["path"])
        for path in set(x for x in t.column("path").to_pylist() if x):
            rel = relative_location(path, roots) if roots else None
            if rel:
                name = rel[len("vcc://"):].split("/", 1)[0]
                url = roots[name][1]
                _, store, cred = container_for(url + "x")
                containers[url] = store
            else:
                url, store, cred = container_for(resolve(path, rules))
                containers[url] = store
            auth[url] = cred
    cfg = icechunk.RepositoryConfig.default()
    if a.split > 0:
        cfg.manifest = icechunk.ManifestConfig(splitting=icechunk.ManifestSplittingConfig.from_dict(
            {icechunk.ManifestSplitCondition.AnyArray(): {icechunk.ManifestSplitDimCondition.Axis(0): a.split}}))
    for prefix, store in containers.items():
        cfg.set_virtual_chunk_container(icechunk.VirtualChunkContainer(prefix, store, name=names.get(prefix)))
    shutil.rmtree(a.repo, ignore_errors=True)
    storage = icechunk.local_filesystem_storage(a.repo)
    repo = icechunk.Repository.create(storage, config=cfg, authorize_virtual_chunk_access=auth)
    if a.cache_refs > 0:
        # write-time only: keep the current and previous snapshot and about
        # two commits of refs, so cached manifests do not pile up across
        # commits; reopen does not save it to the repository config
        cfg.caching = icechunk.CachingConfig(num_snapshot_nodes=2, num_chunk_refs=a.cache_refs)
        repo = repo.reopen(config=cfg, authorize_virtual_chunk_access=auth)
    session = repo.writable_session("main")
    store = session.store
    attrs0 = dict(doc.get("meta") or {})
    if roots_table:
        attrs0["byterefs_roots"] = roots_table
    root = zarr.open_group(store, mode="w", attributes=attrs0)

    t0 = time.time()
    coords = [r for r in rows if r["storage"] != "referenced"]
    for r in coords:
        v = coord_values(r).astype(np.dtype(r["dtype"]).newbyteorder("="))
        z = root.create_array(r["array"], shape=v.shape, chunks=v.shape, dtype=v.dtype,
                              dimension_names=r["dims"], attributes=json_safe(r.get("attrs") or {}),
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
        # xarray masks on this attribute for Zarr v3. A NaN fill is left out:
        # zarr writes attributes with bare NaN tokens, which is not JSON and
        # which Icechunk rejects ("bad metadata"), and NaN needs no mask.
        if fill is not None and np.isfinite(fill):
            attrs["_FillValue"] = fill
        attrs = json_safe(attrs)
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
                                               location=location(d["path"][j]),
                                               offset=d["offset"][j], length=d["size"][j])
                     for j in range(b.num_rows) if d["present"][j] == 1 and d["path"][j]]
            failed = store.set_virtual_refs(r["array"], specs, validate_containers=True)
            if failed:
                sys.exit(f"{r['array']}: {len(failed)} refs rejected, first {failed[:3]}")
            nref += len(specs)
            pending += len(specs)
            if pending >= a.commit_every:
                snap = session.commit(f"byterefs flat store refs to {nref}")
                session = repo.writable_session("main")
                store = session.store
                root = zarr.open_group(store, mode="r+")
                pending, ncommit = 0, ncommit + 1
        print(f"  {r['array']}: shape {r['shape']} chunks {r['chunks']}", file=sys.stderr)
    if pending or not ncommit:  # a batch commit may already hold every ref
        snap = session.commit(f"byterefs flat store {os.path.abspath(a.flat)}, target {a.target}")
        ncommit += 1
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(a.repo) for f in fs)
    print(f"icechunk: {nref} virtual refs, {len(coords)} coords, containers {sorted(containers)}, "
          f"snapshot {snap} ({ncommit} commits), {size / 1e6:.1f} MB, {time.time() - t0:.1f} s", file=sys.stderr)


if __name__ == "__main__":
    main()

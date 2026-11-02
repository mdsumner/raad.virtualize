"""check_kerchunk_parquet.py -- do fastparquet and pyarrow read the same refs?

fsspec's LazyReferenceMapper reads kerchunk Parquet refs with
engine="fastparquet" by default, and ReferenceFileSystem(fo=<dir>) gives no
way to change that. When a refs.<n>.parq file was written by arrow with
dictionary encoding on the `path` column and the dictionary outgrew arrow's
1 MiB dictionary page limit, arrow fell back to plain encoding for the rest of
the column chunk, and fastparquet (2026.5.0, 2026.9.0) returns null for every
path after the fallback (row 8192 in the OISST store). zarr then sees "no
such chunk" and xarray returns fill values without an error.

The writer fix is use_dictionary = FALSE (R/mdimrefs_pipeline.R). This script
checks a rendered or published kerchunk directory:

  * pyarrow is the truth for the number of non-null paths per file;
  * if fastparquet is installed, its `path` column must match pyarrow's
    exactly (nulls and values);
  * without fastparquet, a file is flagged "at risk" when `path` has a
    dictionary page and its distinct values exceed the arrow limit, which is
    the condition that triggers the fallback.

Usage:
  python check_kerchunk_parquet.py KERCHUNK_DIR_OR_URL [--sample N] [--json]

KERCHUNK_DIR_OR_URL is a local kerchunk/ directory or an http(s) URL of one
(anonymous). The files are found from .zmetadata (record_size and each
array's shape and chunks), so no listing is needed. --sample N checks only N
evenly spaced files per array (always the first and the last). Exit status 1
when any file is unreadable, mismatched or at risk.
"""
import argparse
import io
import json
import math
import os
import sys
import urllib.request

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

try:
    import fastparquet
except ImportError:  # the structural check still runs
    fastparquet = None

# arrow's default dictionary_pagesize_limit (C++ WriterProperties, R and pyarrow)
DICT_LIMIT = 1024 * 1024


def fetch(base, rel):
    if base.startswith(("http://", "https://")):
        with urllib.request.urlopen(base.rstrip("/") + "/" + rel, timeout=120) as r:
            return r.read()
    with open(os.path.join(base, rel), "rb") as f:
        return f.read()


def ref_files(zmeta):
    """{array: [refs.<n>.parq, ...]} for every array with chunk refs."""
    meta, rs = zmeta["metadata"], zmeta["record_size"]
    out = {}
    for key, za in meta.items():
        if not key.endswith("/.zarray"):
            continue
        name = key[: -len("/.zarray")]
        za = json.loads(za) if isinstance(za, str) else za
        n = math.prod(math.ceil(s / c) for s, c in zip(za["shape"], za["chunks"])) if za["shape"] else 1
        out[name] = [f"{name}/refs.{i}.parq" for i in range(math.ceil(n / rs))]
    return out


def pick(files, sample):
    if not sample or len(files) <= sample:
        return files
    idx = sorted({round(i * (len(files) - 1) / (sample - 1)) for i in range(sample)}) if sample > 1 else [0]
    return [files[i] for i in idx]


def check_bytes(data):
    """One refs file: counts from pyarrow, fastparquet agreement, risk flag."""
    pf = pq.ParquetFile(io.BytesIO(data))
    path = pf.read(columns=["path"]).column("path")
    res = {"rows": len(path), "paths": len(path) - path.null_count,
           "row_groups": pf.metadata.num_row_groups}
    # the fallback condition, per row group (each has its own dictionary)
    col = pf.schema_arrow.get_field_index("path")
    risk = False
    start = 0
    for g in range(pf.metadata.num_row_groups):
        md = pf.metadata.row_group(g)
        part = path.slice(start, md.num_rows)
        start += md.num_rows
        if md.column(col).has_dictionary_page:
            u = pc.unique(part.drop_null() if part.null_count else part)
            dict_bytes = sum(len(s) for s in u.to_pylist()) + 4 * len(u)
            risk = risk or dict_bytes >= DICT_LIMIT * 0.9
    res["dictionary_at_risk"] = risk
    if fastparquet is not None:
        fp = fastparquet.ParquetFile(io.BytesIO(data)).to_pandas(columns=["path"])["path"]
        fp_paths = int(fp.notna().sum())
        res["fastparquet_paths"] = fp_paths
        ok = fp_paths == res["paths"]
        if ok:
            pa_vals = path.to_pylist()
            ok = all((v is None) if m else (v == f)
                     for v, f, m in zip(pa_vals, fp.tolist(), fp.isna().tolist()))
        res["fastparquet_same"] = ok
    return res


def check(base, sample=0, log=print):
    zmeta = json.loads(fetch(base, ".zmetadata"))
    report, bad = {}, 0
    for name, files in ref_files(zmeta).items():
        r = {"files": len(files), "checked": 0, "rows": 0, "paths": 0,
             "fastparquet_paths": None if fastparquet is None else 0,
             "mismatch": [], "at_risk": [], "unreadable": []}
        for rel in pick(files, sample):
            try:
                c = check_bytes(fetch(base, rel))
            except Exception as e:  # missing or corrupt file
                r["unreadable"].append(f"{rel}: {e}")
                continue
            r["checked"] += 1
            r["rows"] += c["rows"]
            r["paths"] += c["paths"]
            if fastparquet is not None:
                r["fastparquet_paths"] += c["fastparquet_paths"]
                if not c["fastparquet_same"]:
                    r["mismatch"].append(rel)
            if c["dictionary_at_risk"]:
                r["at_risk"].append(rel)
        # with fastparquet a mismatch is the failure; without, the risk flag
        failed = r["unreadable"] or r["mismatch"] or (fastparquet is None and r["at_risk"])
        bad += bool(failed)
        status = "FAIL" if failed else ("ok (dictionary, fastparquet agrees)" if r["at_risk"] else "ok")
        fpp = "" if fastparquet is None else f", fastparquet {r['fastparquet_paths']}"
        log(f"  {name}: {r['checked']}/{r['files']} files, paths pyarrow {r['paths']}{fpp}, "
            f"at risk {len(r['at_risk'])}, mismatched {len(r['mismatch'])}, "
            f"unreadable {len(r['unreadable'])}  {status}")
        for k in ("unreadable", "mismatch"):
            for x in r[k][:5]:
                log(f"    {k}: {x}")
        report[name] = r
    return report, bad


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("kerchunk", help="local kerchunk/ directory or http(s) URL of one")
    p.add_argument("--sample", type=int, default=0, help="files per array (0 = all)")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    a = p.parse_args()
    print(f"kerchunk refs check: {a.kerchunk} "
          f"(fastparquet {fastparquet.__version__ if fastparquet else 'not installed'}, "
          f"pyarrow {pa.__version__})")
    report, bad = check(a.kerchunk, a.sample)
    if a.json:
        print(json.dumps(report, indent=1))
    print("kerchunk refs check:", "FAIL" if bad else "ok")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

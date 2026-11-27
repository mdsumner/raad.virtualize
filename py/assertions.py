"""Assertion step: apply storecard assertion documents to a store.

An assertion (hypertidy/storecard ASSERTIONS.md, v0) is an evidenced claim
about a variable's grid: zarr-conventions `spatial:` and `proj:` keys in
`asserts`, with `crs_axes`, `evidence`, `by` and `status`. In raad.virtualize
an assertion is a render input, keyed to the dataset id and the variable
(`subject.dataset`, `subject.variable`), not to a published store's URL and
metadata digest: the published forms are outputs of the render, so their
digest changes when the assertion is written into them.

    python py/assertions.py apply --store store.sqlite --plan plan.vrt DIR

reads every DIR/*.json, checks each against the store and the plan, and
records the result in the store's meta table (key `assertions`, a JSON
list), which every emitter reads (R/mdimrefs_pipeline.R mr_array_list:
Zarr attributes of the flat, kerchunk and Icechunk forms, the mdim VRT
<SRS>; R/stac.R: item proj:* and the collection's rv:assertions). A
missing or empty DIR removes the key, so a store built without assertions
renders as before.

Checks, each fatal:
- the document follows v0 (kind grid, asserts only spatial:/proj: keys,
  status proposed, settled or withdrawn);
- the variable is a data array of the store, spatial:dimensions are among
  its dimensions and spatial:shape matches their lengths;
- spatial:transform equals the transform restated from the store's 1-D
  coordinate arrays of those dimensions (cell corners), where the store has
  them, to 1e-6 of a cell;
- proj:code equals the EPSG code of the plan's <SRS> for the variable,
  where the plan has one (the assertion then restates the source; where
  the plan has none it supplies the CRS).

A withdrawn assertion is recorded with applied = false and written nowhere.

    python py/assertions.py import --dataset ID --out assertions/ID \
        [--url-base URL] STORECARD_DOC...

restates storecard documents (keyed to a published store) as documents of
this repository (keyed to the dataset id), one per variable.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import struct
import sys
import xml.etree.ElementTree as ET

GRID_KEYS = ("spatial:transform", "spatial:shape", "spatial:dimensions",
             "spatial:registration", "spatial:transform_type",
             "proj:code", "proj:wkt2", "proj:projjson")
STATUSES = ("proposed", "settled", "withdrawn")
TOL = 1e-6  # of a cell


def digest(doc):
    """sha256 of the document as canonical JSON (sorted keys, no spaces)."""
    s = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(s.encode("ascii")).hexdigest()


def epsg_of(wkt):
    """EPSG code of a WKT2 or WKT1 string: the last ID[] or AUTHORITY[]."""
    if not wkt:
        return None
    m = re.findall(r'(?:ID|AUTHORITY)\["EPSG",\s*"?([0-9]+)"?\]', wkt)
    return f"EPSG:{m[-1]}" if m else None


def plan_srs(plan):
    """{array name: (SRS text, dataAxisToSRSAxisMapping)} from a plan VRT."""
    out = {}
    if not plan or not pathlib.Path(plan).exists():
        return out
    for arr in ET.parse(plan).getroot().iter("Array"):
        s = arr.find("SRS")
        if s is not None and s.text:
            out[arr.get("name")] = (s.text, s.get("dataAxisToSRSAxisMapping"))
    return out


def validate(doc, where):
    def bad(msg):
        sys.exit(f"assertion {where}: {msg}")
    if str(doc.get("assertion_version")) != "0":
        bad("assertion_version is not 0")
    if doc.get("kind") != "grid":
        bad(f"kind {doc.get('kind')!r}: only grid assertions are applied at render")
    if doc.get("status") not in STATUSES:
        bad(f"status {doc.get('status')!r} not one of {STATUSES}")
    sub = doc.get("subject") or {}
    if not sub.get("dataset") or not sub.get("variable"):
        bad("subject needs dataset and variable")
    a = doc.get("asserts") or {}
    extra = set(a) - set(GRID_KEYS)
    if extra:
        bad(f"asserts keys outside spatial:/proj: {sorted(extra)}")
    for k in ("spatial:transform", "spatial:shape", "spatial:dimensions"):
        if k not in a:
            bad(f"asserts lacks {k}")
    if not any(k in a for k in ("proj:code", "proj:wkt2", "proj:projjson")):
        bad("asserts states no CRS (proj:code, proj:wkt2 or proj:projjson)")
    if sorted(doc.get("crs_axes") or []) != ["x", "y"]:
        bad("crs_axes must be a permutation of x, y")


def _coord_values(row):
    """Values of a coordinate array from its store row, or None."""
    if row["storage"] == "affine":
        af = json.loads(row["affine"])
        n = json.loads(row["shape"])[0]
        return [af["start"] + af["step"] * i for i in range(n)]
    if row["storage"] == "inline" and row["values"] is not None:
        dt = row["dtype"]
        code = {"f8": "d", "f4": "f", "i8": "q", "i4": "i", "i2": "h", "u2": "H",
                "u4": "I", "u8": "Q", "i1": "b", "u1": "B"}.get(dt[1:])
        if code is None:
            return None
        end = ">" if dt.startswith(">") else "<"
        b = bytes(row["values"])
        return list(struct.unpack(f"{end}{len(b) // struct.calcsize(code)}{code}", b))
    return None


def _restated(v):
    """(corner, step) of regular 1-D values, or None."""
    if not v or len(v) < 2:
        return None
    step = (v[-1] - v[0]) / (len(v) - 1)
    if step == 0 or any(abs(v[i] - (v[0] + step * i)) > TOL * abs(step) * 10 for i in range(len(v))):
        return None
    return v[0] - step / 2, step


def check(doc, con, srs_by_array, where):
    sub, a = doc["subject"], doc["asserts"]
    var = sub["variable"]
    row = con.execute("SELECT * FROM arrays WHERE array = ?", (var,)).fetchone()
    if row is None or row["kind"] != "data":
        sys.exit(f"assertion {where}: {var!r} is not a data array of the store")
    dims, shape = json.loads(row["dims"]), json.loads(row["shape"])
    sd, ss = a["spatial:dimensions"], a["spatial:shape"]
    if not set(sd) <= set(dims):
        sys.exit(f"assertion {where}: spatial:dimensions {sd} not among {var} dims {dims}")
    got = [shape[dims.index(d)] for d in sd]
    if got != list(ss):
        sys.exit(f"assertion {where}: spatial:shape {ss}, store {got}")
    out = {"shape": "agrees"}
    # transform: x = a col + b row + c, y = d col + e row + f (cell corners)
    ta, tb, tc, td, te, tf = a["spatial:transform"]
    yd, xd = sd
    rs = {}
    for d in (xd, yd):
        c = con.execute("SELECT * FROM arrays WHERE array = ? AND kind = 'coord'", (d,)).fetchone()
        rs[d] = _restated(_coord_values(c)) if c is not None else None
    if rs[xd] and rs[yd]:
        (x0, dx), (y0, dy) = rs[xd], rs[yd]
        ok = (tb == 0 and td == 0 and abs(ta - dx) <= TOL * abs(dx) and abs(te - dy) <= TOL * abs(dy)
              and abs(tc - x0) <= TOL * abs(dx) and abs(tf - y0) <= TOL * abs(dy))
        if not ok:
            sys.exit(f"assertion {where}: spatial:transform {a['spatial:transform']} differs from "
                     f"the store's coordinates [{dx}, 0, {x0}, 0, {dy}, {y0}]")
        out["transform"] = "agrees with the store's 1-D coordinates"
    else:
        out["transform"] = "supplied (no regular 1-D coordinates in the store)"
    srs = srs_by_array.get(var)
    code = a.get("proj:code")
    if srs:
        pe = epsg_of(srs[0])
        if code and pe and pe != code:
            sys.exit(f"assertion {where}: proj:code {code}, plan <SRS> {pe}")
        out["crs"] = f"agrees with the plan <SRS> ({pe})" if pe else "plan <SRS> has no EPSG code"
    else:
        out["crs"] = "supplied (the plan has no <SRS>)"
    return out


def apply(store, plan, adir):
    con = sqlite3.connect(store)
    con.row_factory = sqlite3.Row
    files = sorted(pathlib.Path(adir).glob("*.json")) if adir and pathlib.Path(adir).is_dir() else []
    dataset = (con.execute("SELECT value FROM meta WHERE key = 'dataset'").fetchone() or [None])[0]
    srs = plan_srs(plan)
    recs = []
    for f in files:
        doc = json.loads(f.read_text())
        validate(doc, f.name)
        sub = doc["subject"]
        if dataset and not dataset.startswith(sub["dataset"]):
            sys.exit(f"assertion {f.name}: subject.dataset {sub['dataset']!r}, store {dataset!r}")
        applied = doc["status"] != "withdrawn"
        checks = check(doc, con, srs, f.name) if applied else {}
        recs.append({"id": f.stem, "variable": sub["variable"], "kind": doc["kind"],
                     "status": doc["status"], "digest": digest(doc), "applied": applied,
                     "asserts": doc["asserts"], "crs_axes": doc["crs_axes"],
                     "by": doc.get("by"), "derived_from": doc.get("derived_from"),
                     "checks": checks})
        print(f"assert: {f.name} {sub['variable']} {doc['status']}"
              + ("".join(f"\n  {k}: {v}" for k, v in checks.items()) if applied else " (not applied)"))
    vars_ = [r["variable"] for r in recs if r["applied"]]
    if len(vars_) != len(set(vars_)):
        sys.exit("assert: more than one applied assertion for a variable")
    with con:
        if recs:
            con.execute("INSERT INTO meta(key,value) VALUES('assertions',?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (json.dumps(recs, separators=(",", ":")),))
        else:
            con.execute("DELETE FROM meta WHERE key = 'assertions'")
            print(f"assert: no assertions in {adir}; the store carries none")
    con.close()


def import_storecard(src, dataset, out_dir, url=None):
    """A raad.virtualize assertion from a storecard document: the same
    asserts, crs_axes, evidence, by, made_at and status, with the subject
    keyed to the dataset id and variable and derived_from naming the
    storecard document and its subject."""
    d = json.loads(pathlib.Path(src).read_text())
    var = d["subject"]["variable"]
    out = {"assertion_version": d["assertion_version"], "kind": d["kind"],
           "subject": {"dataset": dataset, "variable": var},
           "asserts": d["asserts"], "crs_axes": d["crs_axes"], "evidence": d.get("evidence"),
           "by": d.get("by"), "made_at": d.get("made_at"), "status": d["status"],
           "derived_from": {"url": url or str(src), "subject": d["subject"]}}
    validate(out, src)
    f = pathlib.Path(out_dir) / f"{var}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1) + "\n")
    print(f"import: {src} -> {f}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("apply", help="check DIR/*.json against the store and record them in it")
    a.add_argument("--store", required=True)
    a.add_argument("--plan")
    a.add_argument("dir")
    m = sp.add_parser("import", help="restate storecard documents as assertions/<dataset>/<variable>.json")
    m.add_argument("--dataset", required=True)
    m.add_argument("--out", required=True, help="assertions/<dataset>")
    m.add_argument("--url-base", help="URL of the storecard assertions directory, for derived_from")
    m.add_argument("src", nargs="+")
    args = p.parse_args(argv)
    if args.cmd == "apply":
        apply(args.store, args.plan, args.dir)
    else:
        for s in args.src:
            url = f"{args.url_base.rstrip('/')}/{pathlib.Path(s).name}" if args.url_base else None
            import_storecard(s, args.dataset, args.out, url)


if __name__ == "__main__":
    main()

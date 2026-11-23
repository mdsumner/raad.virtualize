"""plan_concat.py -- mdim VRT plan that concatenates classic netCDF files
along a dimension with no indexing variable.

For collections of one file per platform whose arrays share a leading
dimension of a different size in each file (Argo-style profile files:
N_PROF profiles of N_LEVELS levels), which `gdal mdim mosaic` cannot join
because the dimension has no coordinate. Each requested array becomes one
global array whose leading dimension is the sum of the files' sizes, the
files placed in the order of the source list:

  <Source>
    <SourceFilename>FILE</SourceFilename>
    <SourceArray>/TEMP</SourceArray>
    <SourceSlab offset="0,0" count="n_i,1000" step="1,1"/>
    <DestSlab offset="N_0+..+N_{i-1},0"/>
  </Source>

<BlockSize> is one row of the leading axis and the whole of the others
(--block for another), so every file starts on a chunk boundary and the
harvest (py/harvest.py, engine cdf) references each row as one chunk. The
other dimensions must agree in every file that holds an array; a file
without an array leaves its rows unwritten (fill).

1D variables on the dimension (--inline: time, position, cycle number) are
small: they are read from every file and written into the plan as
<InlineValues>, so they become materialised arrays of the store rather
than one reference per element. A char variable is written as Byte. Two
derived arrays can be added: --index NAME, the position of each element's
file in the source list (the file names are its attribute source_names),
and --row NAME, the element's row within its file.

--extents FILE writes one row per source (source, west, south, east, north,
start, end, n, n_located) from the inline --lat, --lon and --time arrays,
for R/stac.R (STAC_EXTENTS). A position counts when both values are finite,
neither is the fill, |lat| <= 90, |lon| <= 360 and lat < --lat-max; the box
crosses the antimeridian (west > east) when that spans the positions in
less longitude.

Headers and inline variables are read through GDAL's virtual file system
(py/cdf.py); no file is opened with a netCDF library.

Usage:
  python plan_concat.py --sources sources.txt --dim N_PROF \\
    --array TEMP --array TEMP_ADJUSTED --inline JULD --inline LATITUDE \\
    --index tag --row row [--extents extents.tsv --lat LATITUDE --lon LONGITUDE \\
    --time JULD --lat-max 0] [--require-all] [--workers 16] plan.vrt
"""
import argparse
import csv
import datetime as dt
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdf  # noqa: E402

VRT_TYPE = {"|i1": "Int8", "|u1": "Byte", "|S1": "Byte", ">i2": "Int16", ">u2": "UInt16",
            ">i4": "Int32", ">u4": "UInt32", ">i8": "Int64", ">u8": "UInt64",
            ">f4": "Float32", ">f8": "Float64"}


def fmt(v, kind):
    if kind == "f":
        return "nan" if math.isnan(v) else f"{v:.17g}"
    return str(int(v))


def attr_xml(name, value, ind="      "):
    vals = value if isinstance(value, list) else [value]
    typ = "String" if isinstance(vals[0], str) else (
        "Int32" if all(isinstance(x, int) for x in vals) else "Float64")
    out = [f'{ind}<Attribute name="{escape(name)}">', f"{ind}  <DataType>{typ}</DataType>"]
    out += [f"{ind}  <Value>{escape(x) if typ == 'String' else fmt(x, 'f' if typ == 'Float64' else 'i')}</Value>"
            for x in vals]
    return out + [f"{ind}</Attribute>"]


def lon_span(lon):
    """(west, east) covering the longitudes in the least span; west > east
    when that crosses the antimeridian."""
    x = np.unique(((np.asarray(lon) + 180.0) % 360.0) - 180.0)
    if len(x) == 1:
        return float(x[0]), float(x[0])
    gaps = np.diff(np.concatenate([x, [x[0] + 360.0]]))
    k = int(np.argmax(gaps))
    if k == len(x) - 1:
        return float(x[0]), float(x[-1])
    return float(x[k + 1]), float(x[k])


def cf_times(v, units):
    """Datetimes of CF time values '<unit> since <origin>' (days, hours,
    minutes, seconds)."""
    unit, origin = [s.strip() for s in units.split("since", 1)]
    o = origin.replace("T", " ").replace("UTC", "").replace("Z", "").strip()
    base = dt.datetime.fromisoformat(o[:19] if len(o) > 10 else o + " 00:00:00")
    sec = {"day": 86400, "days": 86400, "hour": 3600, "hours": 3600, "minute": 60,
           "minutes": 60, "second": 1, "seconds": 1}[unit.lower()]
    return [base + dt.timedelta(seconds=float(t) * sec) for t in v]


def write_extents(path, sources, per, fills, time_units, lat_max=90.0):
    """One row per source (source, west, south, east, north, start, end, n,
    n_located) for R/stac.R STAC_EXTENTS. per: (lat, lon, time) arrays of
    each source; fills: their fill values. A position counts when both
    values are finite and not the fill, |lat| <= 90, |lon| <= 360 and
    lat < lat_max."""
    flat, flon, ftime = fills
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["source", "west", "south", "east", "north", "start", "end", "n", "n_located"])
        for s, (la, lo, t) in zip(sources, per):
            la, lo, t = (np.asarray(x, dtype="f8") for x in (la, lo, t))
            ok = (np.isfinite(la) & np.isfinite(lo) & (la != flat) & (lo != flon)
                  & (np.abs(la) <= 90) & (np.abs(lo) <= 360) & (la < lat_max))
            tok = np.isfinite(t) & (t != ftime)
            tt = cf_times(t[tok], time_units) if tok.any() else []
            if ok.any():
                we = lon_span(lo[ok])
                box = [f"{we[0]:.6g}", f"{la[ok].min():.6g}", f"{we[1]:.6g}", f"{la[ok].max():.6g}"]
            else:
                box = ["", "", "", ""]
            w.writerow([s] + box + ([min(tt).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    max(tt).strftime("%Y-%m-%dT%H:%M:%SZ")] if tt else ["", ""])
                       + [len(t), int(ok.sum())])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True)
    ap.add_argument("--dim", required=True, help="the dimension to concatenate along")
    ap.add_argument("--array", action="append", default=[], help="array to concatenate (repeatable)")
    ap.add_argument("--inline", action="append", default=[], help="1D variable to inline (repeatable)")
    ap.add_argument("--index", help="name of a derived array: the source of each element")
    ap.add_argument("--row", help="name of a derived array: the element's row in its source")
    ap.add_argument("--block", help="BlockSize of the arrays, comma separated (default one row)")
    ap.add_argument("--require-all", action="store_true",
                    help="fail when a source lacks a requested array (default: unwritten rows)")
    ap.add_argument("--extents", help="write per-source extents (TSV) for R/stac.R")
    ap.add_argument("--lat"), ap.add_argument("--lon"), ap.add_argument("--time")
    ap.add_argument("--lat-max", type=float, default=90.0,
                    help="positions at or north of this latitude are left out of the extents")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("vrt")
    a = ap.parse_args()
    if not a.array:
        sys.exit("plan_concat: give at least one --array")
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    with ThreadPoolExecutor(a.workers) as ex:
        heads = list(ex.map(cdf.read_header, sources))

    # dimension sizes: the concatenated one per source, the rest must agree
    n = []
    for s, h in zip(sources, heads):
        d = dict(h["dims"])
        if a.dim not in d:
            sys.exit(f"plan_concat: {s} has no dimension {a.dim}")
        n.append(h["numrecs"] if d[a.dim] == 0 else d[a.dim])
    start = np.concatenate([[0], np.cumsum(n)]).astype(int)
    total = int(start[-1])

    specs = {}
    for nm in a.array + a.inline:
        have = [(i, h["vars"][nm]) for i, h in enumerate(heads) if nm in h["vars"]]
        if not have:
            print(f"plan_concat: no source has {nm}; left out", file=sys.stderr)
            continue
        if a.require_all and len(have) < len(sources):
            sys.exit(f"plan_concat: {len(sources) - len(have)} sources lack {nm}, first "
                     f"{sources[next(i for i in range(len(sources)) if nm not in heads[i]['vars'])]}")
        v0 = have[0][1]
        if not v0["dims"] or v0["dims"][0] != a.dim:
            sys.exit(f"plan_concat: {nm} does not lead with {a.dim} ({v0['dims']})")
        if nm in a.inline and len(v0["dims"]) != 1:
            sys.exit(f"plan_concat: --inline {nm} has dims {v0['dims']}; only 1D variables are inlined")
        for i, v in have:
            if v["dims"] != v0["dims"] or v["shape"][1:] != v0["shape"][1:] or v["dtype"] != v0["dtype"]:
                sys.exit(f"plan_concat: {nm} in {sources[i]} is {v['dtype']} {v['dims']} {v['shape']}, "
                         f"in {sources[have[0][0]]} {v0['dtype']} {v0['dims']} {v0['shape']}")
        specs[nm] = (have, v0)

    a.array = [nm for nm in a.array if nm in specs]
    a.inline = [nm for nm in a.inline if nm in specs]
    dims = [(a.dim, total)]
    for nm in a.array:
        for d, sz in zip(specs[nm][1]["dims"][1:], specs[nm][1]["shape"][1:]):
            if d not in dict(dims):
                dims.append((d, sz))
            elif dict(dims)[d] != sz:
                sys.exit(f"plan_concat: dimension {d} is {sz} in {nm} but {dict(dims)[d]} elsewhere")

    lines = ["<VRTDataset>", '  <Group name="/">']
    lines += [f'    <Dimension name="{escape(d)}" size="{sz}"/>' for d, sz in dims]

    # inline 1D arrays: values from every source, fill where one lacks it
    values = {}
    for nm in a.inline:
        have, v0 = specs[nm]
        fill = v0["attrs"].get("_FillValue")
        kind = "i" if v0["dtype"] in ("|S1", "|u1") else np.dtype(v0["dtype"]).kind
        dtype = "u1" if v0["dtype"] == "|S1" else np.dtype(v0["dtype"]).newbyteorder("=").str
        fv = ord(fill[:1] or " ") if isinstance(fill, str) else (fill if fill is not None else
                                                                 (np.nan if kind == "f" else 0))
        out = np.full(total, fv, dtype=dtype)
        with ThreadPoolExecutor(a.workers) as ex:
            got = list(ex.map(lambda iv: (iv[0], cdf.read_var(sources[iv[0]], iv[1], heads[iv[0]]["recsize"])), have))
        for i, x in got:
            out[start[i]:start[i + 1]] = x.view("u1") if v0["dtype"] == "|S1" else x
        values[nm] = out
        lines += [f'    <Array name="{escape(nm)}">', f"      <DataType>{VRT_TYPE[v0['dtype']]}</DataType>",
                  f'      <DimensionRef ref="{escape(a.dim)}"/>']
        u = v0["attrs"].get("units")
        if isinstance(u, str) and u.strip():
            lines.append(f"      <Unit>{escape(u)}</Unit>")
        lines.append(f'      <InlineValues offset="0" count="{total}">'
                     + " ".join(fmt(x, kind) for x in out.tolist()) + "</InlineValues>")
        lines.append("    </Array>")
    names = [os.path.splitext(os.path.basename(s.split("?")[0]))[0] for s in sources]
    for nm, vals, at in ((a.index, np.repeat(np.arange(len(sources)), n),
                          {"long_name": f"position of the source file of each element along {a.dim}, "
                                        "in source_names", "source_names": names}),
                         (a.row, np.concatenate([np.arange(k) for k in n]) if n else np.zeros(0, int),
                          {"long_name": f"row of each element along {a.dim} within its source file"})):
        if not nm:
            continue
        lines += [f'    <Array name="{escape(nm)}">', "      <DataType>Int32</DataType>",
                  f'      <DimensionRef ref="{escape(a.dim)}"/>',
                  f'      <InlineValues offset="0" count="{total}">' + " ".join(map(str, vals.tolist()))
                  + "</InlineValues>"]
        for k, v in at.items():
            lines += attr_xml(k, v)
        lines.append("    </Array>")

    # concatenated arrays
    for nm in a.array:
        have, v0 = specs[nm]
        rest = v0["shape"][1:]
        block = a.block or ",".join(["1"] + [str(x) for x in rest])
        lines += [f'    <Array name="{escape(nm)}">', f"      <DataType>{VRT_TYPE[v0['dtype']]}</DataType>"]
        lines += [f'      <DimensionRef ref="{escape(d)}"/>' for d in v0["dims"]]
        lines.append(f"      <BlockSize>{block}</BlockSize>")
        u = v0["attrs"].get("units")
        if isinstance(u, str) and u.strip():
            lines.append(f"      <Unit>{escape(u)}</Unit>")
        fv = v0["attrs"].get("_FillValue")
        if isinstance(fv, (int, float)):
            lines.append(f"      <NoDataValue>{fmt(fv, 'f')}</NoDataValue>")
        for i, v in have:
            if not n[i]:
                continue
            cnt = ",".join(str(x) for x in [n[i]] + rest)
            zero = ",".join("0" for _ in v0["shape"])
            dest = ",".join([str(start[i])] + ["0"] * len(rest))
            lines += ["      <Source>", f"        <SourceFilename>{escape(sources[i])}</SourceFilename>",
                      f"        <SourceArray>/{escape(nm)}</SourceArray>",
                      f'        <SourceSlab offset="{zero}" count="{cnt}" step="{",".join("1" for _ in v0["shape"])}"/>',
                      f'        <DestSlab offset="{dest}"/>', "      </Source>"]
        lines.append("    </Array>")
    lines += ["  </Group>", "</VRTDataset>", ""]
    with open(a.vrt, "w") as f:
        f.write("\n".join(lines))

    if a.extents:
        if not (a.lat and a.lon and a.time) or not {a.lat, a.lon, a.time} <= set(values):
            sys.exit("plan_concat: --extents needs --lat, --lon and --time, each given with --inline")
        vl = {k: specs[k][1] for k in (a.lat, a.lon, a.time)}
        per = [tuple(values[k][start[i]:start[i + 1]] for k in (a.lat, a.lon, a.time)) for i in range(len(sources))]
        write_extents(a.extents, sources, per, [vl[k]["attrs"].get("_FillValue") for k in (a.lat, a.lon, a.time)],
                      vl[a.time]["attrs"]["units"], a.lat_max)
    print(f"plan_concat: {len(sources)} sources, {total} along {a.dim}, {len(a.array)} arrays, "
          f"{len(a.inline) + bool(a.index) + bool(a.row)} inline -> {a.vrt}")


if __name__ == "__main__":
    main()

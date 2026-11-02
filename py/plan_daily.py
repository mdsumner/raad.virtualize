"""plan_daily.py -- mdim VRT plan for a long daily series of one-step files.

The plan step for daily collections of thousands of netCDF/HDF5 files that
share one structure (OISST, sea ice CDR). `gdal mdim mosaic` opens every
source to read its coordinates, about 1 s per /vsicurl/ file, so a 16,000 day
series takes hours. This script runs the mosaic on the first two files only
(the template: dimensions, coordinate arrays, data types, attributes, and one
<Source> per array) and extends it to every file, with:

  - the time index of a file = its date minus the first date, so a missing
    day is a hole in the array rather than a shift of every later day;
  - time coordinate values extrapolated from the two template values (one
    step per day, in the units of the files);
  - the time <Unit> taken from the first file when the mosaic leaves it out
    (CF units are needed by the STAC and grist renders);
  - each <Source> a copy of the template source with its file name and
    DestSlab time offset replaced (the SourceSlab count is kept, so a read
    opens only the sources it touches).

Every file is assumed to share the grid, arrays, types and chunking of the
template, with exactly one time step. --check N opens N files spread over the
series (plus the first and last) and fails if a file's time value is not the
extrapolated one or its array shapes differ from the template; harvest and
verify catch the rest. Dates come from the first capture group of --pattern
applied to the file name, as YYYYMMDD; two files for one date are refused.

Usage:
  python plan_daily.py --sources sources.txt --array sst --array anom \
    --pattern 'oisst-avhrr-v02r01\\.(\\d{8})(_preliminary)?\\.nc$' plan.vrt
  [--template mosaic.vrt]  an existing mosaic of the first two sources (no
                           mosaic run; for tests)
  [--check 8] [--gdal gdal]
"""
import argparse
import copy
import datetime as dt
import os
import random
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def dated(sources, pattern):
    rx = re.compile(pattern)
    out = []
    for s in sources:
        m = rx.search(os.path.basename(s))
        if not m:
            sys.exit(f"plan_daily: no date in {s} (pattern {pattern})")
        out.append((dt.datetime.strptime(m.group(1), "%Y%m%d").date(), s))
    out.sort()
    days = [d for d, _ in out]
    dup = sorted({d for d in days if days.count(d) > 1}) if len(set(days)) != len(days) else []
    if dup:
        sys.exit(f"plan_daily: more than one file for {dup[0]} ({len(dup)} dates)")
    return out


def mosaic_template(gdal_bin, arrays, sources):
    fd, path = tempfile.mkstemp(suffix=".vrt")
    os.close(fd)
    cmd = [gdal_bin, "mdim", "mosaic", "--overwrite"]
    for a in arrays:
        cmd += ["--array", a]
    subprocess.run(cmd + list(sources) + [path], check=True)
    return path


def _num(v):
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def time_dimension(group):
    dims = group.findall("Dimension")
    for d in dims:
        if d.get("type") == "TEMPORAL":
            return d
    for d in dims:
        if d.get("name") == "time":
            return d
    sys.exit("plan_daily: the template has no TEMPORAL or 'time' dimension")


def file_time_unit(path, tname):
    """Units of the time coordinate in one source, through GDAL multidim."""
    from osgeo import gdal
    gdal.UseExceptions()
    ds = gdal.OpenEx(path, gdal.OF_MULTIDIM_RASTER)
    arr = ds.GetRootGroup().OpenMDArray(tname)
    # with exceptions on, GetAttribute raises for a missing attribute
    attrs = {a.GetName(): a for a in (arr.GetAttributes() or [])}
    u = arr.GetUnit() or (attrs["units"].Read() if "units" in attrs else "")
    cal = attrs["calendar"].Read() if "calendar" in attrs else None
    return u, cal


def check_files(files, idx, values, arrays, shapes, tname):
    """Open each sampled file: one time step equal to the extrapolated value,
    and the same array shapes as the template."""
    from osgeo import gdal
    import numpy as np
    gdal.UseExceptions()
    bad = 0
    for i in idx:
        d, s = files[i]
        want = values[(d - files[0][0]).days]
        g = gdal.OpenEx(s, gdal.OF_MULTIDIM_RASTER).GetRootGroup()
        t = np.asarray(g.OpenMDArray(tname).ReadAsArray()).ravel()
        msg = []
        if t.size != 1 or abs(float(t[0]) - want) > 1e-6:
            msg.append(f"time {t.tolist()} expected {want}")
        for a in arrays:
            shp = [x.GetSize() for x in g.OpenMDArray(a).GetDimensions()]
            if shp != shapes[a]:
                msg.append(f"{a} shape {shp} expected {shapes[a]}")
        print(f"  check {d} {os.path.basename(s)}: {'; '.join(msg) or 'ok'}")
        bad += bool(msg)
    if bad:
        sys.exit(f"plan_daily: {bad} of {len(idx)} checked files differ from the template")


def plan(files, template, arrays, unit=None, calendar=None):
    tree = ET.parse(template)
    group = tree.getroot().find("Group")
    tdim = time_dimension(group)
    tname = tdim.get("name")
    tvar = tdim.get("indexingVariable") or tname
    d0 = files[0][0]
    nt = (files[-1][0] - d0).days + 1

    tarr = next((a for a in group.findall("Array") if a.get("name") == tvar), None)
    if tarr is None:
        sys.exit(f"plan_daily: no coordinate array {tvar} in the template")
    iv = tarr.find("InlineValues")
    if iv is not None:
        tv = [float(x) for x in iv.text.split()]
    else:
        rs = tarr.find("RegularlySpacedValues")
        tv = [float(rs.get("start")) + k * float(rs.get("increment")) for k in range(2)]
    if len(tv) != 2:
        sys.exit(f"plan_daily: the template time axis has {len(tv)} steps, not 2")
    gap = (files[1][0] - d0).days
    per_day = (tv[1] - tv[0]) / gap
    if per_day <= 0:
        sys.exit("plan_daily: template time values do not increase")
    values = [tv[0] + k * per_day for k in range(nt)]

    tdim.set("size", str(nt))
    for el in list(tarr):
        if el.tag in ("InlineValues", "RegularlySpacedValues"):
            tarr.remove(el)
    pos = [i for i, el in enumerate(tarr) if el.tag in ("DataType", "DimensionRef")][-1] + 1
    if tarr.find("Unit") is None and unit:
        u = ET.Element("Unit")
        u.text = unit
        tarr.insert(pos, u)
        pos += 1
    if calendar and not any(a.get("name") == "calendar" for a in tarr.findall("Attribute")):
        at = ET.SubElement(tarr, "Attribute", name="calendar")
        ET.SubElement(at, "DataType").text = "String"
        ET.SubElement(at, "Value").text = calendar
    if tarr.find("Unit") is not None:
        pos = list(tarr).index(tarr.find("Unit")) + 1
    new = ET.Element("InlineValues", offset="0", count=str(nt))
    new.text = " ".join(_num(v) for v in values)
    tarr.insert(pos, new)

    shapes = {}
    for a in group.findall("Array"):
        if a.get("name") not in arrays:
            continue
        refs = [r.get("ref") for r in a.findall("DimensionRef")]
        if tname not in refs:
            sys.exit(f"plan_daily: array {a.get('name')} has no {tname} dimension")
        ax = refs.index(tname)
        srcs = a.findall("Source")
        if len(srcs) != 2:
            sys.exit(f"plan_daily: array {a.get('name')} has {len(srcs)} template sources, not 2")
        tmpl = srcs[0]
        cnt = tmpl.find("SourceSlab").get("count").split(",")
        if cnt[ax] != "1":
            sys.exit(f"plan_daily: array {a.get('name')} sources hold {cnt[ax]} time steps, not 1")
        dims = {d.get("name"): int(d.get("size")) for d in group.findall("Dimension")}
        shapes[a.get("name")] = [1 if r == tname else dims[r] for r in refs]
        at = list(a).index(tmpl)
        for s in srcs:
            a.remove(s)
        for k, (d, path) in enumerate(files):
            s = copy.deepcopy(tmpl)
            s.find("SourceFilename").text = path
            ds = s.find("DestSlab")
            off = ds.get("offset").split(",")
            off[ax] = str((d - d0).days)
            ds.set("offset", ",".join(off))
            a.insert(at + k, s)
    missing = set(arrays) - set(shapes)
    if missing:
        sys.exit(f"plan_daily: arrays {sorted(missing)} not in the template")
    ET.indent(tree, space="  ")
    return tree, nt, values, shapes, tname


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True, help="file of sources, one per line")
    ap.add_argument("--array", action="append", required=True)
    ap.add_argument("--pattern", required=True, help="regex on the file name; group 1 is YYYYMMDD")
    ap.add_argument("--template", help="mosaic VRT of the first two sources (skips the mosaic run)")
    ap.add_argument("--check", type=int, default=8, help="files to open and check (0 none)")
    ap.add_argument("--gdal", default=os.environ.get("GDAL", "gdal"))
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    files = dated(sources, a.pattern)
    if len(files) < 2:
        sys.exit("plan_daily: need at least two sources")
    template = a.template or mosaic_template(a.gdal, a.array, [s for _, s in files[:2]])
    unit = cal = None
    if not a.template:
        tname = time_dimension(ET.parse(template).getroot().find("Group")).get("name")
        unit, cal = file_time_unit(files[0][1], tname)
    tree, nt, values, shapes, tname = plan(files, template, a.array, unit, cal)
    if not a.template:
        os.remove(template)
    if a.check:
        n = len(files)
        idx = sorted({0, n - 1} | set(random.Random(1).sample(range(n), min(a.check, n))))
        check_files(files, idx, values, a.array, shapes, tname)
    tree.write(a.vrt, encoding="unicode")
    print(f"plan_daily: {len(files)} files over {nt} days ({nt - len(files)} missing), "
          f"{len(a.array)} arrays -> {a.vrt}")


if __name__ == "__main__":
    main()

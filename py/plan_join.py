"""plan_join.py -- add arrays from other files to an mdim VRT plan.

A model's grid often lives in separate static files: ACCESS-ESM1.6 (MOM)
writes the 2D cell centres geolon_t and geolat_t in ocean-2d-geolon_t-fx.nc
and ocean-2d-geolat_t-fx.nc, while each variable file names them in its
`coordinates` attribute and carries only the nominal 1D axes. This adds such
arrays to a plan made by `gdal mdim mosaic`, so harvest, collate and every
rendered form carry them as arrays of the store.

For each --source, `gdal mdim mosaic` (one source) writes a VRT of its
arrays; their <Array> elements are copied into the plan's root group, with
any <Dimension> the plan lacks. A dimension present in both must have the
same size, and an array name already in the plan stops the join. Sources
are written as given (e.g. /vsicurl/https://...), like the mosaic writes
them.

  --plan     plan VRT to extend (rewritten in place)
  --source   SOURCE[:ARRAY[,ARRAY...]]; arrays default to every array of
             the source other than its dimension coordinates (repeatable)
  --gdal     the gdal command (default gdal)

Usage:
  python plan_join.py --plan plan.vrt \
      --source /vsicurl/https://.../ocean-2d-geolon_t-fx.nc:geolon_t \
      --source /vsicurl/https://.../ocean-2d-geolat_t-fx.nc:geolat_t
"""
import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def split_source(s):
    # a /vsicurl/https:// URL holds colons: arrays follow the last ":" only
    # when what follows has no "/"
    head, sep, tail = s.rpartition(":")
    if sep and tail and "/" not in tail:
        return head, [a for a in tail.split(",") if a]
    return s, []


def mosaic(gdal, source, arrays, out):
    cmd = [gdal, "mdim", "mosaic", "--overwrite"]
    for a in arrays:
        cmd += ["--array", a]
    subprocess.run(cmd + [source, out], check=True)
    return ET.parse(out).getroot()


def join(plan_root, src_root, arrays):
    pg = plan_root.find("Group")
    sg = src_root.find("Group")
    if pg is None or sg is None:
        sys.exit("plan_join: no root <Group> in the plan or the source VRT")
    dims = {d.get("name"): d for d in pg.findall("Dimension")}
    have = {a.get("name") for a in pg.findall("Array")}
    sdims = {d.get("name"): d for d in sg.findall("Dimension")}
    coord = set(sdims)
    added = []
    for arr in sg.findall("Array"):
        name = arr.get("name")
        if arrays and name not in arrays:
            continue
        if not arrays and name in coord:
            continue
        if name in have:
            sys.exit(f"plan_join: array {name} is already in the plan")
        for dr in arr.findall("DimensionRef"):
            d = dr.get("ref")
            if d in dims:
                if dims[d].get("size") != sdims[d].get("size"):
                    sys.exit(f"plan_join: dimension {d} is {dims[d].get('size')} in the plan, "
                             f"{sdims[d].get('size')} in the source of {name}")
            else:
                pg.insert(len(pg.findall("Dimension")), sdims[d])
                dims[d] = sdims[d]
                # its indexing variable comes too, when the source has one
                for ia in sg.findall("Array"):
                    if ia.get("name") == sdims[d].get("indexingVariable") and ia.get("name") not in have:
                        pg.append(ia)
                        have.add(ia.get("name"))
        pg.append(arr)
        have.add(name)
        added.append(name)
    missing = [a for a in arrays if a not in added]
    if missing:
        sys.exit(f"plan_join: not in the source: {', '.join(missing)}")
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--source", action="append", required=True)
    ap.add_argument("--gdal", default="gdal")
    a = ap.parse_args()
    tree = ET.parse(a.plan)
    root = tree.getroot()
    with tempfile.TemporaryDirectory() as tmp:
        for i, s in enumerate(a.source):
            src, arrays = split_source(s)
            sroot = mosaic(a.gdal, src, arrays, os.path.join(tmp, f"join{i}.vrt"))
            added = join(root, sroot, arrays)
            print(f"plan_join: {', '.join(added)} from {src}")
    ET.indent(tree)
    tree.write(a.plan, encoding="unicode")


if __name__ == "__main__":
    main()

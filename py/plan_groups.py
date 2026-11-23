"""plan_groups.py -- mdim VRT plan with one group per classic netCDF file.

For a collection whose files cannot be one cube (dimensions that differ in
size from file to file, such as the 12 to 28 levels of MEOP's 2017 seal
profiles): each file becomes a group of the plan holding every variable of
the file as stored, its own dimensions, and its global attributes, read
whole from the one source:

  <Group name="ct36-B-09">
    <Dimension name="N_PROF" size="893"/>  ...
    <Attribute name="species">...</Attribute>  ...
    <Array name="TEMP">
      <DataType>Float32</DataType>
      <DimensionRef ref="N_PROF"/><DimensionRef ref="N_LEVELS"/>
      <BlockSize>893,12</BlockSize>
      <Source><SourceFilename>FILE</SourceFilename><SourceArray>/TEMP</SourceArray>
        <SourceSlab offset="0,0" count="893,12" step="1,1"/><DestSlab offset="0,0"/></Source>
    </Array>

The store names each array by its path (ct36-B-09/TEMP, py/harvest.py
plan_arrays()), and the BlockSize of the whole array makes each variable
one chunk (harvest engine cdf). The group name is the file name without
its extension, less --strip (a regex). A char variable is written as Byte
(GDAL reads a 1D, 3D or 4D one so; a 2D one it reads as strings, which
R/mdimrefs_pipeline.R leaves out of the rendered VRT). Scalar variables
(rank 0) have no place in the store and are left out, with a count.

--extents FILE writes one row per source from its --lat, --lon and --time
variables, as py/plan_concat.py --extents does, for R/stac.R STAC_EXTENTS.

Usage:
  python plan_groups.py --sources sources.txt [--strip '_(hr1_)?prof$'] [--workers 16] \
    [--extents extents.tsv --lat LATITUDE --lon LONGITUDE --time JULD --lat-max 0] plan.vrt
"""
import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdf  # noqa: E402
from plan_concat import VRT_TYPE, attr_xml, write_extents  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", required=True)
    ap.add_argument("--strip", default="", help="regex removed from the file stem to name the group")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--extents", help="write per-source extents (TSV) for R/stac.R")
    ap.add_argument("--lat"), ap.add_argument("--lon"), ap.add_argument("--time")
    ap.add_argument("--lat-max", type=float, default=90.0,
                    help="positions at or north of this latitude are left out of the extents")
    ap.add_argument("vrt")
    a = ap.parse_args()
    with open(a.sources) as f:
        sources = [s.strip() for s in f if s.strip()]
    with ThreadPoolExecutor(a.workers) as ex:
        heads = list(ex.map(cdf.read_header, sources))
    names = [re.sub(a.strip, "", os.path.splitext(os.path.basename(s.split("?")[0]))[0]) if a.strip
             else os.path.splitext(os.path.basename(s.split("?")[0]))[0] for s in sources]
    if len(set(names)) < len(names):
        dup = sorted({n for n in names if names.count(n) > 1})
        sys.exit(f"plan_groups: two sources give the group name {dup[0]}")
    lines = ["<VRTDataset>", '  <Group name="/">']
    narr = nscalar = 0
    for s, h, g in zip(sources, heads, names):
        lines.append(f'    <Group name="{escape(g)}">')
        for d, sz in h["dims"]:
            lines.append(f'      <Dimension name="{escape(d)}" size="{h["numrecs"] if sz == 0 else sz}"/>')
        for k, v in h["attrs"].items():
            if v == "" or v == []:
                continue
            lines += attr_xml(k, v, ind="      ")
        for nm, v in h["vars"].items():
            if not v["shape"]:
                nscalar += 1
                continue
            lines += [f'      <Array name="{escape(nm)}">', f"        <DataType>{VRT_TYPE[v['dtype']]}</DataType>"]
            lines += [f'        <DimensionRef ref="{escape(d)}"/>' for d in v["dims"]]
            # one chunk: the whole variable (a record variable: one record)
            block = [1] + v["shape"][1:] if v["record"] else v["shape"]
            lines.append(f"        <BlockSize>{','.join(map(str, block))}</BlockSize>")
            u = v["attrs"].get("units")
            if isinstance(u, str) and u.strip():
                lines.append(f"        <Unit>{escape(u)}</Unit>")
            fv = v["attrs"].get("_FillValue")
            if isinstance(fv, (int, float)) and v["dtype"] != "|S1":
                lines.append(f"        <NoDataValue>{fv:.17g}</NoDataValue>")
            shp = ",".join(map(str, v["shape"]))
            zero = ",".join("0" for _ in v["shape"])
            lines += ["        <Source>", f"          <SourceFilename>{escape(s)}</SourceFilename>",
                      f"          <SourceArray>/{escape(nm)}</SourceArray>",
                      f'          <SourceSlab offset="{zero}" count="{shp}" step="{",".join("1" for _ in v["shape"])}"/>',
                      f'          <DestSlab offset="{zero}"/>', "        </Source>", "      </Array>"]
            narr += 1
        lines.append("    </Group>")
    lines += ["  </Group>", "</VRTDataset>", ""]
    with open(a.vrt, "w") as f:
        f.write("\n".join(lines))
    if a.extents:
        if not (a.lat and a.lon and a.time):
            sys.exit("plan_groups: --extents needs --lat, --lon and --time")
        ks = (a.lat, a.lon, a.time)

        def one(i):
            h = heads[i]
            if not all(k in h["vars"] for k in ks):
                return (), (), ()
            return tuple(cdf.read_var(sources[i], h["vars"][k], h["recsize"]) for k in ks)
        with ThreadPoolExecutor(a.workers) as ex:
            per = list(ex.map(one, range(len(sources))))
        v0 = next(h["vars"] for h in heads if all(k in h["vars"] for k in ks))
        write_extents(a.extents, sources, per, [v0[k]["attrs"].get("_FillValue") for k in ks],
                      v0[a.time]["attrs"]["units"], a.lat_max)
    print(f"plan_groups: {len(sources)} groups, {narr} arrays"
          f"{f', {nscalar} scalar variables left out' if nscalar else ''} -> {a.vrt}")


if __name__ == "__main__":
    main()

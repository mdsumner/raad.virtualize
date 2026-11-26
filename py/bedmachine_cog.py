"""bedmachine_cog.py -- Cloud Optimized GeoTIFFs of the BedMachine Antarctica netCDF.

One COG per array of the NSIDC-0756 file (MEaSUREs BedMachine Antarctica,
doi:10.5067/POJQI54A45HX), written as OUT/<array>.tif, with values, type
and nodata unchanged: Float32 and Int16 arrays keep their _FillValue
(-9999) as nodata, and the Int8 class arrays, which have none, get none.
The netCDF is the provenance source: its SHA-256 is stamped into each COG
and into OUT/provenance.json, with the SHA-256 of each COG. Each COG is
read back and compared with the netCDF array; any differing pixel (NaN
equal to NaN) is a failure.

Settings, as for Bedmap3 (docs/bedmap-source-coop.md), for the
byte-reference forms built on these files:

  COMPRESS=ZSTD LEVEL=17  write-once product
  PREDICTOR=NO            a predictor makes the kerchunk and Icechunk forms
                          need imagecodecs and unreadable by GDAL Zarr
  BLOCKSIZE=512           one tile is one Zarr chunk
  SPARSE_OK=FALSE         every tile of the grid has a reference
  AVERAGE overviews       NEAREST for the class arrays (mask, source,
                          dataid, rgi); indexed as <name>_x<f>
                          (py/plan_static.py --overviews)

Usage:
  python py/bedmachine_cog.py --nc RAW/<file>.nc --out OUT [--fetch RAW/fetch.tsv]
"""
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

DOI = "10.5067/POJQI54A45HX"
LICENSE = ("These data are freely, openly, and fully available to use without restrictions, "
           "provided that you cite the data according to the recommended citation at "
           "https://nsidc.org/about/data-use-and-copyright.")
ARRAYS = {
    "bed": "AVERAGE", "dataid": "NEAREST", "errbed": "AVERAGE", "firn": "AVERAGE",
    "geoid": "AVERAGE", "mask": "NEAREST", "rgi": "NEAREST", "source": "NEAREST",
    "surface": "AVERAGE", "thickness": "AVERAGE",
}
# netCDF attributes carried into the COG metadata ("source" is the
# attribution of the array, not the source array)
TAGS = ("long_name", "standard_name", "flag_values", "flag_meanings", "valid_range",
        "source", "comment", "geoid")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def text(v):
    return " ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--nc", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fetch", help="fetch.tsv: name, size, sha256, url per source file")
    p.add_argument("--arrays", help="comma separated subset of the arrays (a test)")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    nc_name = os.path.basename(a.nc)
    nc_hash = sha256(a.nc)
    fetched = {}
    if a.fetch:
        with open(a.fetch) as f:
            fetched = {r[0]: r[1:] for r in (l.rstrip("\n").split("\t") for l in f if l.strip())}
        if nc_name in fetched and fetched[nc_name][1] != nc_hash:
            sys.exit(f"bedmachine_cog: {nc_name} does not match the checksum taken at download")
    root = gdal.OpenEx(a.nc, gdal.OF_MULTIDIM_RASTER).GetRootGroup()
    gattr = {t.GetName(): t.Read() for t in root.GetAttributes()}
    x = root.OpenMDArray("x").ReadAsArray()
    y = root.OpenMDArray("y").ReadAsArray()
    res = float(x[1] - x[0])
    if res <= 0 or not np.all(np.diff(x) == res) or not np.all(np.diff(y) == -res):
        sys.exit("bedmachine_cog: x must ascend and y descend on a regular grid")
    left, top = float(x[0]) - res / 2, float(y[0]) + res / 2
    want_gt = (left, res, 0.0, top, 0.0, -res)
    bounds = [left, top, left + res * len(x), top - res * len(y)]
    names = a.arrays.split(",") if a.arrays else list(ARRAYS)
    files = {}
    for name in names:
        resampling = ARRAYS[name]
        t0 = time.time()
        out = os.path.join(a.out, f"{name}.tif")
        m = root.OpenMDArray(name)
        at = {t.GetName(): t.Read() for t in m.GetAttributes()}
        nodata = m.GetNoDataValueAsDouble() if m.GetNoDataValueAsRaw() is not None else None
        tags = {"SOURCE_DOI": DOI, "SOURCE_FILE": nc_name, "SOURCE_SHA256": nc_hash,
                "SOURCE_ARRAY": name, "SOURCE_PRODUCT_VERSION": str(gattr.get("product_version", ""))}
        tags.update({k: text(at[k]) for k in TAGS if k in at})
        tmp = gdal.Translate("", f'NETCDF:"{a.nc}":{name}', format="VRT", outputSRS="EPSG:3031",
                             outputBounds=bounds, noData="none" if nodata is None else nodata,
                             stats=False)
        band = tmp.GetRasterBand(1)
        band.SetDescription(name)
        if m.GetUnit():
            band.SetUnitType(m.GetUnit())
        tmp.SetMetadata({})
        band.SetMetadata({})
        tmp.SetMetadata(tags)
        gdal.Translate(out, tmp, format="COG", creationOptions=[
            "COMPRESS=ZSTD", "LEVEL=17", "PREDICTOR=NO", "BLOCKSIZE=512",
            "SPARSE_OK=FALSE", f"OVERVIEW_RESAMPLING={resampling}", "NUM_THREADS=ALL_CPUS"])
        tmp = None
        got = gdal.Open(out)
        b = got.GetRasterBand(1)
        v = got.ReadAsArray()
        want = m.ReadAsArray()
        same = (v == want) | (np.isnan(v) & np.isnan(want)) if v.dtype.kind == "f" else (v == want)
        n = int(v.size - same.sum())
        gt = got.GetGeoTransform()
        if n or v.dtype != want.dtype or b.GetNoDataValue() != nodata or gt != want_gt:
            sys.exit(f"bedmachine_cog: {name}: {n} pixels differ from the netCDF, type {v.dtype} "
                     f"(netCDF {want.dtype}), nodata {b.GetNoDataValue()} (netCDF {nodata}), "
                     f"geotransform {gt} (expected {want_gt})")
        st = got.GetMetadata("IMAGE_STRUCTURE")
        files[name] = {"file": f"{name}.tif", "bytes": os.path.getsize(out), "sha256": sha256(out),
                       "dtype": str(v.dtype), "nodata": nodata, "pixels_compared": int(v.size),
                       "pixels_different": n, "overview_resampling": resampling}
        got = v = want = same = None
        print(f"{name}: {files[name]['bytes'] / 1e6:.1f} MB, identical to the netCDF, "
              f"{st.get('COMPRESSION')}, {time.time() - t0:.0f} s", flush=True)
    doc = {"source": {"doi": f"https://doi.org/{DOI}", "file": nc_name,
                      "bytes": os.path.getsize(a.nc), "sha256": nc_hash,
                      "product_version": str(gattr.get("product_version", "")),
                      "date_modified": str(gattr.get("date_modified", "")),
                      "url": fetched.get(nc_name, [None] * 3)[2]},
           "license": LICENSE, "gdal": gdal.__version__, "cogs": files,
           "fetched": {k: {"bytes": int(v[0]), "sha256": v[1]} for k, v in fetched.items()}}
    with open(os.path.join(a.out, "provenance.json"), "w") as f:
        json.dump(doc, f, indent=1)


if __name__ == "__main__":
    main()

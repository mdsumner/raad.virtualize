"""ibcso_cog.py -- Cloud Optimized GeoTIFFs of an IBCSO release.

One COG per grid, written as OUT/<array>.tif with values, type and nodata
unchanged. The release GeoTIFFs are the provenance source: each file's
SHA-256 is stamped into its COG and written to OUT/provenance.json, and each
COG is compared with its GeoTIFF; any differing pixel is a failure.

  --release v2      PANGAEA (doi:10.1594/PANGAEA.937574), IBCSO_v2_<grid>.tif;
                    also compared with the netCDF of each grid, stored south-up
  --release 2024    annual releases, IBCSO_<grid>.tif (2024 from the raad
  --release 2025    mirror, no longer distributed; 2025 from ibcso.org)

The annual bed and ice-surface GeoTIFFs state an origin of -4800018.55,
4800018.55, 18.55 m off the v2 grid that their own RID and TID grids use. A
regression of each release's difference from v2 on the v2 terrain gradient
gives a shift of at most 0.005 cells against 0.037 for 18.55 m, so the values
are on the v2 grid and only the geotransform is wrong. These COGs take the v2
origin; pixels are unchanged and the correction is recorded in the COG tags
and provenance.json.

Settings are those of py/bedmap3_cog.py (docs/bedmap-source-coop.md):
ZSTD level 17, no predictor, 512 x 512 tiles, SPARSE_OK=FALSE. Overviews use
AVERAGE, or NEAREST for the identifier grids rid and tid.

Usage:
  python py/ibcso_cog.py --raw RAW --out OUT
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

DOI = "10.1594/PANGAEA.937574"
GRIDS = {  # array: file stem, netCDF array, overview resampling, long name
    "bed": ("bed", "z", "AVERAGE", "Bed elevation, sub-ice topography"),
    "ice_surface": ("ice-surface", "z", "AVERAGE", "Ice surface elevation"),
    "rid": ("RID", "rid", "NEAREST", "Regional identifier of the source dataset"),
    "tid": ("TID", "tid", "NEAREST", "Type identifier of the source data"),
}
V2_GT = (-4800000.0, 500.0, 0.0, 4800000.0, 0.0, -500.0)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raw", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--release", required=True, choices=["v2", "2024", "2025"])
    a = p.parse_args()
    v2 = a.release == "v2"
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.raw, "fetch.tsv")) as f:
        fetched = {r[0]: r[1:] for r in (l.rstrip("\n").split("\t") for l in f)}
    files = {}
    for name, (grid, nc_array, resampling, long_name) in GRIDS.items():
        t0 = time.time()
        stem = f"IBCSO_v2_{grid}" if v2 else f"IBCSO_{grid}"
        src = os.path.join(a.raw, f"{stem}.tif")
        h = sha256(src)
        # annual GeoTIFFs come out of the fetched zips; their zip is checksummed
        want_h = fetched.get(f"{stem}.tif", [None, None])[1]
        if want_h is not None and want_h != h:
            sys.exit(f"ibcso_cog: {stem}.tif does not match the checksum taken at download")
        s = gdal.Open(src)
        fix = s.GetGeoTransform() != V2_GT
        if fix and (v2 or abs(s.GetGeoTransform()[0] + 4800018.550238501) > 1e-6):
            sys.exit(f"ibcso_cog: {stem}.tif geotransform {s.GetGeoTransform()} is not one this script corrects")
        tags = [f"SOURCE_DOI={DOI}", f"SOURCE_FILE={stem}.tif", f"SOURCE_SHA256={h}",
                f"IBCSO_RELEASE={a.release}", f"long_name={long_name}"]
        if fix:
            tags.append("GEOTRANSFORM_CORRECTED=origin -4800018.550238501,4800018.550238501 "
                        "set to the v2 grid -4800000,4800000; pixels unchanged (py/ibcso_cog.py)")
        tmp = gdal.Translate("", src, format="VRT", outputBounds=[-4800000, 4800000, 4800000, -4800000]) if fix else src
        out = os.path.join(a.out, f"{name}.tif")
        gdal.Translate(out, tmp, format="COG", metadataOptions=tags, creationOptions=[
            "COMPRESS=ZSTD", "LEVEL=17", "PREDICTOR=NO", "BLOCKSIZE=512", "SPARSE_OK=FALSE",
            f"OVERVIEW_RESAMPLING={resampling}", "NUM_THREADS=ALL_CPUS"])
        got = gdal.Open(out)
        v = got.ReadAsArray()
        want = s.ReadAsArray()
        m = None
        if v2:
            nc = gdal.OpenEx(os.path.join(a.raw, f"{stem}.nc"), gdal.OF_MULTIDIM_RASTER)
            flipped = np.asarray(nc.GetRootGroup().OpenMDArray(nc_array).ReadAsArray())[::-1]
            m = int((v != flipped).sum())
        n = int((v != want).sum())
        if n or m or v.dtype != want.dtype or got.GetGeoTransform() != V2_GT or \
                got.GetRasterBand(1).GetNoDataValue() != s.GetRasterBand(1).GetNoDataValue():
            sys.exit(f"ibcso_cog: {name}: {n} pixels differ from the GeoTIFF, {m} from the netCDF")
        files[name] = {"file": f"{name}.tif", "source": f"{stem}.tif", "source_sha256": h,
                       "bytes": os.path.getsize(out), "sha256": sha256(out),
                       "pixels_compared": int(v.size), "pixels_different_geotiff": n,
                       "pixels_different_netcdf": m, "overview_resampling": resampling,
                       "geotransform_corrected": fix}
        print(f"{name}: {files[name]['bytes'] / 1e6:.1f} MB, identical to the source"
              f"{' and netCDF' if v2 else ''}{', origin corrected' if fix else ''}, "
              f"{time.time() - t0:.0f} s", flush=True)
    doc = {"release": a.release, "source": {"doi": f"https://doi.org/{DOI}", "origin": {
               "v2": "PANGAEA", "2024": "raad mirror of ibcso.org/wp-content/uploads/_ANNUAL (2024-12-03); "
               "no longer distributed by IBCSO", "2025": "ibcso.org/wp-content/uploads/_ANNUAL"}[a.release]},
           "license": "CC-BY-4.0",
           "gdal": gdal.__version__, "cogs": files,
           "fetched": {k: {"bytes": int(v[0]), "sha256": v[1], "url": v[2]} for k, v in fetched.items()}}
    with open(os.path.join(a.out, "provenance.json"), "w") as f:
        json.dump(doc, f, indent=1)


if __name__ == "__main__":
    main()

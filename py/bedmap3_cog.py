"""bedmap3_cog.py -- Cloud Optimized GeoTIFFs of the Bedmap3 netCDF.

One COG per array of bedmap3.nc (UK Polar Data Centre,
doi:10.5285/2d0e4791-8e20-46a3-80e4-f5f6716025d2), written as
OUT/<array>.tif, with values, type and nodata unchanged. The netCDF is the
provenance source: its SHA-256 is stamped into each COG and into
OUT/provenance.json, with the SHA-256 of each COG. Each COG is read back
and compared with the netCDF array; any differing pixel is a failure.

Settings, for the byte-reference forms built on these files (see
docs/bedmap-source-coop.md):

  COMPRESS=ZSTD LEVEL=17  write-once product
  PREDICTOR=NO            a predictor makes the kerchunk and Icechunk forms
                          need imagecodecs and unreadable by GDAL Zarr
  BLOCKSIZE=512           one tile is one Zarr chunk
  SPARSE_OK=FALSE         every tile of the grid has a reference
  AVERAGE overviews       NEAREST for mask and thickness_survey_count, whose
                          values are class codes and counts

Usage:
  python py/bedmap3_cog.py --nc RAW/bedmap3.nc --out OUT [--fetch RAW/fetch.tsv]
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

DOI = "10.5285/2d0e4791-8e20-46a3-80e4-f5f6716025d2"
ARRAYS = {
    "bed_topography": "AVERAGE", "bed_uncertainty": "AVERAGE",
    "ice_thickness": "AVERAGE", "mask": "NEAREST",
    "surface_topography": "AVERAGE", "thickness_survey_count": "NEAREST",
    "thickness_uncertainty": "AVERAGE",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--nc", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fetch", help="fetch.tsv: name, size, sha256, url per source file")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    nc_hash = sha256(a.nc)
    fetched = {}
    if a.fetch:
        with open(a.fetch) as f:
            fetched = {r[0]: r[1:] for r in (l.rstrip("\n").split("\t") for l in f)}
        name = os.path.basename(a.nc)
        if name in fetched and fetched[name][1] != nc_hash:
            sys.exit(f"bedmap3_cog: {name} does not match the checksum taken at download")
    root = gdal.OpenEx(a.nc, gdal.OF_MULTIDIM_RASTER).GetRootGroup()
    x0 = float(np.frombuffer(root.OpenMDArray("x").Read(), "f4")[0])
    y0 = float(np.frombuffer(root.OpenMDArray("y").Read(), "f4")[0])
    files = {}
    for name, resampling in ARRAYS.items():
        t0 = time.time()
        out = os.path.join(a.out, f"{name}.tif")
        m = root.OpenMDArray(name)
        ny, nx = [d.GetSize() for d in m.GetDimensions()]
        at = {t.GetName(): t.Read() for t in m.GetAttributes()}
        tags = {"SOURCE_DOI": DOI, "SOURCE_FILE": os.path.basename(a.nc),
                "SOURCE_SHA256": nc_hash, "SOURCE_ARRAY": name}
        for k in ("long_name", "standard_name", "description", "flag_meanings"):
            if k in at:
                tags[k] = str(at[k])
        tmp = gdal.Translate(
            "", f'NETCDF:"{a.nc}":{name}', format="VRT", outputSRS="EPSG:3031",
            outputBounds=[x0 - 250, y0 + 250, x0 - 250 + 500 * nx, y0 + 250 - 500 * ny],
            noData=-9999, stats=False)
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
        got = gdal.Open(out)
        b = got.GetRasterBand(1)
        v = got.ReadAsArray()
        want = np.frombuffer(m.Read(), "<i2").reshape(ny, nx)
        n = int((v != want).sum())
        gt = got.GetGeoTransform()
        if n or v.dtype != want.dtype or b.GetNoDataValue() != -9999 or \
                gt != (x0 - 250, 500.0, 0.0, y0 + 250, 0.0, -500.0):
            sys.exit(f"bedmap3_cog: {name}: {n} pixels differ from the netCDF, "
                     f"type {v.dtype}, nodata {b.GetNoDataValue()}, geotransform {gt}")
        st = got.GetMetadata("IMAGE_STRUCTURE")
        files[name] = {"file": f"{name}.tif", "bytes": os.path.getsize(out), "sha256": sha256(out),
                       "pixels_compared": int(v.size), "pixels_different": n,
                       "overview_resampling": resampling}
        got = None
        print(f"{name}: {files[name]['bytes'] / 1e6:.1f} MB, identical to the netCDF, "
              f"{st.get('COMPRESSION')}, {time.time() - t0:.0f} s", flush=True)
    doc = {"source": {"doi": f"https://doi.org/{DOI}", "file": os.path.basename(a.nc),
                      "bytes": os.path.getsize(a.nc), "sha256": nc_hash,
                      "url": fetched.get(os.path.basename(a.nc), [None] * 3)[2]},
           "license": "CC-BY-4.0", "gdal": gdal.__version__, "cogs": files,
           "fetched": {k: {"bytes": int(v[0]), "sha256": v[1]} for k, v in fetched.items()}}
    with open(os.path.join(a.out, "provenance.json"), "w") as f:
        json.dump(doc, f, indent=1)


if __name__ == "__main__":
    main()

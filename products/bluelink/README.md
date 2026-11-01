# Bluelink ReANalysis (BRAN): virtual stores

Byte-reference indexes of the Bluelink ReANalysis daily ocean model output
held by NCI (project gb6). The model data is not copied: every form below
reads the original netCDF files from NCI THREDDS
(`https://thredds.nci.org.au/thredds/fileServer/gb6/BRAN/`). BRAN2020 is
used before 2010 and BRAN2023 from 2010; the two share grid, chunking,
codecs and packing, so each variable is one array from 1993 (w from 1998)
to the last BRAN2023 month.

## Contents

- `catalog.json`: STAC catalog, one child collection per dataset
- `datasets.tsv`, `datasets.json`: the dataset list, the configuration each
  was built with, and (in `datasets.json`) time extent and build revision
- `<dataset>/`: one directory per variable and frequency, for example
  `bluelink-daily-temp/`
  - `mdim.vrt`: GDAL multidimensional VRT
  - `kerchunk/`: kerchunk Parquet (Zarr v2)
  - `icechunk/`: Icechunk repository, virtual references, branch `main`
  - `flat/`: flat refs store (`arrays.json`, `sources.parquet`,
    `refs_<var>.parquet`)
  - `stac/`: STAC collection (one asset per form) and one item per source
    file
  - `plan.vrt`, `store.sqlite`: the concatenation plan and the mdim-refs/0.2
    store the forms are rendered from

## Reading

With `BASE` the URL of this directory. The Icechunk example is for an
S3-compatible endpoint (`ENDPOINT`, `BUCKET`, `PREFIX` the location of this
directory), read anonymously:

```sh
gdal mdim info /vsicurl/$BASE/bluelink-daily-temp/mdim.vrt
```

```r
r <- terra::rast(sprintf("/vsicurl/%s/bluelink-daily-temp/mdim.vrt", BASE), md = TRUE)
```

```python
import icechunk, xarray as xr, zarr
zarr.config.set({"async.concurrency": 4})   # THREDDS resets connections at the default of 10
st = icechunk.s3_storage(bucket=BUCKET, prefix=f"{PREFIX}/bluelink-daily-temp/icechunk",
                         endpoint_url=ENDPOINT, region="us-east-1", anonymous=True,
                         force_path_style=True)
repo = icechunk.Repository.open(st,
    authorize_virtual_chunk_access={"https://thredds.nci.org.au/": icechunk.credentials.HttpAccess})
ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
```

## Provenance

Built with mdsumner/raad.virtualize on NCI Gadi, in situ from `/g/data/gb6`,
and verified against GDAL reads of the source files before and after
publication. The store meta records the code revision and configuration.
Terms of use of the model output are those of BRAN (CSIRO, Bluelink) at NCI.

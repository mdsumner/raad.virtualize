---
title: Overview
---

# Byte-reference virtualization of array collections

This repository builds virtual, cloud-readable views of archival array
collections (netCDF, HDF5, GeoTIFF/COG) without copying the data. Each
granule's chunk index is read once into a tabular store of byte references;
every published form is rendered from that store. The repository is a
working stage: its name and layout will change as the parts move to their
long-term homes.

- Code and runbook: [README](https://github.com/mdsumner/raad.virtualize#readme)
- Run log and findings: [results](results.md)

## Model

A virtual store is a table plus a plan. The table holds one row per chunk
of every source file (source, chunk coordinate within the source, present,
offset, size); the plan places each source in a global array. The forms
are projections of the two:

| Form | Readers |
|---|---|
| Flat refs store (`arrays.json`, `refs_<array>.parquet`, `sources.parquet`) | any Parquet reader; wxylib `wxy-refs` |
| GDAL multidim VRT | GDAL and its bindings (gdalraster, osgeo.gdal) |
| kerchunk Parquet | fsspec / xarray; GDAL `/vsikerchunk_parquet_ref/` |
| Icechunk (virtual references) | zarr-python / xarray |

The store layout is mdim-refs/0.2 (specification in wxylib/design,
`specs/mdim-refs-0.2.md`). Source URIs are recorded as harvested and
rewritten only at render time, so one harvest serves several endpoints.

## Pipeline

```
sources -> plan (gdal mdim mosaic, or py/plan_cog.py for GeoTIFF)
        -> harvest (chunk index per source)  -> collate (store.sqlite)
        -> render (flat, VRT, kerchunk)      -> Icechunk
        -> verify (every form against GDAL on the sources)
        -> publish, verify-published (object storage)
```

## Datasets

| Dataset | Source | Refs | State |
|---|---|---|---|
| OISST v2.1 daily, Sept 1981 | NOAA S3 (netCDF) | 120 | all forms verified; test case |
| BRAN2023 daily `temp` 2010 | NCI THREDDS (netCDF) | 1,116,900 | all forms verified; published to the AADC transfer bucket |
| BRAN2023 daily `salt` Jan-Feb 2010 | NCI THREDDS (netCDF) | 180,540 | verified from the bucket |
| GHRSST MUR `analysed_sst` 2024 | source.coop (COG) | 935,496 | VRT and Icechunk verified from the bucket |
| GHRSST MUR `analysed_sst` 2002-2026 | source.coop (COG) | 22,771,404 | harvest 17 min, collate 6 min (1.2 GB store), render 5 min, Icechunk 105 s (568 MB, 23 commits); verify in progress |

The AADC transfer bucket is private staging. Public publication (Pawsey,
source.coop) is a later step.

## Reader coverage

The GHRSST COGs use ZSTD with TIFF horizontal predictor (`PREDICTOR=2`),
written to the Zarr forms as the `imagecodecs_delta` filter. Coverage then
differs by reader:

| Form | Python with imagecodecs | GDAL, R |
|---|---|---|
| MDIM VRT | yes | yes; a full-width row of one day took 166 s |
| Icechunk | yes; the same row took 6 s | no filter for `imagecodecs_delta` |
| kerchunk Parquet | yes | no filter for `imagecodecs_delta` |
| flat refs store | own decode | wxy-refs, once it decodes the predictor |

Each reader stack has at least one working form today; the gaps below
widen that for R and GDAL users.

## Ongoing work

- Full GHRSST MUR series through render, Icechunk and verify (the
  Icechunk scale test).
- BRAN2023 multi-decade, a second scale test over THREDDS.
- A TIFF horizontal-predictor filter in GDAL's Zarr reader.
- Predictor decode in wxy-refs, so R reads the flat store directly.
- Serial COG tile fetches when GDAL reads through the VRT.
- Attribute types in the store, so readers keep float32 packing.
- GDAL `gdal mdim` block-info for bulk harvest into the flat store.
- Feeding the store from local file mirrors (the collection table) and
  publishing to the public endpoints.

## Related work

- [wxylib/design](https://github.com/wxylib/design): mdim-refs/0.2
  specification and the wxy-refs reader
- [hypertidy/vrtstack](https://github.com/hypertidy/vrtstack): COG
  collections as multidim VRT, the form `py/plan_cog.py` writes
- [hypertidy/blocklist](https://github.com/hypertidy/blocklist): the
  kerchunk writer vendored here
- [Tensors and tables](https://www.hypertidy.org/posts/2026-10-12_tensors-tables/):
  the tabular view of array data behind the store
- [ausantarctic/ghrsst-mur-v2](https://source.coop/ausantarctic/ghrsst-mur-v2):
  the GHRSST MUR COGs

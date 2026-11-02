# Bluelink ReANalysis (BRAN): virtual stores

Byte-reference indexes of the Bluelink ReANalysis daily ocean model output
held by NCI (project gb6). The model data is not copied: every form reads
the original netCDF files from NCI THREDDS. BRAN2020 is used before 2010
and BRAN2023 from 2010, so each variable is one array from 1993 (w from
1998) to the last BRAN2023 month.

## Contents

- `catalog.json`: STAC catalog, one child collection per dataset
- `datasets.tsv`, `datasets.json`: the dataset list, how each was built, and
  (in `datasets.json`) time extent and build revision
- `<dataset>/`, for example `bluelink-daily-temp/`: `mdim.vrt` (GDAL
  multidimensional VRT), `kerchunk/` (kerchunk Parquet), `icechunk/`
  (Icechunk, virtual references), `flat/` (flat Parquet refs), `stac/`,
  `grist/catalog.parquet`, and the plan and store they are rendered from
  (`plan.vrt`, `store.sqlite`)

## Reading

```sh
gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-temp/mdim.vrt
```

Fuller examples (Icechunk, xarray, R): mdsumner/raad.virtualize,
`docs/reading-published-stores.md`.

## Provenance

Built with mdsumner/raad.virtualize on NCI Gadi, in situ from `/g/data/gb6`,
and verified against GDAL reads of the source files before and after
publication. The store meta records the code revision and configuration.
Terms of use of the model output are those of BRAN (CSIRO, Bluelink) at NCI.

# NOAA OISST v2.1: virtual stores

Byte-reference indexes of the NOAA 1/4 degree Daily Optimum Interpolation
Sea Surface Temperature (OISST v2.1, AVHRR). No data is copied: every form
reads the original netCDF files in the public NOAA bucket
`noaa-cdr-sea-surface-temp-optimum-interpolation-pds`.

## Contents

- `catalog.json`: STAC catalog, one child collection per dataset
- `<dataset>/`, for example `oisst-v2.1-daily/`: `mdim.vrt`, `kerchunk/`,
  `icechunk/`, `flat/`, `stac/`, `grist/catalog.parquet`, and the plan and
  store they are rendered from (`plan.vrt`, `store.sqlite`)

## Reading

```sh
gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/oisst/oisst-v2.1-daily/mdim.vrt
```

Worked examples and how the stores are built: https://mdsumner.github.io/raad.virtualize/

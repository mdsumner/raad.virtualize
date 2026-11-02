# Virtual stores (drafts)

![Arrays and Ledgers](https://data.source.coop/ausantarctic/ausantarctic-scratch/banner-800.jpg)

Draft byte-reference indexes ("virtual stores") of ocean and sea ice
datasets. No data is copied: every form reads the original files where they
are published. Contents are transient. A group moves to its production home
when it is ready, and anything here may change or be removed without notice.

## Layout

- `catalog.json`: STAC catalog, one child catalog per group
- `<group>/catalog.json`: one child STAC collection per dataset
- `<group>/<dataset>/`: one dataset, in several forms read from the same
  byte references: `mdim.vrt` (GDAL multidimensional VRT), `kerchunk/`
  (kerchunk Parquet), `icechunk/` (Icechunk, virtual references), `flat/`
  (flat Parquet refs), `stac/`

Groups: `bluelink/` (Bluelink ReANalysis), `ghrsst/` (GHRSST MUR),
`oisst/` (NOAA OISST), `seaice/` (sea ice concentration).

## Reading

```sh
gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-temp/mdim.vrt
```

Fuller examples (Icechunk, xarray, R) and how the stores are built: see
Links below.

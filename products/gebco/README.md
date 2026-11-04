# GEBCO

Virtual multidimensional indexes of the GEBCO global grids published in this
product. The indexes read the Cloud Optimized GeoTIFFs in place: no data is
copied. The COGs are a repackaged copy; the authoritative releases are those
of the GEBCO Compilation Group, cited below.

GEBCO grids are not for navigation or any other purpose involving safety at
sea.

## Releases

| Dataset | COG | Compression |
|---|---|---|
| `gebco-2026` | `GEBCO_2026.tif` | DEFLATE, PREDICTOR=2 |
| `gebco-2025` | `GEBCO_2025.tif` | DEFLATE, PREDICTOR=2 |
| `gebco-2024` | `GEBCO_2024.tif` | DEFLATE, no predictor |

## Grid

43,200 x 86,400 cells at 15 arc-seconds in EPSG:4326, Int16, nodata -32767,
one array `elevation` (metres, ocean and land, with under-ice topography for
Greenland and Antarctica), and one array per overview level,
`elevation_x<factor>`.

Layout:

```
GEBCO_<year>.tif                    COG (not written by these indexes)
virtual/catalog.json                STAC catalog
virtual/gebco-<year>/mdim.vrt       GDAL multidimensional VRT
virtual/gebco-<year>/kerchunk/      Kerchunk Parquet
virtual/gebco-<year>/icechunk/      Icechunk repository
virtual/gebco-<year>/flat/          flat reference tables
virtual/gebco-<year>/stac/          STAC collection, its one item, stac-geoparquet
virtual/gebco-<year>/thumbnail.png  overview of elevation
virtual/gebco-<year>/store.sqlite   byterefs/0.1 store
```

Every virtual form references the COGs by absolute URL. PREDICTOR=2 maps to
the `imagecodecs_delta` filter: for 2025 and 2026 the Kerchunk and Icechunk
forms need imagecodecs in the reader, and GDAL reads neither; the VRT form
reads every release.

## Citation

GEBCO grids are in the public domain and may be used free of charge; the
GEBCO terms of use ask that the source be acknowledged:

GEBCO Compilation Group (<year>) GEBCO <year> Grid.

See the [GEBCO terms of use](https://www.gebco.net/data_and_products/gridded_bathymetry_data/#a1)
for the DOI of each release and the full attribution.

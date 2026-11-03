# IBCSO

Cloud-optimized copies of the International Bathymetric Chart of the Southern
Ocean (IBCSO) grids, with virtual multidimensional indexes over them. Each
release has its own prefix. This is a repackaged copy; the authoritative
releases are those of AWI and IBCSO, cited below.

IBCSO products are not for navigation or any other purpose involving safety
at sea. They are provided as is, and their accuracy and completeness are not
guaranteed (IBCSO release readme).

## Releases

| Prefix | Release | Source |
|---|---|---|
| `v2/` | Version 2, 2022 | PANGAEA, doi:10.1594/PANGAEA.937574 |
| `annual-2024/` | 2024 annual release | raad mirror of ibcso.org, 2024-12-03; no longer distributed by IBCSO |
| `annual-2025/` | 2025 annual release, 2025-09-19 | ibcso.org |

The annual release is a rolling product: each replaces the previous one at
the same address. The annual prefixes here keep each release as it was
published.

## Grids

19,200 x 19,200 cells at 500 m in EPSG:9354 (IBCSO Polar Stereographic),
Int16, nodata -32768, one Cloud Optimized GeoTIFF per grid.

| Array | Content |
|---|---|
| `bed` | bed elevation, with sub-ice topography (metres) |
| `ice_surface` | ice surface elevation (metres) |
| `rid` | regional identifier of the source dataset |
| `tid` | type identifier of the source data |

Identifier codes and nodata differ between releases: v2 `tid` has no nodata
cells, the annual releases have about 122.7 million.

Layout:

```
<release>/cog/<array>.tif             COGs
<release>/cog/provenance.json         checksums and source record
virtual/catalog.json                  STAC catalog
virtual/ibcso-<release>/mdim.vrt      GDAL multidimensional VRT
virtual/ibcso-<release>/kerchunk/     Kerchunk Parquet
virtual/ibcso-<release>/icechunk/     Icechunk repository
virtual/ibcso-<release>/flat/         flat reference tables
virtual/ibcso-<release>/stac/         STAC collection, its one item, stac-geoparquet
virtual/ibcso-<release>/thumbnail.png overview of bed
virtual/ibcso-<release>/store.sqlite  byterefs/0.1 store
```

## Provenance

The COGs are written from the GeoTIFFs of each release with values, type and
nodata unchanged, and compared with them pixel by pixel; v2 is also compared
with the netCDF of the same release, which is stored south-up. Checksums of
every source file are in `provenance.json`.

The annual `bed` and `ice-surface` GeoTIFFs state an origin of
(-4800018.55, 4800018.55), 18.55 m off the grid of their own RID and TID and of
v2. A regression of the difference from v2 on the v2 terrain gradient gives a
shift of at most 0.005 cells, against 0.037 for 18.55 m, so the values lie on
the v2 grid. These COGs take the v2 origin (-4800000, 4800000); the pixels are
unchanged, and the correction is recorded in the tag `GEOTRANSFORM_CORRECTED`
and in `provenance.json`.

## Citation

Use of these data requires citation, under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):

Dorschel, B., Hehemann, L., Viquerat, S., et al. (2022). The International
Bathymetric Chart of the Southern Ocean Version 2. Scientific Data, 9(1), 275.
<https://doi.org/10.1038/s41597-022-01366-7>

For Version 2 also: Dorschel, B., et al. (2022). The International
Bathymetric Chart of the Southern Ocean Version 2 (IBCSO v2). PANGAEA.
<https://doi.org/10.1594/PANGAEA.937574>

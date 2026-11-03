# Bedmap

Cloud-optimized copies of the Bedmap gridded products for Antarctica, with
virtual multidimensional indexes over them. Each version has its own prefix.
This is a repackaged copy. The authoritative release is the UK Polar Data
Centre record cited below.

## Bedmap3

Static grids of 13,334 x 13,334 cells at 500 m in EPSG:3031, Int16, nodata
-9999, one Cloud Optimized GeoTIFF per array.

| Array | Unit | Content |
|---|---|---|
| `bed_topography` | metres | bed elevation |
| `bed_uncertainty` | metres | uncertainty of bed elevation |
| `ice_thickness` | metres | ice thickness |
| `mask` | | 1 grounded ice, 2 transiently grounded ice shelf, 3 floating ice shelf, 4 rock |
| `surface_topography` | metres | surface elevation |
| `thickness_survey_count` | count | survey points used for ice thickness |
| `thickness_uncertainty` | metres | uncertainty of ice thickness |

Layout:

```
bedmap3/cog/<array>.tif          COGs
bedmap3/cog/provenance.json      checksums and source record
virtual/catalog.json             STAC catalog
virtual/bedmap3/mdim.vrt         GDAL multidimensional VRT
virtual/bedmap3/kerchunk/        Kerchunk Parquet
virtual/bedmap3/icechunk/        Icechunk repository
virtual/bedmap3/flat/            flat reference tables
virtual/bedmap3/stac/            STAC collection, its one item, stac-geoparquet
virtual/bedmap3/thumbnail.png    overview of bed_topography
virtual/bedmap3/store.sqlite     byterefs/0.1 store
```

Every virtual form references the COGs by absolute URL.

## Provenance

The source is `bedmap3.nc` from the UK Polar Data Centre, SHA-256
`776bfbef4d4c06ceea0851619915d2c397eef9547d35cb551d5d1b11dd064ff3`. The COGs
are written from it with values, type and nodata unchanged, and are compared
pixel by pixel with the netCDF. The same record also distributes GeoTIFFs,
whose seven grids are pixel-identical to the netCDF arrays. The EPSG:3031
definition, the tiling, ZSTD compression and overviews are the only additions;
the array names are those of the netCDF. `bm3_streamlines_pt.zip` is not
included.

## Citation

Use of these data requires citation of the dataset and the paper, under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):

Pritchard, H., Fretwell, P., Fremand, A., et al. (2024). BEDMAP3 - Ice
thickness, bed and surface elevation for Antarctica - gridding products
(Version 1.0) [Data set]. NERC EDS UK Polar Data Centre.
<https://doi.org/10.5285/2d0e4791-8e20-46a3-80e4-f5f6716025d2>

Pritchard, H.D., Fretwell, P.T., Fremand, A.C., et al. Bedmap3 updated ice
bed, surface and thickness gridded datasets for Antarctica. Sci Data 12, 414
(2025). <https://doi.org/10.1038/s41597-025-04672-y>

# BedMachine Antarctica

Cloud-optimized copies of MEaSUREs BedMachine Antarctica, with virtual
multidimensional indexes over them. Each version has its own prefix. This
is a repackaged copy. The authoritative release is the NSIDC DAAC record
cited below, which needs a NASA Earthdata login and withdraws a version
when it is retired.

## Version 4 (file V04.1)

Static grids of 13,333 x 13,333 cells at 500 m in EPSG:3031, one Cloud
Optimized GeoTIFF per array. Elevations are heights above the EIGEN-6C4
geoid; ice thickness and surface elevation are in ice equivalent (firn air
content removed). Height above the WGS 84 ellipsoid is `bed` + `geoid`; the
top of the snow surface is `surface` + `firn`.

| Array | Type | Nodata | Unit | Content |
|---|---|---|---|---|
| `bed` | Float32 | -9999 | metres | bed topography and ocean bathymetry |
| `dataid` | Int8 | | | input data: 1 REMA, 2 radar, 7 seismic, 10 multibeam |
| `errbed` | Int16 | -9999 | metres | error of bed topography and ice thickness |
| `firn` | Float32 | -9999 | metres | firn air content |
| `geoid` | Float32 | | metres | EIGEN-6C4 geoid height above the WGS 84 ellipsoid |
| `mask` | Int8 | | | 0 ocean, 1 ice-free land, 2 grounded ice, 3 floating ice, 4 Lake Vostok |
| `rgi` | Int8 | | | 1 inside a Randolph Glacier Inventory v7.0 outline, 0 outside |
| `source` | Int8 | | | method: 1 REMA/IBCSO v2, 2 mass conservation, 3 interpolation, 4 hydrostatic, 5 ice flow perturbation analysis, 6 gravity, 7 seismic, 8 IceBoost, 10 multibeam |
| `surface` | Float32 | -9999 | metres | ice surface elevation |
| `thickness` | Float32 | -9999 | metres | ice thickness |

Layout:

```
v4.1/cog/<array>.tif                 COGs
v4.1/cog/provenance.json             checksums and source record
virtual/catalog.json                 STAC catalog
virtual/bedmachine-v4.1/mdim.vrt     GDAL multidimensional VRT
virtual/bedmachine-v4.1/kerchunk/    Kerchunk Parquet
virtual/bedmachine-v4.1/icechunk/    Icechunk repository
virtual/bedmachine-v4.1/flat/        flat reference tables
virtual/bedmachine-v4.1/stac/        STAC collection, its one item, stac-geoparquet
virtual/bedmachine-v4.1/thumbnail.png  overview of bed
virtual/bedmachine-v4.1/store.sqlite byterefs/0.1 store
```

Every virtual form references the COGs by absolute URL.

## Provenance

The source is `NSIDC-0756_BedMachineAntarctica_19700101-20191001_V04.1.nc`
(`product_version` v4.1, `date_modified` 2025-12-12), 1,198,815,840 bytes,
SHA-256 `6bd08dbbe1a781834450cd25f7b5f438463a540a873d819bb781912e7ecb1538`.
The COGs are written from it with values, type and nodata unchanged, and
are compared pixel by pixel with the netCDF. The EPSG:3031 definition, the
tiling, ZSTD compression and overviews are the only additions; the array
names and attributes are those of the netCDF.

## Citation and terms

NSIDC states: "These data are freely, openly, and fully available to use
without restrictions, provided that you cite the data according to the
recommended citation at <https://nsidc.org/about/data-use-and-copyright>."
See also the [NASA EOSDIS data use
policy](https://earthdata.nasa.gov/earth-observation-data/data-use-policy).

Morlighem, M. (2025). MEaSUREs BedMachine Antarctica (NSIDC-0756, Version
4). [Data set]. Boulder, Colorado USA. NASA National Snow and Ice Data
Center Distributed Active Archive Center.
<https://doi.org/10.5067/POJQI54A45HX>

Morlighem, M., Rignot, E., Binder, T., Blankenship, D. D., Drews, R.,
Eagles, G., et al. (2020). Deep glacial troughs and stabilizing ridges
unveiled beneath the margins of the Antarctic ice sheet. Nature Geoscience,
13, 132-137. <https://doi.org/10.1038/s41561-019-0510-8>

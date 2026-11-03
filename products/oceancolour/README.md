# Ocean colour virtual stores

Byte-reference indexes of ocean colour products. The sources are Cloud
Optimized GeoTIFF copies of the original netCDF files, one per variable per
time step, held on Pawsey Acacia (`aad-derived/esacci-oc/`). `catalog.json`
lists one STAC collection per dataset, each in its own directory with the
forms common to every group (`mdim.vrt`, `kerchunk/`, `icechunk/`, `flat/`,
`grist/`, `stac/`).

- `esacci-oc-v6.0-monthly-chlor_a`: ESA Ocean Colour CCI v6.0, merged-sensor
  L3S chlorophyll-a (mg m-3), geographic 4 km (8640 x 4320, EPSG:4326),
  monthly from 1997-09. COGs written from the netCDF files at
  https://www.oceancolour.org/thredds/catalog/cci/v6.0-release/geographic/monthly/chlor_a/catalog.html
  with values unchanged and the netCDF fill as NaN.
- `esacci-oc-v6.0-monthly-chlor_a_log10_bias`,
  `esacci-oc-v6.0-monthly-chlor_a_log10_rmsd`: the per-pixel log10 bias and
  root mean square difference of `chlor_a`, from the same files.

Citation: Ocean Colour Climate Change Initiative dataset, Version 6.0,
European Space Agency, available online at
https://climate.esa.int/en/projects/ocean-colour/. Licence: ESA CCI, EOCIS
and C3S data policy, free and open access.

## Reading

```sh
gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/oceancolour/esacci-oc-v6.0-monthly-chlor_a/mdim.vrt
```

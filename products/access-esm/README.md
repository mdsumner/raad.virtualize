# ACCESS-ESM1.6: virtual stores

Byte-reference indexes of the ACCESS-ESM1.6 historical simulation (ACCESS-NRI),
native model output, model years 1850 to 2021. No data is copied: every form
reads the original netCDF files on the ACCESS-NRI pilot bucket
`https://projects.pawsey.org.au/ct-esm1-6/` (Pawsey Acacia, public). The
bucket is a pilot copy and is expected to move; the stores record the source
URLs verbatim and a new location is a remap rule.

`catalog.json` lists one STAC collection per dataset, each in its own
directory with the forms common to every group (`mdim.vrt`, `kerchunk/`,
`icechunk/`, `flat/`, `grist/`, `stac/`).

- `access-esm1-6.historical.ocean-3d-temp-1mon-mean`: MOM ocean `temp`,
  monthly means, 50 depth levels on the 1 degree tripolar grid (300 x 360),
  2064 months. The 1D axes `xt_ocean` and `yt_ocean` are nominal; the true
  cell centres are the 2D arrays `geolon_t` and `geolat_t`, joined from the
  static files `output000/ocean/ocean-2d-geolon_t-fx.nc` and
  `ocean-2d-geolat_t-fx.nc`.

Native output, not CMORised: names follow the ACCESS output specification
and attributes are as the model wrote them. Licence and citation of the
model output are to be confirmed with ACCESS-NRI.

## Reading

```sh
gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/access-esm/access-esm1-6.historical.ocean-3d-temp-1mon-mean/mdim.vrt
```

# Sea ice concentration virtual stores

Byte-reference indexes of passive microwave sea ice concentration, read in
place from the original files. `catalog.json` lists one STAC collection per
dataset, each in its own directory with the forms common to every group
(`mdim.vrt`, `kerchunk/`, `icechunk/`, `flat/`, `grist/`, `stac/`).

- `g02202-v6-daily-south`, `g02202-v6-daily-north`: NOAA/NSIDC Climate Data
  Record of Passive Microwave Sea Ice Concentration, G02202 Version 6, 25 km
  polar stereographic grids, daily from 1978-10-25. Sources are the netCDF
  files at https://noaadata.apps.nsidc.org/NOAA/G02202_V6/.

How they are built and read: mdsumner/raad.virtualize.

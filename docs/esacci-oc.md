---
title: "ESA Ocean Colour CCI on source.coop"
---

Build of the ESA Ocean Colour CCI v6.0 indexes in the `oceancolour/` group of
`ausantarctic/ausantarctic-scratch`. The THREDDS server at
www.oceancolour.org is distant and slow for range reads, so the selected
variables are copied once as COGs to Pawsey Acacia and the virtual forms
reference the COGs (the GHRSST pattern), not the netCDF files. Monthly
`chlor_a`, with its log10 bias and RMSD, are the first datasets.

## COG settings

`py/esacci_cog.py` writes one COG per variable per netCDF file:

| Setting | Value | Reason |
|---|---|---|
| Compression | ZSTD level 17 | write-once product |
| Predictor | none | a predictor is written as a filter GDAL's Zarr driver does not read |
| Tiles | 512 x 512 | one tile is one Zarr chunk; 17 x 9 tiles per grid |
| `SPARSE_OK` | FALSE | every tile has a reference; an all-NaN tile is a few hundred bytes |
| Type and values | as in the netCDF (Float32 for `chlor_a`) | |
| Nodata | NaN, from the netCDF `_FillValue` 9.96921e+36 | becomes the Zarr `fill_value`; `--fill source` keeps the netCDF value |
| CRS, geotransform | EPSG:4326, (-180, 1/24, 0, 90, 0, -1/24) | the netCDF has no CRS; its coordinates are checked to 1e-6 degree |
| Overviews | AVERAGE, x2 to x32 | indexed as arrays `<var>_x2` .. `<var>_x32` on dims `y_x<f>`, `x_x<f>` (`ESACCI_OVERVIEWS`, default 1; py/plan_cog.py --overviews) |

Each COG is read back and compared with the netCDF array before it is
renamed into place; the NaN pixels must be exactly the netCDF fill pixels.
The COG metadata records the source URL, size and SHA-256 of the netCDF, and
each run writes `manifest/<UTC time>.tsv` under the COG root (COG, source,
sizes, checksums, pixel counts).

Layout under the COG root, from the THREDDS path, with the upstream product
folder (`chlor_a`) replaced by the variable:

```
v6.0-release/geographic/monthly/chlor_a/1997/ESACCI-OC-L3S-CHLOR_A-MERGED-1M_MONTHLY_4km_GEO_PML_OCx-199709-fv6.0_chlor_a.tif
```

## Time axis

`ESACCI_CADENCE` (monthly, 5day, daily) selects the THREDDS folder and the
`py/plan_cog.py --cadence`:

- `month`: one step per calendar month, the first day of the month as days
  since 1970-01-01 (`InlineValues`)
- `5day`: one step per 5-day period. The calendar is taken from the file
  dates: periods starting on days 1, 6, 11, 16, 21 and 26 of each month,
  on day of year 1, 6, ..., 361 (the OC-CCI 5-day product, restarting each
  1 January), or a continuous 5-day sequence. Dates fitting none stop the
  plan.
- `day`: one step per day

A step with no file is a hole, listed by the plan step; `ESACCI_MAX_MISSING`
stops the plan when there are more (default 0 monthly, 60 5-day, 300 daily,
since the early SeaWiFS record has real gaps). The 5-day and daily datasets publish STAC items
as ndjson and stac-geoparquet only (`STAC_ITEM_FILES=0`).

## Procedure on Setonix

Conversion, from the repository root (`rclone` uses its own configuration for
the `pawsey1197` remote; no keys are set in the job):

```sh
# smoke test: two files of 2025
sbatch --export=ALL,ESACCI_YEARS=2025,ESACCI_LIMIT=2 hpc/pawsey/esacci-cog.slurm
# the full monthly series; resubmit as is after a timeout
sbatch hpc/pawsey/esacci-cog.slurm
# the 5-day series (index with ESACCI_CADENCE=5day as well)
sbatch --export=ALL,ESACCI_CADENCE=5day hpc/pawsey/esacci-cog.slurm
```

Index over the local COGs, remapped to the public Acacia URL, then publish to
scratch from a login node (the source.coop keys last one hour):

```sh
bash hpc/pawsey/singularity-run.sh run.sh config/esacci-oc.sh
bash hpc/pawsey/singularity-run.sh run.sh config/esacci-oc.sh config/source-coop.sh publish verify-published
bash hpc/pawsey/singularity-run.sh catalog.sh products/oceancolour config/source-coop.sh publish
```

The build steps can also run as a batch job sized for the harvest (4 cores,
no `--mem`; see the header of `hpc/pawsey/run.slurm` for the measurements):

```sh
sbatch --export=ALL,ESACCI_CADENCE=5day,RUN_ARGS="config/esacci-oc.sh config/source-coop.sh" hpc/pawsey/run.slurm
```

The local `verify` step reads the forms, which reference the public URL, so
the COGs are uploaded before the index is built.

## Open points

- Variables: the job converts `chlor_a`, `chlor_a_log10_bias` and
  `chlor_a_log10_rmsd` from each download (`ESACCI_VARS`); the per-sensor
  observation counts in the same files are not converted. Each variable is
  its own dataset (`ESACCI_VAR`).
- Annual and 8-day cadences are not planned.
- Re-runs skip COGs already written; a file changed upstream under the same
  name is not detected (v6.0 is a fixed release, extended by new files).
- Coverage is global.

# IMOS animal tracking virtual stores

Byte-reference indexes of IMOS Animal Tracking Facility (AATAMS) data, read
in place from the IMOS public bucket (`s3://imos-data/IMOS/AATAMS/`,
ap-southeast-2; mirrored on NCI in `/g/data/sh74/IMOS_AODN/`). No data is
copied. `catalog.json` lists one STAC collection per dataset, each in its own
directory with the forms common to every group (`mdim.vrt`, `kerchunk/`,
`icechunk/`, `flat/`, `stac/`).

The sources are the MEOP-QC'd CTD profiles of satellite-relay tags (SMRU
SRDL) on southern elephant seals, Weddell seals, fur seals and turtles: one
classic netCDF file (Argo profile format) per tag under
`satellite_tagging/MEOP_QC_CTD/`, in two releases:

| release | files | profiles | levels | years |
|---|---|---|---|---|
| `IMOS-CTD_2024` (`*_hr1_prof.nc`, one `MEOP-CTD_2023-12-01`) | 265 | 126,518 | 1000 (1 dbar) | 2012-2024 |
| `MEOP-CTD_2017-10-01` (other `*_prof.nc`) | 299 | 140,868 | 12 to 28, by tag | 2004-2017 |

Classic netCDF is uncompressed, big-endian and contiguous, so every
variable, and every run of whole profiles of one, is a byte range known from
the file header (`py/cdf.py`, harvest engine `cdf`).

- `meop-ctd-2024`: the 2024 release as one cube, `(N_PROF, N_LEVELS)` =
  `(126518, 1000)`, the files' profiles in key order, one profile (4000
  bytes) a chunk. Arrays: `PRES`, `TEMP`, `PSAL`, `CHLA`, `DOXY`, `LIGHT`,
  each with `_ADJUSTED` and `_ADJUSTED_ERROR` (`CHLA`, `LIGHT` in 97 files,
  `DOXY` in 47; elsewhere fill). The per-profile variables (`JULD`,
  `LATITUDE`, `LONGITUDE`, `CYCLE_NUMBER`, `POSITION_QC`, ...) are
  materialised arrays along `N_PROF`, flags as ASCII codes; `tag` gives each
  profile's file (names in its attribute `source_names`, in the order of the
  STAC items' placements) and `row` its row in that file. Per-level QC flags
  and text variables are in `meop-ctd-tags`. License CC-BY-4.0 (the files'
  `license`).
- `meop-ctd-tags`: every file of both releases as a group named for its tag
  (`ct36-B-09`, `ct160-264-20`), holding every variable as stored (QC flags
  and text as char) and the file's global attributes, one chunk a variable.
  The 2017 files state the MEOP data policy (`distribution_statement`), the
  2024 files CC-BY-4.0. The VRT leaves out 2D char variables, which GDAL's
  netCDF driver reads as strings.

The STAC items are the tags, with a box and time range from their profiles.
Positions north of the equator are left out of the boxes: every species here
is southern, and 19,484 profiles of five campaigns (Weddell seals ct150 and
ct156, fur seals ct91, ct101 and ct110) have such positions with
`POSITION_QC` 1. The arrays keep the values as the files hold them.

`JULD` carries the files' `calendar = "julian"` with units of days since
1950-01-01. Julian and Gregorian leap years agree from 1950 to 2099, so the
day counts decode to the same dates in either calendar; xarray returns
them as cftime objects.

The files are rewritten in place (299 last written in 2017, 135 in 2024, 130
in 2025). Each store records the ETag of every file (`sources.meta.tsv`);
`py/s3_sources.py --stale` lists those changed since the build.

## Reading

```python
import icechunk, xarray as xr
st = icechunk.s3_storage(bucket="us-west-2.opendata.source.coop", region="us-west-2", anonymous=True,
                         prefix="ausantarctic/ausantarctic-scratch/imos-tracking/meop-ctd-2024/icechunk")
repo = icechunk.Repository.open(st, authorize_virtual_chunk_access={
    "https://imos-data.s3.ap-southeast-2.amazonaws.com/": icechunk.credentials.HttpAccess})
ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
# one tag of meop-ctd-tags: open_zarr(..., group="ct36-B-09")
```

```sh
gdal mdim info /vsicurl/https://data.source.coop/ausantarctic/ausantarctic-scratch/imos-tracking/meop-ctd-2024/mdim.vrt
```

GDAL's kerchunk Parquet reader (`/vsikerchunk_parquet_ref/`) resolves a
reference with no path (an absent chunk: a profile with no `CHLA`) against
the refs directory, which exists for a local copy, and fails with
"Decompressed tile ... has not expected size"; fsspec and the other forms
read fill there.

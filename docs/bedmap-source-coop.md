---
title: "Bedmap on source.coop"
---

Build and publication of `ausantarctic/bedmap`, the first product here that
holds both its material COGs and the virtual forms over them. Bedmap3 is the
only version built. Each version takes its own prefix, so an earlier version
joins without a new product or moved paths.

## COG settings

Tests on all seven arrays, full resolution only, GDAL 3.14 (the published
COGs are written by GDAL 3.13.3 in the project image):

| Setting | Total MB | Note |
|---|---|---|
| ZSTD level 9 | 280.80 | |
| ZSTD level 17 | 263.05 | 6.3% smaller, about 16 times the write time single-threaded |
| ZSTD level 9, predictor 2 | 207.19 | larger on four arrays: both uncertainties, `mask`, survey count |
| ZSTD level 17, predictor 2 | 181.74 | 31% smaller than level 17 |
| ZSTD level 9, `SPARSE_OK=TRUE` | 280.37 | 0.15% smaller |

Chosen: level 17, no predictor, `SPARSE_OK=FALSE`, 512 x 512 tiles. A
predictor is written as `imagecodecs_delta`, which GDAL's Zarr driver does not
read; without one GDAL reads the Kerchunk form. Overviews use AVERAGE, or
NEAREST for `mask` and `thickness_survey_count`, and add 40% to
`bed_topography` by 43%. They are not indexed.

## Findings for other static products

- A static grid has no time axis. `py/plan_static.py` writes 2D arrays, one per
  file; harvest and the VRT render take rank 2 without a leading axis.
- The forms reference public URLs that do not exist before upload.
  `BEDMAP3_LOCAL=1` builds a copy referencing the local COGs, so `verify` runs
  before anything is published.
- The grist catalog contract needs a date, so `config/bedmap3.sh` leaves out
  `grist`.
- `STAC_INTERVAL`, `STAC_LICENSE` and `STAC_TITLE` state what cannot be derived
  from a static store.

## Procedure

`hpc/vm/docker-run.sh` mounts `/rdsi` by default. Bedmap reads nothing there,
so `RV_MOUNTS=` is set.

```sh
export RV_MOUNTS=
bash hpc/vm/docker-run.sh run.sh config/bedmap3.sh prepare
BEDMAP3_LOCAL=1 bash hpc/vm/docker-run.sh run.sh config/bedmap3.sh
export SOURCECOOP_REPO=ausantarctic/bedmap SOURCECOOP_PRODUCTION=1
bash hpc/vm/docker-run.sh run.sh config/bedmap3.sh config/source-coop.sh \
  plan harvest collate render icechunk stac
```

Publication is `hpc/vm/bedmap3-publish.sh`, with the product keys exported. It
uploads the COGs and README files, publishes the virtual
forms, reads them back anonymously, and publishes the catalog.

---
title: "BedMachine on source.coop"
---

Build and publication of `ausantarctic/bedmachine`, which holds COGs of
MEaSUREs BedMachine Antarctica (NSIDC-0756) and the virtual forms over
them, as `ausantarctic/bedmap` does for Bedmap3. Version 4 (file V04.1) is
the only version built. Each version takes its own prefix (`v4.1/cog/`,
`virtual/bedmachine-v4.1/`). The product repo is
[AustralianAntarcticDivision/bedmachine](https://github.com/AustralianAntarcticDivision/bedmachine),
which holds the byte makers (`bytes/fetch.sh`, `bytes/bedmachine_cog.py`);
the config, product files and runner are here until raad.virtualize has a
tag to pin.

## Source

NSIDC distributes one netCDF-4 file per version, behind a NASA Earthdata
login, and withdraws a version when it is retired (version 3 on
2026-02-24). The virtual forms therefore reference COGs held on
source.coop, not the NSIDC file. The netCDF arrays are chunked (1905 to
3334 cells) with the shuffle filter and deflate. GDAL's Zarr driver reads
no shuffle filter in a release, so references to the netCDF chunks would
fail the codec criterion as well.

The terms are those of NASA EOSDIS: free to use without restriction, with
the citation (`products/bedmachine/README.md`).

## COG settings

The settings of Bedmap3 (`docs/bedmap-source-coop.md`): ZSTD level 17, no
predictor, 512 x 512 tiles, `SPARSE_OK=FALSE`, AVERAGE overviews (NEAREST for
the class arrays `mask`, `source`, `dataid` and `rgi`). Type and nodata are
those of the netCDF: Float32 and Int16 arrays keep `_FillValue` -9999 as
nodata, and `geoid` and the Int8 class arrays have none.

| Array | Type | MB |
|---|---|---|
| `bed` | Float32 | 775.0 |
| `dataid` | Int8 | 8.8 |
| `errbed` | Int16 | 31.2 |
| `firn` | Float32 | 234.1 |
| `geoid` | Float32 | 760.0 |
| `mask` | Int8 | 0.6 |
| `rgi` | Int8 | 0.1 |
| `source` | Int8 | 6.7 |
| `surface` | Float32 | 240.8 |
| `thickness` | Float32 | 246.2 |

The ten COGs are 2.30 GB, against 1.20 GB for the netCDF. Without a
predictor, Float32 compresses poorly: `bed` and `geoid` are 82% and 80% of
their uncompressed size with overviews. A floating-point predictor
(`PREDICTOR=3`) would make them smaller but is written as an imagecodecs
filter that GDAL's Zarr driver does not read, as for Bedmap3.

## Findings for other static products

- `py/plan_static.py` took one type and nodata for every file. BedMachine
  has Float32, Int16 and Int8 arrays, some with no nodata, so the plan now
  takes each file's own and requires only a common grid and tiling. The
  Bedmap3 and IBCSO v2 plans are unchanged by this.
- Int8 is new among the static products; `plan_static.py` maps it.
- Arrays with no nodata (`geoid` and the class arrays): Zarr v3 needs a
  `fill_value`, so the Icechunk form has 0 there with no `_FillValue`
  attribute; xarray masks a Zarr v3 array
  on the attribute only, so `mask` 0 (ocean) reads as 0. `py/verify.py`
  read the `fill_value` as the fill wherever the attribute was absent,
  which is right only for a NaN fill, and reported 30 mismatches; it now
  falls back to `fill_value` for a NaN fill only. A reader that masks on
  `fill_value` (xarray's `use_zarr_fill_value_as_mask=True`) would mask
  those zeros.
- Verify, against the local COGs: 330 windows across the full-resolution
  arrays and overviews, each read the same by the plan, the VRT, Kerchunk
  and Icechunk.

## Procedure

Fetch with an Earthdata token (`EDL_TOKEN`), then record the checksum:

```sh
mkdir -p work/bedmachine-raw && cd work/bedmachine-raw
f=NSIDC-0756_BedMachineAntarctica_19700101-20191001_V04.1.nc
u=https://data.nsidc.earthdatacloud.nasa.gov/nsidc-cumulus-prod-protected/MEASURES/NSIDC-0756/4/1970/01/01/$f
curl -L --fail -H "Authorization: Bearer $EDL_TOKEN" -o $f $u
printf '%s\t%s\t%s\t%s\n' $f $(stat -c %s $f) $(sha256sum $f | cut -d' ' -f1) $u > fetch.tsv
cd ../..
```

Build, verify against the local COGs, then build the public forms:

```sh
bash hpc/vm/docker-run.sh run.sh config/bedmachine.sh prepare
BEDMACHINE_LOCAL=1 bash hpc/vm/docker-run.sh run.sh config/bedmachine.sh
export SOURCECOOP_REPO=ausantarctic/bedmachine SOURCECOOP_PRODUCTION=1
bash hpc/vm/docker-run.sh run.sh config/bedmachine.sh config/source-coop.sh \
  plan harvest collate render icechunk stac
```

Publication is `hpc/vm/bedmachine-publish.sh`, with the product keys
exported. It uploads the COGs, verifies the public forms against them (the
publish gate needs that record, and the public forms cannot be read before
the COGs are up), publishes the forms, reads them back anonymously, and
publishes the catalog and README. The source.coop product
`ausantarctic/bedmachine` must exist first.

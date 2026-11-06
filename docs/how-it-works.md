---
title: "How it works"
---

A virtual store is a table plus a plan. The plan places every source file in
one global array; the table holds one row per chunk of every source. Every
form is a projection of the two.

| Step | Writes | Does |
|---|---|---|
| plan | `plan.vrt` | where each file sits in the global array (`gdal mdim mosaic`, `py/plan_cog.py`) |
| harvest | chunk index per file | offsets and sizes of every chunk, with GDAL or h5py (`py/harvest.py`) |
| collate | `store.sqlite` | one byterefs/0.1 table per dataset |
| render | `flat/`, `kerchunk/`, `icechunk/`, `mdim.vrt`, `stac/` | each form from the table |
| verify | | each form against GDAL reading the sources (`py/verify.py`) |
| publish | | upload, then read every form back anonymously (`verify-published`) |

All steps are `run.sh <dataset config> [publish target] [steps]`.

## The table

Three files, readable by any Parquet reader:

```
arrays.json            dims, shapes, chunks, dtype, fill, codec, remap rules, meta
refs_<array>.parquet   dim_0 ... dim_n, present, path, offset, size, info
sources.parquet        source_id, source, size, mtime, etag
```

One row of OISST `sst`:

```
dim_0..3  0 0 0 0      present 1
path      .../avhrr/198109/oisst-avhrr-v02r01.19810901.nc
offset    1025881      size 683590
info      COMPRESSION=DEFLATE; FILTER=SHUFFLE; ENDIANNESS=LITTLE
```

Specification: [byterefs/spec](https://github.com/byterefs/spec),
`spec/byterefs-0.1.md`. Stores built before 2026-11 say `mdim-refs/0.2`,
the same layout.

## One table, several endpoints

Paths are stored as scanned; a local mirror is the fastest place to scan.
Remap rules carried with the table give each reader a path it can open:
`public` for https, `gdal` for `/vsicurl/`. A rule asserts the bytes are
identical at both ends, and verify checks it (byterefs decision 0004).

```
target  prefix                                        replacement
public  /rdsi/PUBLIC/raad/data/www.ncei.noaa.gov/...  https://noaa-cdr-...s3.amazonaws.com/data/v2.1/avhrr/
gdal    (same)                                        /vsicurl/https://noaa-cdr-...s3.amazonaws.com/...
```

## What verify checks

Per array: the first chunk, one full row across the last dimension, four
random present chunks, one absent chunk, plus `scale_factor` and fill. Raw
values must hash the same as GDAL reading the sources through `plan.vrt`.

## File lists and staleness

A build reads its file list from the
[aad-filelist](https://github.com/mdsumner/aad-filelist) listing corpus and
keeps a record of every file it referenced (`sources.meta.tsv`). The `stale`
step compares that record with the corpus now: a file replaced at the same
URL, or withdrawn, is flagged before its byte offsets mislead a reader.

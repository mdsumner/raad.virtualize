# Pipeline results and findings

Runs of `run.sh` between 2026-10-20 and 2026-10-21. "Identical" means the
raw (unscaled) values of every checked window hash the same as GDAL reading
the sources through the plan VRT. verify checks the first chunk, one full
row across the last dimension, four random present chunks and one absent
chunk per array, plus `scale_factor` and fill value.

## Runs

| Run | Result |
|---|---|
| OISST, 30 files, 4 arrays (NOAA S3) | VRT, kerchunk and Icechunk identical. scale_factor and fill exact in every form. xarray opens the Icechunk store and decodes time. |
| Synthetic BRAN, 2 files, 168 chunks, 28 never written | VRT and Icechunk identical, including absent chunks. kerchunk identical except absent chunks (finding 3). |
| wxy-refs (wxylib core 1d5f349) on `out/flat` | `wxy warp --remap public` identical to GDAL on OISST and synthetic BRAN. |
| Scale test, 1,116,900 fake refs | collate 11 s; render 15 s; Icechunk 8 s. Store 87 MB, flat 6 MB, kerchunk 14 MB, Icechunk 22 MB (about 20 B per ref). |
| BRAN2023 `temp` 2010 over THREDDS | 1,116,900 refs. collate 12 s, render 16 s, Icechunk 5 s. VRT and kerchunk identical; Icechunk identical once read concurrency is lowered (finding 6). Published to the AADC transfer bucket; GDAL opens the VRT from there. |
| BRAN2023 `salt` Jan-Feb 2010 over THREDDS | 180,540 refs. All forms identical, locally and read back from the bucket. |
| Publish to S3 | Tested against a local S3 mock (moto) on OISST and synthetic BRAN, then against the AADC transfer bucket. |

## Findings

1. **GDAL `GetRawBlockInfo` is wrong for netCDF4/HDF5 files with unwritten
   chunks, and slow.** GDAL 3.13 turns block coordinates into a linear index
   for `H5Dget_chunk_info(index)`, which HDF5 counts over allocated chunks
   only, so one unwritten chunk shifts every later answer. GDAL master
   (0896c69ac3) fills all blocks with `H5Dchunk_iter` when block 0 is asked
   first; the fallback path is unchanged. Reported upstream. The harvest
   detects sparse files and rescans them with h5py; `--engine auto` uses h5py
   for local files and GDAL for remote ones.
2. **THREDDS cost of a harvest.** One BRAN month over THREDDS: GDAL 3.13
   about 70 s, 1.7k GETs, 35 MB; GDAL 3.14dev 39 s, 1.7k GETs, 33.5 MB; h5py
   with 64 KB fsspec blocks 53 s, 1.8k GETs, 115 MB; with 1 MB blocks over
   500 MB. The chunk index itself is about 33 MB per file and the time is
   round-trip bound (about 23 ms per GET), so parallel files are the lever.
   `py/probe_harvest.py SOURCE` measures this for any source.
3. **GDAL `/vsikerchunk_parquet_ref/` fails on absent chunks.** A row with
   null path and null raw (fsspec's "no such chunk") is opened as a path.
   verify labels it rather than failing. Does not affect fully allocated
   datasets such as BRAN.
4. **R JSON writers lose precision.** jsonlite's default `digits = 4` in
   blocklist's `.zmetadata` writer is the cause of BRAN's `scale_factor`
   0.0078 in earlier indexes. The copies here use `digits = I(17)`; the
   upstream one-line fixes are in blocklist and byteref.
5. **Packing is not checked by `gdal mdim mosaic`.** The mosaic checks
   dtype, nodata and dimensions across sources but takes scale and offset
   from the first. The harvest records packing per source and collate stops
   if it differs. With the HDF5 driver (no netCDF driver), `scale_factor` is
   not lifted to GetScale and the mosaic VRT keeps it as text at reduced
   precision; verify reads its reference value from the first source.
6. **THREDDS resets concurrent connections.** An Icechunk read across 12
   chunks fails with "Connection reset by peer" at zarr's default
   `async.concurrency` of 10 and succeeds at 4. GDAL reuses connections and
   does not trip it. verify steps concurrency down automatically.
7. **Reader gaps.** GDAL's Zarr v3 reader has no `numcodecs.shuffle`, so
   GDAL skips shuffled arrays in the Icechunk store. xarray decodes BRAN to
   float64 from the Zarr stores because JSON attributes lose the float32
   type of `scale_factor` (a gap in the store's attribute record).
8. `gdal mdim mosaic` rejects a 2-step time axis as irregularly spaced.
9. `wxy points` and `wxy zonal` have no `--remap`, unlike `wxy warp`.

## Legs

| Leg | Lang | Caveats |
|---|---|---|
| plan | GDAL CLI | One argument per source; batch beyond a few hundred files. |
| harvest | Python | No R producer yet; the gdalraster fork `getRawBlockRefs()` would write the same fragments. |
| collate | R | `refs_<array>` is a view with no index; materialise it beyond a few years of BRAN. |
| flat | R | Paths verbatim; remap rules travel in `arrays.json`. |
| MDIM VRT | R | Loses dimension type and direction, which the store does not hold. |
| kerchunk | R | Builds the whole positional grid in memory. |
| Icechunk | Python | One virtual chunk container per host. Manifests split along the first axis (`--split`, default 365) and the load commits every `--commit-every` refs (default 1M): the GHRSST MUR series, 22.8M refs, builds in 255 s at 4.7 GB peak (568 MB store). |
| verify | Python | `--published` reads the forms from object storage. |

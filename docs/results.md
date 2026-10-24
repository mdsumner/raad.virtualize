# Pipeline results and findings

Runs of `run.sh` between 2026-10-20 and 2026-10-23. "Identical" means the
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
| GHRSST MUR `analysed_sst` COGs 2024 (source.coop) | 935,496 refs. harvest 47 s (8 workers), collate 14 s, render 12 s, Icechunk 4 s (18.4 MB). Published; VRT and Icechunk identical read back from the bucket. kerchunk not read by GDAL (finding 10). |
| GHRSST MUR `analysed_sst` COGs 2002-2026 | 22,771,404 refs from 8,909 files. harvest 1,045 s, collate 385 s (1.2 GB store). Render first stopped on the arrow string limit (finding 11); after the fix, render 282 s (flat 136 s, kerchunk 139 s), Icechunk 105 s, 568 MB in 23 commits. |
| STAC render, synthetic BRAN (2 netCDF) and synthetic MUR COGs (3 days, one missing) | Collection and items validate against STAC 1.1.0 core, datacube 2.2.0, xarray-assets 1.0.0, file 2.1.0 and projection 2.0.0 schemas. From the collection: the Icechunk asset opened with its `xarray:open_kwargs` and `rv:virtual_chunk_containers`, and the VRT asset, both match the item's source file. GDAL STACIT opens the items; GDAL GTI opens `items.parquet` (rustac stac-geoparquet) directly; gdalcubes builds a daily cube from the items with the missing day empty. |
| terra on the rendered VRT | `terra::rast("mdim.vrt", md = TRUE)` reads BRAN-shaped VRTs with time and depth decoded. Before this change the COG VRT had no time units (the plan's `<Unit>` never reached the store), so terra, xarray and STAC saw raw day numbers; collate now takes coordinate units from the plan where the harvest has none. terra still guesses the CRS: the store holds no SRS (finding 13). |
| STAC render, 8,909 items (GHRSST-shaped store with synthetic placements) | 44 s in R (JSON serialization is most of it); `items.ndjson` 7.7 MB, `items/` 8,909 files, collection 1.1 MB. |
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
10. **TIFF predictor has no portable Zarr codec.** `PREDICTOR=2` is
    horizontal differencing restarted on every row. numcodecs `delta` runs
    over the flattened chunk and decodes the first value of every row
    wrongly, so the forms use `imagecodecs_delta` (axis -1), as tifffile
    writes it. Readers of the kerchunk and Icechunk forms need imagecodecs;
    GDAL's Zarr driver reads neither form. The VRT reads the TIFFs directly.
11. **Arrow string arrays hold at most 2 GB.** The path column of the full
    GHRSST series is 3.3 GB; the flat store writer now builds columns in
    chunks of 1M rows.
12. **GDAL reads COG tiles serially through the VRT.** One full-width row of
    one GHRSST day (71 tiles over https) took 252 s through the plan and
    166 s through the rendered VRT; Icechunk read it in 6 s. Cause not yet
    diagnosed.
13. **The store holds no SRS.** The plan VRT carries it (`<SRS>` on the data
    array) but collate drops it, so the rendered VRT, kerchunk and Icechunk
    forms are CRS-less and terra guesses lon/lat. The STAC render reads the
    SRS from the plan beside the store. Recording it in `arrays` would fix
    every form.
14. **Stores must state what readers would otherwise guess.** A browser
    explorer over the two BRAN2023 kerchunk stores in mdsumner/virtualized
    found every guess was about meaning, not layout: fill values that
    disagree (`fill_value` -32767 against `_FillValue` -32768 in the
    VirtualiZarr build), rounded packing (item 4), bare `NaN` in JSON, and
    dimension roles. Collate now stops when `_FillValue` or `missing_value`
    disagree with nodata; harvest writes strict JSON; the plan's dimension
    `type` and `direction` are kept in `meta.dimensions` and written back by
    the VRT render; `arrays.json` carries `dimensions` and a per-array
    `summary` (grid chunks, present, absent, referenced bytes).

## Legs

| Leg | Lang | Caveats |
|---|---|---|
| plan | GDAL CLI, Python | Sources passed as a response file (`@sources.txt`). GeoTIFF sources use `py/plan_cog.py`, since the mosaic does not take GeoTIFF. |
| harvest | Python | No R producer yet; the gdalraster fork `getRawBlockRefs()` would write the same fragments. |
| collate | R | `refs_<array>` is a view with no index; materialise it beyond a few years of BRAN. |
| flat | R | Paths verbatim; remap rules travel in `arrays.json`. Columns built in chunks of 1M rows. |
| MDIM VRT | R | Loses dimension type and direction, which the store does not hold. |
| kerchunk | R | Builds the whole positional grid in memory. |
| Icechunk | Python | One virtual chunk container per host. Manifests split along the first axis (`--split`, default 365) and the load commits every `--commit-every` refs (default 1M): the GHRSST MUR series, 22.8M refs, builds in 255 s at 4.7 GB peak (568 MB store). |
| STAC | R | Item time range and bbox from placements and coordinates; CRS and dimension types from the plan VRT (the store holds neither). Media types for the kerchunk and Icechunk assets follow no settled convention (`application/vnd+zarr`, `application/vnd.zarr+icechunk`). |
| verify | Python | `--published` reads the forms from object storage. |

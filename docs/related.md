---
title: "Related"
---

This repository is the engine. The others hold what it reads, what it
follows, and what reads it.

| Repository | Why it exists |
|---|---|
| [mdsumner/aad-filelist](https://github.com/mdsumner/aad-filelist) | Listing corpus: every source listed on a schedule, every run kept. Builds read their file lists here; a file replaced at the same URL shows up as a change. |
| [mdsumner/bowerbird-byterefs](https://github.com/mdsumner/bowerbird-byterefs) | Will collect every dataset's table in one place and run the stale check against the corpus. |
| [byterefs/spec](https://github.com/byterefs/spec) | The table format, so other readers (wxy-refs, arrir, DuckDB) can use it without this code. |
| [AustralianAntarcticDivision/ghrsst-cogger](https://github.com/AustralianAntarcticDivision/ghrsst-cogger) | Writes the GHRSST MUR COGs indexed here ([ausantarctic/ghrsst-mur-v2](https://source.coop/ausantarctic/ghrsst-mur-v2)). |
| [hypertidy/grist](https://github.com/hypertidy/grist) | Reads the published catalogs from R, one row per date and array. |
| [hypertidy/vrtstack](https://github.com/hypertidy/vrtstack), [hypertidy/blocklist](https://github.com/hypertidy/blocklist) | COG collections as multidim VRT; the kerchunk writer vendored here. |

## Elsewhere

[Earthmover's icechunk-datacube-ingestion agent
skill](https://github.com/earth-mover/agent-skills/tree/main/icechunk-datacube-ingestion)
is a procedure for building one Icechunk repository from many files with
VirtualiZarr, and the [GOES-16
ingest](https://www.earthmover.io/blog/virtual-zarr/) behind it is the
largest worked example (7.1 billion refs). Its practices hold here too:
commit in batches, split manifests past about a million refs (along the
append axis about as often as you commit), load only coordinate variables,
and keep the write-time cache small. `py/render_icechunk.py` follows them,
rendering Icechunk from the table rather than from the files. One
exception: the skill calls kerchunk deprecated and steers away from it. We
keep writing kerchunk (JSON and Parquet), because GDAL and other readers
outside Python need it today; Icechunk is one output among several.

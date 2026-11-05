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

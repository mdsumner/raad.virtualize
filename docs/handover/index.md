---
title: "Ausantarctic production handover: TLDR"
date: 2026-11-05
search: false
---

We index Southern Ocean and Antarctic array data where it already sits and
publish cloud-readable indexes on source.coop, so nobody has to copy the data
to read it fast. Each dataset gets one table of byte references (which bytes
of which file hold each chunk); the GDAL VRT, kerchunk, Icechunk and STAC
forms are all rendered from that table. Three repos do the work: one lists the
source files, one builds and checks the indexes, one will collect the tables
in one place.

The picture of where every dataset's bytes, builds and indexes sit is the
[handover snapshot](snapshot.html).

## The repos

The first three carry the work; the rest frame it.

| Repo | What it is | What production changes |
| --- | --- | --- |
| [mdsumner/raad.virtualize](https://github.com/mdsumner/raad.virtualize) | The engine: plan, harvest, collate, render, verify, publish. One checkout per machine. | Pinned by tag. Dataset configs and product READMEs move out to per-product repos. |
| [mdsumner/aad-filelist](https://github.com/mdsumner/aad-filelist) | The listing corpus: every source listed on a schedule, every run kept. Builds read file lists from it. | Stays. Publishes to source.coop once Actions holds a credential. |
| [mdsumner/bowerbird-byterefs](https://github.com/mdsumner/bowerbird-byterefs) | Will collect every dataset's byte-reference table in one place and run the stale check. README only so far. | Where the central table lives, and in what format. |
| [byterefs/spec](https://github.com/byterefs/spec) | The table format (byterefs/0.1) and its decision records. | Nothing moves. |
| ghrsst-cogger | Turns GHRSST MUR netCDF into COGs on source.coop. | Could also own the GHRSST index. |
| per-product repos (new) | One per production product, on the model of IBCSO: landing text, dataset list, configs, runner, credential. | Created by the production team. |
| grist, sds, raadtools | Read the published catalogs, mostly from R. | Catalog rows carry store URLs, so a move rewrites them. |

## Where things are today

Three datasets are already in production; the rest are drafts in the scratch
product (unlisted, still readable). "Ours" means COGs we wrote and host;
"theirs" means we index the publisher's own files.

| Dataset | Bytes | Built on | Index now |
| --- | --- | --- | --- |
| IBCSO v2, 2024, 2025 | ours, source.coop `ibcso/<release>/cog/` | Nectar VM | production `ibcso/virtual/` |
| Bedmap3 | ours, source.coop `bedmap/bedmap3/cog/` | Nectar VM | production `bedmap/virtual/` |
| GEBCO 2024 to 2026 | ours, source.coop `gebco/` root | Nectar VM | production `gebco/virtual/` |
| GHRSST MUR | ours, source.coop `ghrsst-mur-v2/YYYY/MM/DD/` | Nectar VM | scratch `ghrsst/` |
| ESA CCI ocean colour (6) | ours, Pawsey Acacia `aad-derived/esacci-oc` | Pawsey Setonix | scratch `oceancolour/` |
| OISST v2.1 | theirs, NOAA public S3 | Nectar VM | scratch `oisst/` |
| G02202 sea ice, north and south | theirs, NSIDC | Nectar VM | scratch `seaice/` |
| AMSR2 ASI sea ice, south | theirs, Uni Bremen | Nectar VM | scratch `seaice/` |
| BRAN2023, 9 variables | theirs, NCI THREDDS | NCI Gadi | scratch `bluelink/` |
| REMA v2 | theirs, PGC bucket | not built | none, listing only |

## Questions to decide together

None of these is decided. We'd rather design them with the team than hand
over a layout.

1. **Product shape.** One production product per scratch group (sea ice as one product), one per source, or one index product with groups.
2. **Byte layout.** One rule for our own COGs (IBCSO's `<release>/cog/` is the candidate); GEBCO and GHRSST differ today.
3. **Landing pages.** One fixed "where things are" block at the top of every product README: bytes, index, where it's built, how to open it.
4. **Machines.** Which of Nectar, Gadi and Setonix the team owns, and which become scheduled runners.
5. **Central refs.** Where the collected tables live on source.coop, and whether products keep their own copies.
6. **Moves.** Copy the existing indexes or rebuild them; a rebuild gives every dataset the build record the stale check needs.

## How to get up to speed

Point a coding agent at each repo (read-only) to build your own picture, then
land the design with Michael in shared sessions, his agents and yours
answering questions side by side. A starting brief:

```markdown
Read mdsumner/raad.virtualize (read-only; do not run builds or publish).
Explain for an operations team taking over production:
- what each step of run.sh does and what it reads and writes
- where a dataset's source files come from (config/<dataset>.sh, py/corpus.py)
- what is published for one dataset (ausantarctic/ibcso/virtual/ibcso-v2/)
  and which files record the store's own URL
- what needs credentials, and on which machine each config runs (hpc/)
Answer with file paths. List what you could not work out as questions.
```

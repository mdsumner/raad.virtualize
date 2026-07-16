# raad.virtualize

Virtualization of the raad file collection and related online datasets: one
central store of byte references, from which published cloud-native forms
(kerchunk, Icechunk, VRT) are derived as projections.

This repo is not stable and will change shape. This README documents the
model; the implementation spans several software projects currently in flux.


## Design

Every array dataset consists of granules (netCDF, HDF5, COG, GRIB) in which
each chunk of each array occupies a byte range. Cloud-native access to
archival data — kerchunk, VirtualiZarr, Icechunk, GDAL multidim VRT — all
reduces to knowing those byte ranges and pointing readers at them, but the tools
store the information in memory or in bespoke file stores. 

This project inverts that model: each granule is scanned once into a durable
store. Every published form is then a projection of the store — a remap of
URIs, a selection of files, an assignment of a global index, a serialization.
The expensive operation (reading chunk indexes out of 16k+ HDF5 files) could in theory be
run only once. 

## The store

A plain SQLite database with two tables:

- `files(file_id, source)` — one row per granule harvested
- one table per array, e.g. `sst(file_id, idx0..idxN, present, offset, size)`
  keyed on (file_id, within-file chunk coordinate)

The store has no knowledge of time, datasets, mirrors, or Zarr. It answers
exactly one question: for this source, this array, this chunk — where are the
bytes.

### The source rule

A source is the URI at harvest time — `file:///rdsi/...`, `https://...`,
`/vsis3/...` — recorded verbatim. That URI is the key that byte offsets are
bound to. Downstream consumers treat it as "where and what was harvested" and
remap by their own rules (local root to public https, vsis3 to s3://, mirror
to mirror). No remapping knowledge is encoded in the store, because those
rules differ per dataset and change over time.

Because prelim/final churn arrives as *renamed files*, a given source
string is immutable content. Incremental
harvest is "scan the sources not already in the store". Preliminary and final
versions of a day coexist in the store as distinct sources; choosing
between them is a projection.

## Projections

Dataset-specific logic lives in projections, applied at read/publish time:

- date extraction from filenames and assignment of a global time index
- dedup policy (prefer final over preliminary, or keep both as two canons)
- URI remapping to whichever endpoint a published form should reference
- join with array metadata (dtype, chunk shape, codec, fill, coordinates),
  which the store deliberately does not hold — it comes from the mdim VRT
  or from template-parsing a single representative granule

A "canon" is the store plus a projection: the OISST daily cube is the store
joined with the VRT concat logic. One store can carry many canons.

## Published forms

Three sibling renderings, none derived from another:

1. **GDAL multidim VRT** — built by `vrtstack` from the file listing plus a
   time-pattern rule; updated daily at
   https://projects.pawsey.org.au/aad-index/oisst/oisst-mdim.vrt.
   Carries the array structure, attributes, and inline coordinates; it is
   the metadata half that the store does not duplicate.
2. **kerchunk (parquet)** — full-rewrite manifest for fsspec/xarray interop.
3. **Icechunk** — the transactional target: bulk-load history once, then
   append new days as commits. Records referenced-file mtimes and errors
   clearly if a source file changes under a stale ref, which matters given
   prelim/final churn across three mirrors.

`blocklist::virtualize_mosaic` already produces stage-2 output from the
VRT; the remaining consolidation is rewiring it to read refs from the store
instead of rescanning files, at which point publish steps have no file
access at all and can run anywhere the (small) store and VRT are reachable.

## Current state

- **OISST** (NOAA v2.1 AVHRR daily, 1981-09-01 to present): fully harvested.
  16,387 files, four rank-4 arrays (sst, anom, err, ice), scanned on raad
  openstack against the /rdsi mirror in ~20 minutes with 8 mirai daemons.
  The store is published as a release artifact: `oisst-refs.sqlite`.
  Coverage is daily-complete, so the time axis is affine
  (origin + index * 1 day) and need not be stored.
- **blocklist** does the per-file scan (`scan_source_chunks`) and the
  VRT parse (`parse_mosaic_vrt`); recent performance work makes the scan
  practical at collection scale.
- **vrtstack** renders the mosaic VRT from a listing plus concat rule.

## Roadmap

- Rewire stage 2 (kerchunk/Icechunk emission) to read from the store; the
  scan then happens exactly once per granule across all published forms.
- Feed the store from the raad openstack file cache: every dataset
  raadtools handles is a candidate, since the schema is dataset-agnostic.
- Add online-only datasets harvested remotely: GHRSST COGs (source.coop),
  Bluelink/BRAN (NCI + THREDDS). The store does not distinguish between
  local and remote sources — the source rule covers both.
- A small per-dataset registry (arrays, roots, remap rules, dedup policy)
  beside the store — projection config, kept out of the chunk tables.
- Longer term this store is a prototype of the reference-extraction
  model proposed for GDAL itself (`gdal mdim` chunk-reference extraction,
  built on `GDALMDArray::GetRawBlockInfo`): the same table, produced by one
  code path for every driver, consumable as a virtual multidim store.

See [with-oisst-gdal.md](with-oisst-gdal.md) for an example of the general
store structure with OISST data via GDAL.



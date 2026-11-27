# Assertion step: status

Request: `requests/assertion-step.md` (PR #124). One dated line per step,
newest last. Blockers go at the top, marked BLOCKED.

## Mechanism (pass 1 decisions)

- Assertion documents live in this repository, `assertions/<dataset>/<variable>.json`,
  keyed to the dataset id and variable (`subject.dataset`, `subject.variable`)
  and not to a published store's URL and metadata digest: the published forms
  are render outputs, so writing the assertion into them changes their digest
  and would make a digest-keyed document stale on its first use.
  `derived_from` points at the storecard document the assertion restates.
- Step `assert` (py/assertions.py), after collate and before render: checks
  each document against the store (variable, dimensions, shape, transform
  restated from the 1-D coordinates) and the plan (`<SRS>` EPSG code, where
  the plan has one), then records it in the store's meta key `assertions`.
  A failed check stops the build.
- Emitters read the record through `mr_array_list()` (R/mdimrefs_pipeline.R):
  flat `arrays.json`, kerchunk `.zattrs` and Icechunk array attributes get the
  `spatial:`/`proj:` keys and their `zarr_conventions` registrations; the mdim
  VRT gets `<SRS dataAxisToSRSAxisMapping>`; STAC items take `proj:*` from the
  assertion and the collection lists `rv:assertions`. Root attributes of the
  flat, kerchunk and Icechunk forms list the applied assertions (id, status,
  digest).
- Done test: py/assertion_cards.py cards each projection (storecard for the
  Zarr forms, osgeo.gdal for the mdim VRT, the items for STAC) and compares
  with the assertion, and for the Zarr forms compares the card with the
  published card under storecard's overlay. Reports go to `cards/<dataset>.md`.

## Log

- 2026-11-27 started. Branch `claude/project-thread-6t1wb1` (the session's
  branch, in place of `assertion-step`). Before card of the published
  G02202 south Icechunk: CRS_NOT_DECLARED, PROJECTED_NO_GRID_MAPPING; with
  storecard's overlay: no findings. Published mdim.vrt has no `<SRS>`; STAC
  items already carry `proj:code` EPSG:3412 from the plan.
- 2026-11-27 G02202 south: PASS in all four projections (assertion-cards
  run 45932750068): kerchunk and Icechunk cards carry EPSG:3412 and the
  transform, with no CRS findings, and equal the published cards under
  storecard's overlay on grid, crs and findings; mdim.vrt has
  `<SRS dataAxisToSRSAxisMapping="3,2">EPSG:3412`; STAC items unchanged in
  value (EPSG:3412 from the plan before, from the assertion now). Card
  diff: cards/g02202-v6-daily-south.md.
- 2026-11-27 next: G02202 north, ASI south and OISST in the same job
  (assertions imported with `py/assertions.py import`). GHRSST MUR waits for
  overview levels; its storecard assertion covers the base level only.

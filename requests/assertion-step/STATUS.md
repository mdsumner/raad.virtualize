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

## Ledger: asserted field by projection

Slot each projection gives the asserted facts (bytes-in-place item 13).
Native: a field of the form's own schema; none: not carried.

| Field | flat arrays.json | kerchunk (Zarr v2) | Icechunk (Zarr v3) | mdim.vrt | STAC items |
| --- | --- | --- | --- | --- | --- |
| proj:code | array attrs | .zattrs | array attributes | `<SRS>` (native) | proj:code (native) |
| spatial:transform | array attrs | .zattrs | array attributes | none (1-D x/y indexing variables restate it) | proj:transform (native) |
| spatial:shape | array attrs | .zattrs | array attributes | none (dimension sizes) | proj:shape (native) |
| crs_axes | none | none | none | dataAxisToSRSAxisMapping (native) | none |
| which assertions | top-level `assertions` | root .zattrs `assertions` | root attributes `assertions` | none | collection `rv:assertions` |

Readers of the Zarr attributes: GDAL 3.13 and later read zarr-conventions
`proj:`/`spatial:` with the registrations written; earlier GDAL, xarray and
kerchunk readers see plain attributes. CF `grid_mapping` is not written
(not an assertion key; out of scope here).

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
- 2026-11-27 G02202 north, ASI south, OISST: PASS in all four projections,
  Zarr cards equal the published cards under storecard's overlays (run
  45935319931). OISST first failed the card comparison only because the
  checker applied one variable's overlay; fixed in 7282509. The OISST
  mdim VRT mapping is 3,4 (time, zlev, lat, lon; EPSG:4326 lat first), and
  its STAC items gain proj:* (the plan has no `<SRS>`, so they had none).
  Cards: cards/<dataset>.md for all four.
- 2026-11-27 next: GHRSST MUR (overview arrays `_x<f>` need the assertion
  scaled per level, or assertions per level); Bluelink has no assertion.
  Not published: a scratch republish of these four needs Michael's go-ahead.
- 2026-11-27 GHRSST MUR started. Overview levels: the assert step derives
  each level's assertion from the base one (same CRS and corner origin,
  cell size times overview_factor, the level's shape and dimensions;
  `level_doc` in py/assertions.py) and checks it against the level's
  coordinates; a document in the directory for a level takes precedence.
  Checked on the published MUR arrays.json: all five levels agree with
  their coordinates. Card findings are now compared per variable.
- 2026-11-27 GHRSST MUR: PASS, base and five overview levels, in kerchunk,
  Icechunk and mdim.vrt (STAC: base). The published-card comparison is not
  made: storecard's MUR document is stale against the republished store
  (overview levels added after it was made). Card: cards/ghrsst-mur-cog-analysed_sst.md.
- 2026-11-27 next: Bluelink needs an assertion (proposed EPSG:4326;
  LON_0_360 and Y_ASCENDING are facts, not targets), from Michael.
- 2026-11-27 Bluelink: EPSG:4326 asserted for the nine daily variables
  (Michael's choice), assertions/bluelink-daily-<var>/<var>.json, transform
  restated from the store's 1-D axes as published (float32-derived: step
  0.10000000369999582, origin -74.99999694728771 on t-grid y), not rounded
  to 0.1. No storecard document exists, so no published-card comparison.
- 2026-11-27 Bluelink daily, nine variables: PASS in all four projections
  (assertion-cards run 45941708694). Kerchunk and Icechunk cards carry
  EPSG:4326 and the transform and lose CRS_NOT_DECLARED; LON_0_360,
  Y_ASCENDING and COORDS_NAMED_MISSING remain (facts of the store, not
  assertion targets). mdim.vrt mapping 3,4 for the 4-D variables (temp,
  salt, u, v, w) and 2,3 for the 3-D ones (eta_t, mld, tx_trans_int_z,
  ty_trans_int_z). STAC items gain proj:*. Evidence in each document cites
  the NCI GeoNetwork BRAN2023 record: its referenceSystemInfo holds an empty
  RS_Identifier, so the catalogue declares no CRS. Cards:
  cards/bluelink-daily-<var>.md.
- 2026-11-27 all six datasets in the request pass. Open: storecard's MUR
  document is stale (rebuild in storecard); a scratch republish of the
  rendered forms needs Michael's go-ahead.
- 2026-11-27 republish script: hpc/vm/assertion-republish.sh (build: fetch
  the published store and plan, assert, render, icechunk, grist, stac,
  verify, no keys; publish: publish and verify-published with the scratch
  keys). Waiting on Michael to run it on the VM.
- 2026-11-27 G02202 south REPUBLISHED to scratch with the assertion applied
  (Michael, VM clone at 54f8069; verify and verify-published SAME, grist
  rows agree). Live cards, no overlay: kerchunk and Icechunk EPSG:3412 via
  proj:code on the array, transform [25000, 0, -3950000, 0, -25000,
  4350000], costume B, no findings; mdim.vrt
  `<SRS dataAxisToSRSAxisMapping="3,2">EPSG:3412`; collection lists
  rv:assertions. A git worktree fails inside the container (its .git file
  points outside the mount): run from a plain clone.
- 2026-11-27 thumbnails: py/thumbnail.py rotated polar stereographic grids
  as if 0..360 longitude (x in metres passes "max > 180, span > 350"), so
  the G02202 thumbnails were split and swapped; fixed in 3eb327b (rotate only
  when x is within 0..361). ASI south never had a published thumbnail.
  assertion-republish.sh gains stac and publish-stac phases to redraw them.
- 2026-11-28 thumbnail rotation removed altogether (Michael: the preview is
  an image of the array as stored); only the south-up flip remains.
- 2026-11-28 live cards after Michael's batch publish, no overlay: G02202
  south EPSG:3412 and north EPSG:3411, ASI south EPSG:3976 (Y_ASCENDING
  left, a fact), OISST EPSG:4326 (LON_0_360, Y_ASCENDING left) in kerchunk
  and Icechunk; each mdim.vrt has its `<SRS dataAxisToSRSAxisMapping>`; each
  collection lists rv:assertions. CRS_NOT_DECLARED is gone from all four.
  MUR and Bluelink not yet republished. Thumbnails on the four were drawn
  before b889262 (G02202 still split, OISST rotated; ASI has none).

# Request: assertion step in the raad.virtualize pipeline

Status: request, 2026-11-27. Any Claude Code session with this repository
can work it: on the Nectar VM for steps that need built work directories or
scratch publish credentials, in the cloud for metadata-only steps (cards,
diffs, emitter code). Background (project notes): bytes-in-place.md section
11 item 15.

## Goal

Every published projection of a store (Zarr, kerchunk JSON/Parquet,
Icechunk, mdim.vrt, STAC) carries the same asserted facts. Assertions are
storecard assertion documents (hypertidy/storecard ASSERTIONS.md, v0): only
zarr-conventions `spatial:` and `proj:` keys in `asserts`, with `evidence`,
`by` and `status`. They become an input to render, and every emitter applies
them.

## Done test, per store

For each projection P of store S:

    card(P) == card(source of S, assertions=[A_S])

on the sections the assertions touch (grid, crs, and later values). Each
pass: render, card every projection, diff, then fix the pipeline or the
assertion. A finding that is a fact rather than a defect (LON_0_360,
Y_ASCENDING) is not a target.

## Order

1. G02202 v6 daily south. Source declares EPSG:3412, plan.vrt keeps it, the
   Zarr forms drop it (storecard finding 2026-11-09). Assertion exists:
   storecard `assertions/ausantarctic/g02202-v6-daily-south/`. This pass
   builds the mechanism.
2. G02202 v6 daily north, ASI AMSR2 v5.4 daily south.
3. OISST v2.1 daily (no CRS anywhere; EPSG:4326 by convention; tests that
   evidence carries through).
4. GHRSST MUR COG (overview levels; `_x<f>` sibling arrays).
5. Bluelink (no assertion yet; CF packing question open).

## Scope of the mechanism (proposal, to settle in pass 1)

- Assertion documents keyed to the raad.virtualize dataset id and the
  build, not to a third-party store URL. Location: `assertions/<dataset>/`
  in raad.virtualize, or read from storecard; decide in pass 1.
- `arrays.json` records which assertions were applied (id, status, digest).
- Emitters: Zarr/Icechunk attrs (storecard `to_zarr_attrs`), STAC asset
  `proj:*` (`to_stac_patch`), mdim.vrt SRS and axis mapping (`to_vrt`, or the
  existing plan SRS path).
- A ledger row per (assertion field, projection): native slot, lossy, none.
  Extends bytes-in-place item 13.

## Working rules on the VM

- The shared checkout `~/Git/raad.virtualize` may be running jobs: never
  switch its branch mid-run, never kill containers by image. Work in a git
  worktree, e.g. `~/Git/raad.virtualize-assert`, on branch
  `assertion-step`.
- Docker image `ghcr.io/hypertidy/gdal-r-python-extras:latest`, mounted at
  `/v`. Containers run as root; any `sudo chown` is a separate step for
  Michael, never inside a combined block.
- Publish nothing to source.coop production. Scratch publishes only after
  Michael says so.
- Repository writing style: AGENTS.md (technical voice, no "we").

## Visibility protocol

- Push the branch early and open a draft PR in mdsumner/raad.virtualize
  titled "Assertion step: apply storecard assertions in every projection".
  The project thread watches that PR.
- Keep `requests/assertion-step/STATUS.md` on the branch: one dated line per
  step (started, store, result, next). Commit and push it at each step.
- After each store, commit the card diff as
  `requests/assertion-step/cards/<dataset>.md` (before and after, per
  projection) and push. That file is the checkpoint the thread reports.
- Blockers go at the top of STATUS.md with "BLOCKED:" and a one-line ask.

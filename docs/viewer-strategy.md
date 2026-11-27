---
title: "Viewer strategy"
---

How published stores are viewed in a browser, and the state of each store.
The viewer itself is `docs/viewer/index.html` (#126).

## Where the viewer lives

The viewer is code in this repository, the one that writes the metadata it
reads. Each store carries a link to it and holds no HTML.

- **Not a static copy in each store.** A copy published with a store freezes
  at that store's publish. A viewer fix, or a new field in the catalog,
  would then mean republishing every dataset. A store holds data and
  metadata only.
- **This repository, not the site that links to it.** The viewer reads a
  contract that this repository writes:
  - the collection's `renders` entry and the `browser` asset;
  - `spatial:*` and `proj:code` (#125);
  - the overview naming `<array>_x<f>` (decision 0006);
  - the virtual chunk containers.

  When viewer and writer ship together, one PR changes both sides. CI can
  then open the viewer against each published collection after a rerun, so
  a broken contract fails in CI instead of in a reader's browser console.
  This matters once the production jobs run unattended.
- **The ausantarctic site is the entry point.** It links to the same page,
  or embeds it, with `?catalog=<production root>`. The viewer reads only
  STAC, so any host can serve it. If this repository is renamed or split
  into product repositories, the page moves with the contract.

## Link from each store

The `stac` step writes one link per collection (#126, `ebcaeba`):

```json
{"rel": "alternate", "type": "text/html",
 "href": "<viewer>?collection=<collection URL>"}
```

STAC clients show it as a view link, and the store holds no viewer code.

## Portolan and the viewer

The Portolan browser has been enabled as far as the stores allow:

- CRS and grid metadata through the assertions (#125);
- a CORS relay for chunk hosts that send no CORS header (the `browser`
  asset, #126);
- a kerchunk asset type that Portolan no longer misreads as a Zarr store.

Polar grids still do not draw: deck.gl-raster does not support them.

The viewer in this repository draws one field of an array in the array's
own CRS, one canvas pixel per cell, with the coastline projected over it
(proj4). It needs no mesh, so grids that hold a pole draw as stored. It
picks the coarsest `<array>_x<f>` level within an 8M-cell budget. It takes
the georeference from `spatial:transform` and `proj:code`, or else from the
1-D coordinate arrays and `cube:dimensions`.

## Store by store

*Read path* is what the browser fetches: the `icechunk` asset direct, or
the `browser` asset through the relay where the chunk host sends no CORS
header. CORS was checked with a GET carrying an `Origin` header (LEDGER,
2026-11-27).

| Stores | CRS | Chunk host CORS | Read path | Viewer | Open |
|---|---|---|---|---|---|
| G02202 v6 daily south | EPSG:3412 | none (NSIDC) | `browser`, relay | Draws (#126 test) | Re-collate for the browser rules, then `browser stac publish`. Portolan: polar |
| G02202 v6 daily north | EPSG:3411 | none (NSIDC) | `browser`, relay | Not yet | As south |
| ASI AMSR2 v5.4 daily south | EPSG:3976 | none (Bremen) | `browser`, relay | Draws through a relay stand-in, about 26 s | Browser rules. Row chunks: 2,656 requests per field; icechunk-js merges none. Portolan: polar |
| OISST v2.1 daily | EPSG:4326 | `*` (NOAA S3) | `icechunk` | Untested | Longitude 0 to 360 |
| GHRSST MUR | EPSG:4326 | `*` (source.coop) | `icechunk` | `analysed_sst_x16` draws (#126 test; `imagecodecs_delta` in JS) | Republish with assertions |
| Bluelink BRAN daily, nine variables | EPSG:4326 | `*` on GET; 403 on HEAD with an Origin (THREDDS) | `icechunk` | Untested | Republish with assertions; check that the reader sends no HEAD. Longitude 0 to 360 |
| Bedmap3 | EPSG:3031 | `*` (source.coop) | `icechunk` | `bed_topography_x8` draws (#126 test) | Assertion document. Portolan: polar |
| BedMachine v4.1 | EPSG:3031 | `*` (source.coop) | `icechunk` | Untested | Assertion document. Portolan: polar |
| IBCSO v2, annual 2024 and 2025 | EPSG:9354 | `*` (source.coop) | `icechunk` | Untested | Assertion documents; the viewer needs a proj4 definition for EPSG:9354. Portolan: polar |
| GEBCO 2024 to 2026 | EPSG:4326 | `*` (source.coop) | `icechunk` | Untested | Assertion documents |
| ESA CCI ocean colour v6.0, six | EPSG:4326 | `*` (Pawsey) | `icechunk` | Untested | Assertion documents |
| IMOS MEOP, two | profiles | `*` (IMOS S3) | n/a | Not a grid | Out of scope |
| ACCESS-ESM1.6 ocean temp | tripolar ocean grid | `*` (Pawsey) | n/a | No affine grid to draw | Out of scope until a curvilinear path |

## CI check

Planned (not in #126): after each rerun, open the viewer headless against
each published collection and fail on a draw error, using the same reads
as the #126 tests.

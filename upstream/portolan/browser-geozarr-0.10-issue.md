# Issue draft: portolan-browser, `spatial:dimensions` names other than y/x

For portolan-sdi/portolan-browser (bug form). **A starting point, not text
to paste.** portolan-browser's CONTRIBUTING.md (AI Use Policy) asks for
issues in the contributor's own voice, without verbose AI-generated text,
and for disclosure of AI assistance.

Record for the disclosure:

- LLM-written (Claude, 2026-11-28): the text below,
  [browser-check.mjs](browser-check.mjs) and
  [geozarr-dimensions-repro.mjs](geozarr-dimensions-repro.mjs).
- Found from Michael's report that the Bluelink stores show "declares no
  spatial reference" in browser.portolan-sdi.org; LEDGER.md, 2026-11-28.

Before filing:

- Re-run `browser-check.mjs` on the then-current portolan-browser main, and
  look for a 0.10 upgrade PR (Renovate's Dependency Dashboard, #116, lists
  the four packages).
- Choose the priority. P2 is suggested below. The rubric's P1 ("a common
  workflow fails with no reasonable workaround") is arguable: the only
  workaround is renaming a store's dimensions.
- Decide whether to offer the upgrade PR as well.
- The check covers metadata only. Whether Bluelink draws once the parser
  accepts it (chunks from THREDDS, which answers GET with
  `Access-Control-Allow-Origin: *`) is not yet seen.

---

**Title:** Zarr store with `spatial:dimensions` not named y/x reported as declaring no spatial reference

### What happened?

A Zarr array whose `spatial:dimensions` is `["yt_ocean", "xt_ocean"]`
shows "declares no spatial reference, so the browser cannot place it on the
map". The array declares `spatial:transform`, `spatial:shape` and
`proj:code: "EPSG:4326"`, and registers both conventions in
`zarr_conventions`. The console reason is `zarr-no-geo`: "The Zarr store
declares no spatial transform and no coordinate arrays to derive one from".

`@developmentseed/geozarr` 0.9.0 matches `spatial:dimensions` by label (`y`,
`lat`, `latitude`; `x`, `lon`, `longitude`) and throws on other names. The
coordinate-array fallback (`spatialDimNames` in `src/utils/zarrSource.js`)
matches the same names. The spatial convention orders the two entries by
role, Y then X, and allows any dimension names. geozarr 0.10.0 reads them by
position (developmentseed/deck.gl-raster#785, from #451).

### Why it matters

Ocean and climate model output often names its grid dimensions otherwise:
MOM `xt_ocean`/`yt_ocean`, ROMS `xi_rho`/`eta_rho`, rotated-pole
`rlon`/`rlat`. The notice also misreports the store: it does declare a
spatial reference.

### Priority

P2

### How to reproduce

Open this collection and switch on `eta_t` (BRAN2023 daily sea surface
height, Icechunk asset):
https://data.source.coop/ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-eta_t/stac/collection.json

Or, the parser alone:

```js
import { parseGeoZarrMetadata } from '@developmentseed/geozarr';
parseGeoZarrMetadata({
  zarr_conventions: [
    { uuid: '689b58e2-cf7b-45e0-9fff-9cfc0883d6b4', name: 'spatial:' },
    { uuid: 'f17cb550-5864-4468-aeb7-f3180cfb622f', name: 'proj:' },
  ],
  'spatial:dimensions': ['yt_ocean', 'xt_ocean'],
  'spatial:transform': [0.1, 0, 0, 0, 0.1, -75],
  'spatial:shape': [1500, 3600],
  'proj:code': 'EPSG:4326',
});
// 0.9.0: Error: spatial:dimensions must contain a Y axis ("y"/"latitude"/"lat") ...
// 0.10.0: axes ["yt_ocean", "xt_ocean"], yAxisIndex 0, xAxisIndex 1
```

### Implementation notes

Raising `@developmentseed/geozarr` alone is not enough. `ZarrLayer` in
deck.gl-zarr 0.9.0 parses the attributes again with its own geozarr
(`parseGeoZarrMetadata(metadataOverride ?? group.attrs)` in
`dist/zarr-layer.js`), so the browser's check would pass and the layer would
then throw inside deck.gl. This needs the 0.10 upgrade of deck.gl-zarr,
deck.gl-geotiff, geotiff and geozarr together. 0.10 changes the Zarr API
(`ZarrSource`, #812; opening from a store with a path and inheriting a
group's GeoZarr metadata, #838, which overlaps the root-inheritance code in
`makeZarrLayerProps`) and the COG API (#799, #801, #804).

### How to confirm the fix

- The `eta_t` layer above passes `makeZarrLayerProps` and draws.
- A unit test in `tests/unit/zarrLayers.spec.js` with
  `spatial:dimensions: ["yt_ocean", "xt_ocean"]` gets no `zarr-no-geo`.

With geozarr 0.10.0 in place of 0.9.0, `makeZarrLayerProps` from `026734e`
passes for all nine BRAN2023 daily collections in that product (run in Node;
script on request).

### Version

`026734e` (deployed 2026-11-26)

<!-- Disclosure (adjust): I used an LLM tool (Claude) to trace the cause and
draft this; I checked the results and rewrote it. -->

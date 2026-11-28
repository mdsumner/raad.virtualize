# Issue draft: portolan-browser, `spatial:dimensions` names other than y/x

For portolan-sdi/portolan-browser (bug form). **A starting point, not text
to paste.** The portolan-ops AI policy asks for a human in the loop who has
read and understood the draft, and the prose norms ask for Simplified
Technical English. `.claude/hooks/writing_check.py` (in the portolan-browser
checkout) passes the body below, checked 2026-11-28.

Record for the disclosure:

- LLM-written (Claude, 2026-11-28): the text below,
  [browser-check.mjs](browser-check.mjs) and
  [geozarr-dimensions-repro.mjs](geozarr-dimensions-repro.mjs).
- Found from Michael's report that the Bluelink stores show "declares no
  spatial reference" in browser.portolan-sdi.org; LEDGER.md, 2026-11-28.

Before filing:

- File [renovate-hold-0.10-issue.md](renovate-hold-0.10-issue.md) first. It
  is time-critical, and this issue refers to it (`#HOLD` below).
- Re-run `browser-check.mjs` on the then-current portolan-browser main.
- Choose the priority. P2 is suggested below. The rubric's P1 ("a common
  workflow fails with no reasonable workaround") is arguable: the only
  workaround is renaming a store's dimensions.
- The check covers metadata only. Whether Bluelink draws once the parser
  accepts it (chunks from THREDDS, which answers GET with
  `Access-Control-Allow-Origin: *`) is not yet seen.

---

**Title:** Map reports "no spatial reference" for a Zarr array whose `spatial:dimensions` are not y and x

### What happened?

The map shows "declares no spatial reference" for a valid GeoZarr array. The
array has `spatial:dimensions: ["yt_ocean", "xt_ocean"]`. It also has
`spatial:transform`, `spatial:shape` and `proj:code: "EPSG:4326"`. Its
`zarr_conventions` lists the `spatial:` and `proj:` conventions.

The console gives this reason:

```
[zarr-no-geo] The Zarr store declares no spatial transform and no coordinate arrays to derive one from
```

`@developmentseed/geozarr` 0.9.0 finds the axes by name. It accepts only
these names:

- Y: `y`, `lat`, `latitude`
- X: `x`, `lon`, `longitude`

The fallback from the coordinate arrays (`spatialDimNames` in
`src/utils/zarrSource.js`) uses the same names. The spatial convention gives
the axis role by position. The first entry names the Y axis. The second entry
names the X axis. Any name is valid.

The geozarr release 0.10.0 reads the axes by position (deck.gl-raster #785).

### Why it matters

Model output often uses other names for the grid dimensions:

- MOM: `xt_ocean`, `yt_ocean`
- ROMS: `xi_rho`, `eta_rho`
- Rotated-pole grids: `rlon`, `rlat`

Also, the notice is wrong. The array declares a spatial reference.

### Priority

P2

### How to reproduce

1. Open this collection in the browser:
   https://data.source.coop/ausantarctic/ausantarctic-scratch/bluelink/bluelink-daily-eta_t/stac/collection.json
2. Switch on the `eta_t` layer (BRAN2023 daily sea surface height).

The parser alone shows the cause:

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
```

```
0.9.0: Error: spatial:dimensions must contain a Y axis ("y"/"latitude"/"lat") and an X axis ("x"/"longitude"/"lon") (case-insensitive), got: ["yt_ocean","xt_ocean"]
0.10.0: axes ["yt_ocean", "xt_ocean"], yAxisIndex 0, xAxisIndex 1
```

### Implementation notes

- An update of `@developmentseed/geozarr` alone does not fix the map.
  `ZarrLayer` in deck.gl-zarr 0.9.0 parses the attributes again with its own
  geozarr. Thus the check passes, and then the layer fails inside deck.gl.
- The fix is the 0.10 update of the four deck.gl-raster packages. That update
  needs the new layer props (#HOLD).
- With geozarr 0.10.0, `makeZarrLayerProps` from `026734e` passes for all
  nine BRAN2023 daily collections in that product. The test ran in Node.

### How to confirm the fix

- The `eta_t` layer of the collection above draws on the map.
- A unit test in `tests/unit/zarrLayers.spec.js` uses
  `spatial:dimensions: ["yt_ocean", "xt_ocean"]`. The test gets no
  `zarr-no-geo`.

### Version

`026734e`

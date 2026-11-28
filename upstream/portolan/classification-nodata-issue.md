# Issue draft: portolan-browser, flag values marked no-data by classification classes

For portolan-sdi/portolan-browser (feature form). **A starting point, not
text to paste.** The portolan-ops AI policy asks for a human in the loop who
has read and understood the draft, and the prose norms ask for Simplified
Technical English. Run `.claude/hooks/writing_check.py` (in the
portolan-browser checkout) on the body before filing.

Record for the disclosure:

- LLM-written (Claude, 2026-11-28): the text below. The code references are
  to portolan-browser `026734e` (upstream main on 2026-11-28).
- Found while publishing the G02202 sea ice stores (raad.virtualize STATUS,
  step 6; LEDGER, 2026-11-28). The G02202 config had a five-value render
  `nodata`, which render v2.0.0 does not allow. It now declares the fill
  (255) only, so portolan-browser draws the flag values 251 to 254.

Before filing:

- The example needs a published collection that declares the classes. The
  raad.virtualize G02202 collections declare only `nodata` 255 today; adding
  `classification:classes` to their asset `bands` is the raad.virtualize
  side of this work.
- Choose the priority. P3 is suggested below: land and coast draw in a
  colour, but the data values are correct.
- Choose between the two routes in "Implementation notes", or leave that to
  the maintainers.

---

**Title:** Draw transparent the values that a classification class marks as no-data

### Use case

Many gridded products keep flag values in the band of a measurement. An
example is the sea ice concentration of NOAA/NSIDC G02202. Values 0 to 100
are concentration. 251 is the pole hole, 253 is coast, 254 is land and 255 is
missing. A map of concentration must not draw 251 to 254 as colours of the
concentration ramp.

### Current limitations

STAC gives one `nodata` value for a band, and render v2.0.0 gives one
`nodata` value for a render. A list fails the render schema. The
classification extension states the other flag values: a class with
`nodata: true` is a no-data value.

portolan-browser reads `classification:classes` only in `_resolveCogRender`
(`src/components/maps/StacMapLayer.js`), through `renderFromClassification`
(`src/utils/renders.js`). That function makes a discrete colormap, and it
returns null when no class has a colour. Thus:

- For a COG measurement band whose classes are only flags, the classes have
  no effect.
- The Zarr layer path (`src/utils/zarrLayers.js`) does not read
  `classification:classes`.

The flag values then draw at the top of the colour ramp.

### Priority

P3

### Example

<!-- a collection with `classification:classes` on the asset's `bands` -->

### Proposed behavior

This applies to a ramp render, which has a `colormap_name` and a `rescale`.
If a class of the band has `nodata: true`, the browser draws its value
transparent. It does this in addition to the `nodata` value of the band or
the render. The COG and Zarr layers do the same.

### Implementation notes

- `isTransparentClass` in `src/utils/renders.js` already identifies these
  classes. Its values can join the no-data set that `bandPixelWriter` and
  `colormapBand` use.
- For Zarr, `zarrVariables` already reads `bands` by variable name. The
  classes can come from the same band entry.
- Another route is the CF `valid_range` attribute of the Zarr array. G02202
  declares `valid_range` 0 to 100. That route reads CF attributes, which the
  browser does not read now. The classification route uses STAC only.

### How to confirm it works

Open a collection whose band declares `nodata` 255 and classes 251 to 254
with `nodata: true`. Draw it with a ramp render. Samples with the values 251
to 255 are transparent, and the samples 0 to 100 keep their colours.

// Run portolan-browser's own Zarr layer checks against a published STAC
// collection, outside a browser. makeZarrLayerProps is where the browser
// raises its Zarr notices ("declares no spatial reference" is
// `zarr-no-geo`), so a store that fails here shows that notice on the map.
//
// Setup, in an empty directory (Node 20):
//   git clone --depth 1 https://github.com/portolan-sdi/portolan-browser pb
//   mkdir check && cp -r pb/src/utils check/utils && cp browser-check.mjs check/
//   cd check && printf '{"type":"module"}\n' > package.json
//   npm install zarrita@^0.7.5 icechunk-js@^0.6.1 @developmentseed/geozarr@^0.9.0
// (the versions portolan-browser pins; install @developmentseed/geozarr@0.10.0
// to test the upgrade). Then:
//   node browser-check.mjs <collection.json URL>
//
// Checks only metadata: no chunk is drawn, and browser-only failures (CORS,
// WebGL, reprojection at draw time) are not seen.
import * as zarr from 'zarrita';
import { zarrDescriptors, makeZarrLayerProps } from './utils/zarrLayers.js';
import { isZarrAsset } from './utils/zarrSource.js';

const url = process.argv[2];
const c = await (await fetch(url)).json();
console.log(`== ${c.id}`);
for (const [key, a] of Object.entries(c.assets)) {
  const asset = {
    ...a,
    getKey: () => key,
    getAbsoluteUrl: () => new URL(a.href, url).href,
    getMetadata: k => a[k],
  };
  if (!isZarrAsset(asset)) continue;
  for (const d of zarrDescriptors(asset, c, null)) {
    const name = d.variable?.name ?? '(store)';
    try {
      await makeZarrLayerProps(d, { zarr, bbox: c.extent?.spatial?.bbox?.[0] });
      console.log(`  OK   ${key} ${name}`);
    } catch (e) {
      console.log(`  FAIL ${key} ${name}: [${e.reason ?? e.name}] ${e.message}`);
    }
  }
}

// deck.gl-raster 0.10 layers given the props portolan-browser passes today
// (the 0.9 names). Run from the root of a portolan-browser checkout with the
// 0.10 packages installed: node layer-old-props.mjs
import { COGLayer } from '@developmentseed/deck.gl-geotiff';
import { ZarrLayer } from '@developmentseed/deck.gl-zarr';
for (const [Layer, props] of [
  [COGLayer, { id: 'cog', geotiff: 'https://example.org/x.tif' }],
  [ZarrLayer, { id: 'zarr', node: {}, selection: {}, getTileData: () => null, renderTile: () => null }],
]) {
  const layer = new Layer(props);
  layer.state = {};
  layer.setState = s => Object.assign(layer.state, s);
  let raised = null;
  layer.raiseError = e => { raised = e; };
  const result = await layer.loadMetadata(new AbortController().signal).then(() => 'resolved', e => `rejected: ${e.message}`);
  console.log(`${Layer.layerName}: props.source=${layer.props.source}; loadMetadata ${result}; state.source=${layer.state.source}; raised=${raised}`);
}

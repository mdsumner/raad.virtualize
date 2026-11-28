import { parseGeoZarrMetadata } from '@developmentseed/geozarr';
const attrs = {
  zarr_conventions: [
    { uuid: '689b58e2-cf7b-45e0-9fff-9cfc0883d6b4', name: 'spatial:' },
    { uuid: 'f17cb550-5864-4468-aeb7-f3180cfb622f', name: 'proj:' },
  ],
  'spatial:dimensions': ['yt_ocean', 'xt_ocean'],
  'spatial:transform': [0.1, 0, 0, 0, 0.1, -75],
  'spatial:shape': [1500, 3600],
  'proj:code': 'EPSG:4326',
};
try {
  const m = parseGeoZarrMetadata(attrs);
  console.log('parsed: axes', m.axes, 'y', m.yAxisIndex, 'x', m.xAxisIndex);
} catch (e) { console.log('error:', e.message); }

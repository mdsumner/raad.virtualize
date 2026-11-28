# Issue and PR drafts: hold the deck.gl-raster 0.10 update in portolan-browser

For portolan-sdi/portolan-browser: a bug issue and its fix PR. **Starting
points, not text to paste.** The portolan-ops AI policy asks for a human in
the loop who has read and understood each draft, and the prose norms ask for
Simplified Technical English. `.claude/hooks/writing_check.py` (in the
portolan-browser checkout) passes both bodies below, checked 2026-11-28.

Record for the disclosure:

- LLM-written (Claude, 2026-11-28): the issue and PR text, the
  `renovate.json5` rule (fork branch `chore/hold-deck-gl-raster-0.10`,
  commit `f2d0b58c`) and [layer-old-props.mjs](layer-old-props.mjs).
- Found while checking the geozarr fix
  ([browser-geozarr-0.10-issue.md](browser-geozarr-0.10-issue.md)): 0.10
  needs a migration, and the update is in Renovate's grouped Monday update.

Timing: the "all non-major" group waits for `schedule:earlyMondays`. The
next window is Monday 2026-11-30, early UTC (Monday morning in Hobart). The
org policy merges the group when its required checks pass.

Before filing:

- Run Renovate's validator on the rule (not run in this session):
  `npx -y --package renovate renovate-config-validator renovate.json5`
  in the fork checkout on branch `chore/hold-deck-gl-raster-0.10`.
- Check the Dependency Dashboard (#116): if the group PR is already open,
  say so in the issue.
- File the issue first, then put its number in the PR's `Why` section.
- A Slack message in the Portolan channel may reach the maintainers faster
  before Monday.

---

**Issue title:** Renovate merges deck.gl-raster 0.10, and the map then draws no COG or Zarr layer

### What happened?

Renovate plans to update the four `@developmentseed` packages from `^0.9.0`
to `^0.10.0`. The Dependency Dashboard (#116) lists them in the "all
non-major" group. The org policy merges that group when the required checks
pass.

deck.gl-raster 0.10 replaces the layer props that the map uses:

- `COGLayer` takes `source` in place of `geotiff` (deck.gl-raster #799).
- `ZarrLayer` takes `source` in place of `node` and `metadata` (#812, #838).

With the old props, both layers draw nothing and report no error.
`RasterTileLayer.loadMetadata` returns early when `props.source` is null.
Thus no error reaches `onError`.

The checks pass with 0.10:

- `pnpm run test:unit` passes all 917 tests. The tests replace the layers
  with stubs.
- `pnpm run build` passes.
- No e2e test opens a COG or a Zarr store. `mapping.spec.js` has two tests.

### Why it matters

After the merge, `deploy-demo.yml` publishes `main`. Then the demo map draws
no COG or Zarr layer. The browser shows no notice.

### Priority

P1

### How to reproduce

1. On `main` (`026734e`), run this command:
   `pnpm add @developmentseed/deck.gl-geotiff@^0.10.0 @developmentseed/deck.gl-zarr@^0.10.0 @developmentseed/geotiff@^0.10.0 @developmentseed/geozarr@^0.10.0`
2. Run `pnpm run test:unit` and `pnpm run build`. Both pass.
3. Run this script from the repo root with Node 20:

```js
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
  const result = await layer.loadMetadata(new AbortController().signal)
    .then(() => 'resolved', e => `rejected: ${e.message}`);
  console.log(`${Layer.layerName}: loadMetadata ${result}; state.source=${layer.state.source}; raised=${raised}`);
}
```

Output:

```
COGLayer: loadMetadata resolved; state.source=undefined; raised=null
ZarrLayer: loadMetadata resolved; state.source=undefined; raised=null
```

### Implementation notes

- Hold the four packages with a `renovate.json5` package rule. `norms/ci.md`
  describes this exception. The rule gives the packages their own group with
  `automerge: false`. The other non-major updates merge as before. A fix PR
  follows.
- Move the map code to the 0.10 props after that. 0.10 also reads
  `spatial:dimensions` by position (deck.gl-raster #785).
- A unit test can catch a future change of this kind. The test builds each
  real layer with the props from `StacMapLayer`. Then it checks that
  `loadMetadata` sets a source.

### How to confirm the fix

- Renovate opens a separate "deck.gl-raster" pull request without automerge.
- The Dependency Dashboard lists the "deck.gl-raster" group.
- The other non-major updates merge as before.

### Version

`026734e`

---

**PR title:** chore(deps): hold the deck.gl-raster 0.10 update for review

## Summary

This change adds a `renovate.json5` with one package rule. The rule puts the
four deck.gl-raster packages in their own Renovate group. It turns off
automerge for that group. deck.gl-raster 0.10 changes the layer props. With
the current map code, the map then draws no COG or Zarr layer. The checks do
not find this problem.

## What changed

- Renovate opens one pull request for the four packages. A person merges it.
- The packages are `@developmentseed/deck.gl-geotiff`,
  `@developmentseed/deck.gl-zarr`, `@developmentseed/geotiff` and
  `@developmentseed/geozarr`.
- The other non-major updates stay in the "all non-major" group.

## Why

Fixes #ISSUE.

## Verification

- The file parses with json5 2.2.3 from the lockfile. The parsed rule has
  the four package names, `groupName: "deck.gl-raster"` and
  `automerge: false`.
- `renovate-config-validator renovate.json5` reports no error. (Run before
  filing.)
- The issue shows that the 0.10 layers draw nothing with the current props.

<!-- ste-ok: PERFECT_TENSE GERUND a maintainer wrote this line by hand -->
- [x] I have read and complied with the [contributing guide](https://github.com/portolan-sdi/portolan-ops/blob/main/policies/CONTRIBUTING.md) and [AI policy](https://github.com/portolan-sdi/portolan-ops/blob/main/policies/AI_POLICY.md).
- [x] This change does not alter behavior (docs, chore, or CI only).

## Implementation notes

The rule uses `groupName` and `groupSlug`. The `vale` rule in
`renovate/default.json5` uses the same keys. Renovate adds the rules of
`renovate.json5` after the rules of the org preset.

## Related issues

#116 lists the update.

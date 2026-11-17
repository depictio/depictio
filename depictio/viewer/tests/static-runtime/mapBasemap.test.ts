/**
 * The offline basemap must survive Plotly's second render.
 *
 * Plotly relinks the previous full layout onto the next one on every update
 * (`relinkPrivateKeys`) and deletes each plain object that ends up empty. A
 * map's `style` object is the caller's, held by reference, so a blank style
 * with `sources: {}` lost `sources` on the first filter change, MapLibre's
 * `setStyle` refused it ("missing required property sources") and Plotly
 * threw `Error: Map error.` as a page error.
 *
 * Run like the other viewer tests (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/static-runtime
 */
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

import { blankStyle, plotlySafeStyle, withReachableBasemap } from '../../src/static-runtime/mapBasemap';

const require = createRequire(import.meta.url);
// Plotly's `isPlainObject` reads `window`; the helper itself needs no DOM.
(globalThis as { window?: unknown }).window ??= globalThis;
// Plotly's own helper, not a copy of it: the test is that our style survives it.
const relinkPrivateKeys = require('plotly.js/src/lib/relink_private') as (
  to: Record<string, unknown>,
  from: Record<string, unknown>,
) => void;

/** What Plotly does to `layout.map.style` between two renders of one map. */
function afterAnUpdate(style: Record<string, unknown>): Record<string, unknown> {
  // Every render hands Plotly a freshly built style (renderMap resolves the
  // basemap again), so the old full layout holds an equal but distinct object
  // and the relink walks into it.
  const next = { map: { style } };
  const previous = { map: { style: structuredClone(style) } };
  relinkPrivateKeys(next, previous);
  return next.map.style;
}

/** MapLibre's required top-level properties of a style document. */
function missingRequired(style: Record<string, unknown>): string[] {
  return ['version', 'sources', 'layers'].filter((key) => !(key in style));
}

describe('blankStyle', () => {
  for (const theme of ['light', 'dark'] as const) {
    it(`keeps every required property through a Plotly update (${theme})`, () => {
      const style = afterAnUpdate(blankStyle(theme));
      expect(missingRequired(style)).toEqual([]);
      expect(Object.keys(style.sources as object)).not.toHaveLength(0);
    });
  }

  it('needs no network: the only source is inline GeoJSON', () => {
    const sources = blankStyle('light').sources as Record<string, { type: string; data: unknown }>;
    for (const source of Object.values(sources)) {
      expect(source.type).toBe('geojson');
      expect(typeof source.data).toBe('object');
    }
  });
});

describe('plotlySafeStyle', () => {
  it('drops the empty objects Plotly would drop, and keeps a source', () => {
    const style = plotlySafeStyle({
      version: 8,
      sources: {},
      metadata: {},
      layers: [{ id: 'bg', type: 'background', layout: {}, paint: { 'background-color': '#fff' } }],
    });
    expect(missingRequired(afterAnUpdate(style))).toEqual([]);
    expect(style.metadata).toBeUndefined();
    expect((style.layers as Array<Record<string, unknown>>)[0].layout).toBeUndefined();
  });
});

describe('withReachableBasemap offline', () => {
  it('swaps an unreachable Carto style for one that survives the next update', async () => {
    const realFetch = globalThis.fetch;
    globalThis.fetch = (() => Promise.reject(new TypeError('offline'))) as typeof fetch;
    try {
      const out = await withReachableBasemap(
        { figure: { data: [], layout: { map: { style: 'carto-positron' } } } },
        'light',
      );
      const style = (out.figure.layout as { map: { style: Record<string, unknown> } }).map.style;
      expect(style.name).toBe('depictio-offline-blank');
      expect(missingRequired(afterAnUpdate(style))).toEqual([]);
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});

describe('the regression itself', () => {
  it('an empty `sources` is what Plotly deletes', () => {
    const style = afterAnUpdate({ version: 8, sources: {}, layers: [] });
    expect(missingRequired(style)).toEqual(['sources']);
  });
});

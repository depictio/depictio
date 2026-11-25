import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from '../../selectionGroups';
import { MAX_PANELS } from '../../splitPanels';
import { computeMapFit } from './fit';
import type { MapFitSpec } from './fit';
import {
  allSignaturesEqual,
  figureSignature,
  mapGroupBadgeReasons,
  mapGroupPlan,
  sharedMapView,
} from './split';

const SPEC: MapFitSpec = {
  minLat: 48.5,
  maxLat: 48.6,
  minLon: 8.8,
  maxLon: 9.0,
  padding: 0.5,
  maxZoom: 12,
  singlePointZoom: 9,
};

function groups(n: number, display: 'color' | 'facet'): GroupRenderState {
  return {
    colorByGroup: true,
    display,
    groups: Array.from({ length: n }, (_, i) => ({
      name: `g${i}`,
      column_name: 'sample',
      values: [`s${i}`],
      color: '#000',
    })) as GroupRenderState['groups'],
  };
}

describe('mapGroupPlan', () => {
  it('draws a map with no grouping whole and unbadged', () => {
    expect(mapGroupPlan(undefined, [])).toEqual({ kind: 'whole', badge: null });
  });

  it('badges an overlay, which a map does not draw', () => {
    expect(mapGroupPlan(groups(3, 'color'), [])).toEqual({ kind: 'whole', badge: 'overlay' });
  });

  it('splits a facet display into one panel per group', () => {
    const plan = mapGroupPlan(groups(3, 'facet'), []);
    expect(plan.kind).toBe('split');
    if (plan.kind === 'split') {
      expect(plan.panels.map((p) => p.name)).toEqual(['g0', 'g1', 'g2', 'Other']);
    }
  });

  it('refuses a split past MAX_PANELS and says so', () => {
    expect(mapGroupPlan(groups(MAX_PANELS + 1, 'facet'), [])).toEqual({
      kind: 'whole',
      badge: 'too_many',
    });
  });

  it('splits a single group against Other, and not once Other is hidden', () => {
    const plan = mapGroupPlan(groups(1, 'facet'), []);
    expect(plan.kind === 'split' && plan.panels.map((p) => p.name)).toEqual(['g0', 'Other']);
    expect(mapGroupPlan({ ...groups(1, 'facet'), showOther: false }, [])).toEqual({
      kind: 'whole',
      badge: 'unsplittable',
    });
  });

  it('has a reason line for every badge', () => {
    for (const reason of ['overlay', 'too_many', 'unsplittable', 'ineffective'] as const) {
      expect(mapGroupBadgeReasons(reason).length).toBeGreaterThan(0);
    }
  });
});

describe('sharedMapView', () => {
  it('is null without a spec or a box', () => {
    expect(sharedMapView(null, [{ width: 300, height: 200 }])).toBeNull();
    expect(sharedMapView(SPEC, [])).toBeNull();
  });

  it('fits against the smallest panel so every point stays in every panel', () => {
    const view = sharedMapView(SPEC, [
      { width: 400, height: 300 },
      { width: 399, height: 280 },
    ]);
    expect(view).toEqual(computeMapFit(SPEC, 399, 280));
  });

  it('gives the same view however the panels are ordered', () => {
    const a = { width: 400, height: 300 };
    const b = { width: 380, height: 310 };
    expect(sharedMapView(SPEC, [a, b])).toEqual(sharedMapView(SPEC, [b, a]));
  });
});

describe('figureSignature', () => {
  const fig = (lat: number[], lon: number[]) => ({ data: [{ type: 'scattermap', lat, lon }] });

  it('tells two groups apart', () => {
    expect(figureSignature(fig([1, 2], [3, 4]))).not.toBe(figureSignature(fig([1, 2, 5], [3, 4, 6])));
    expect(figureSignature(fig([1, 2], [3, 4]))).not.toBe(figureSignature(fig([1, 9], [3, 4])));
  });

  it('matches two panels that drew the same points', () => {
    expect(figureSignature(fig([1, 2], [3, 4]))).toBe(figureSignature(fig([1, 2], [3, 4])));
  });

  it('reads typed-array columns', () => {
    const a = { data: [{ type: 'scattermap', lat: { dtype: 'f8', bdata: 'AAAAAAAA8D8=' } }] };
    const b = { data: [{ type: 'scattermap', lat: { dtype: 'f8', bdata: 'AAAAAAAAAEA=' } }] };
    expect(figureSignature(a)).not.toBe(figureSignature(b));
  });

  it('is null without a figure', () => {
    expect(figureSignature(null)).toBeNull();
  });
});

describe('allSignaturesEqual', () => {
  it('needs two or more settled panels', () => {
    expect(allSignaturesEqual(['a'])).toBe(false);
    expect(allSignaturesEqual(['a', null])).toBe(false);
  });
  it('is true only when every panel matches', () => {
    expect(allSignaturesEqual(['a', 'a', 'a'])).toBe(true);
    expect(allSignaturesEqual(['a', 'a', 'b'])).toBe(false);
  });
});

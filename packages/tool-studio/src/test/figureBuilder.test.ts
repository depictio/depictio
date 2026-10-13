import { describe, it, expect } from 'vitest';
import { buildPreview, isUnavailable } from '../viz/figureBuilder';
import { parseFixture } from '../catalog/parseFixture';
import type { RenderSpec } from '../types';

const fixture = parseFixture(
  'f.csv',
  ['gene,lfc,p,sample', 'A,2,0.01,S1', 'B,-1,0.5,S1', 'C,3,0.001,S2'].join('\n'),
);

describe('buildPreview — figure', () => {
  it('builds a histogram trace from x', () => {
    const r: RenderSpec = { uid: 'r', component: 'figure', visu_type: 'histogram', dict_kwargs: { x: 'lfc' } };
    const res = buildPreview(fixture, r);
    expect(isUnavailable(res)).toBe(false);
    if (!isUnavailable(res)) expect(res.data[0].type).toBe('histogram');
  });
  it('reports unavailable when x is missing', () => {
    const r: RenderSpec = { uid: 'r', component: 'figure', visu_type: 'bar', dict_kwargs: {} };
    const res = buildPreview(fixture, r);
    expect(isUnavailable(res)).toBe(true);
  });
  it('groups a scatter by categorical color', () => {
    const r: RenderSpec = { uid: 'r', component: 'figure', visu_type: 'scatter', dict_kwargs: { x: 'lfc', y: 'p', color: 'sample' } };
    const res = buildPreview(fixture, r);
    if (!isUnavailable(res)) expect(res.data.length).toBe(2); // S1, S2
  });
});

describe('buildPreview — everything else', () => {
  it('leaves non-figure renders to depictio\'s own renderers', () => {
    // Cards, tables, interactive controls and advanced viz are drawn by
    // depictio-react-core off the offline api shim, not by this module.
    for (const r of [
      { uid: 'r', component: 'card', column: 'lfc', aggregation: 'average' },
      { uid: 'r', component: 'table' },
      {
        uid: 'r',
        component: 'advanced_viz',
        kind: 'volcano',
        roles: { feature_id: 'gene', effect_size: 'lfc', significance: 'p' },
      },
    ] as RenderSpec[]) {
      expect(isUnavailable(buildPreview(fixture, r))).toBe(true);
    }
  });
});

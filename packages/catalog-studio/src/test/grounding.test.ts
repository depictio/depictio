import { describe, it, expect } from 'vitest';
import { boundColumns, validateRender } from '../catalog/grounding';
import type { FixtureColumn, KindsMap, RenderSpec } from '../types';

const columns: FixtureColumn[] = [
  { name: 'gene', dtype: 'String' },
  { name: 'lfc', dtype: 'Float64' },
  { name: 'p', dtype: 'Float64' },
  { name: 'cov', dtype: 'Int64' },
];

const kinds: KindsMap = {
  volcano: {
    roles: { feature_id: ['String', 'Utf8'], effect_size: ['Float64'], significance: ['Float64'], label: ['String', 'Utf8'] },
    required_roles: ['feature_id', 'effect_size', 'significance'],
    heavy: false,
    label: 'Volcano',
  },
};

describe('boundColumns', () => {
  it('collects figure kwarg columns', () => {
    const r: RenderSpec = { uid: 'r', component: 'figure', visu_type: 'bar', dict_kwargs: { x: 'gene', color: 'cov', title: 'ignored' } };
    expect(boundColumns(r).sort()).toEqual(['cov', 'gene']);
  });
  it('collects advanced_viz role columns', () => {
    const r: RenderSpec = { uid: 'r', component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'gene', effect_size: 'lfc' } };
    expect(boundColumns(r).sort()).toEqual(['gene', 'lfc']);
  });
});

describe('validateRender', () => {
  it('flags a column not in the fixture', () => {
    const r: RenderSpec = { uid: 'r', component: 'figure', visu_type: 'bar', dict_kwargs: { x: 'missing' } };
    const issues = validateRender(r, columns, kinds);
    expect(issues.some((i) => i.severity === 'error' && /not in the fixture/.test(i.message))).toBe(true);
  });
  it('passes a fully-bound valid volcano', () => {
    const r: RenderSpec = { uid: 'r', component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'gene', effect_size: 'lfc', significance: 'p' } };
    expect(validateRender(r, columns, kinds)).toHaveLength(0);
  });
  it('flags a missing required role', () => {
    const r: RenderSpec = { uid: 'r', component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'gene' } };
    const issues = validateRender(r, columns, kinds);
    expect(issues.some((i) => /requires role/.test(i.message))).toBe(true);
  });
  it('flags an unknown role', () => {
    const r: RenderSpec = { uid: 'r', component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'gene', effect_size: 'lfc', significance: 'p', bogus: 'cov' } };
    const issues = validateRender(r, columns, kinds);
    expect(issues.some((i) => /not valid for volcano/.test(i.message))).toBe(true);
  });
  it('warns on a dtype mismatch', () => {
    const r: RenderSpec = { uid: 'r', component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'gene', effect_size: 'gene', significance: 'p' } };
    const issues = validateRender(r, columns, kinds);
    expect(issues.some((i) => i.severity === 'warning' && /expects/.test(i.message))).toBe(true);
  });
});

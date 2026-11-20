import { describe, it, expect } from 'vitest';
import { buildPreview, isUnavailable } from '../viz/figureBuilder';
import { applyPlotlyTheme } from '../viz/plotlyTheme';
import { parseFixture } from '../catalog/parseFixture';
import { renderSpecFromManifest } from '../catalog/fromManifestRender';
import { renderItemLines } from '../catalog/yamlGen';
import { boundColumns } from '../catalog/grounding';
import type { RenderSpec } from '../types';

const fixture = parseFixture(
  'f.csv',
  ['sample,depth', 'S1,10', 'S2,20', 'S3,30', 'S4,40'].join('\n'),
);

const render: RenderSpec = {
  uid: 'r',
  component: 'figure',
  visu_type: 'bar',
  dict_kwargs: { x: 'sample', y: 'depth' },
  reference_lines: [{ axis: 'y', stat: 'median', column: 'depth' }],
};

describe('figure reference_lines', () => {
  it('draws a median of the fixture and names it', () => {
    const res = buildPreview(fixture, render);
    expect(isUnavailable(res)).toBe(false);
    if (isUnavailable(res)) return;
    const shapes = res.layout.shapes as Record<string, unknown>[];
    expect(shapes[0]).toMatchObject({ type: 'line', y0: 25, y1: 25 });
    const annotations = res.layout.annotations as Record<string, unknown>[];
    expect(annotations[0].text).toBe('median of this table');
    // The scheme colours it; the builder hardcodes none.
    const themed = applyPlotlyTheme(res.layout, 'dark');
    expect(((themed.shapes as any[])[0].line as any).color).toBeTruthy();
  });

  it('round-trips through the manifest and the YAML', () => {
    const parsed = renderSpecFromManifest(
      {
        component: 'figure',
        visu_type: 'bar',
        dict_kwargs: { x: 'sample', y: 'depth' },
        reference_lines: [
          { axis: 'y', stat: 'median', column: 'depth' },
          { axis: 'y', value: 1, stat: 'mean', column: 'depth' }, // both: dropped
        ],
      },
      'u',
    );
    expect(parsed && parsed.component === 'figure' && parsed.reference_lines).toEqual([
      { axis: 'y', stat: 'median', column: 'depth' },
    ]);
    const lines = renderItemLines(render);
    expect(lines).toContain('reference_lines:');
    expect(lines).toContain('  - { axis: y, stat: median, column: depth }');
    expect(boundColumns(render)).toContain('depth');
  });
});

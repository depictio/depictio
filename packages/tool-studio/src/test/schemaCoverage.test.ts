import { describe, it, expect } from 'vitest';
import { parseFixture } from '../catalog/parseFixture';
import { buildPreview, isUnavailable } from '../viz/figureBuilder';
import { canonicalEdamTopic, genModuleYaml, genOutputYaml } from '../catalog/yamlGen';
import { renderSpecFromManifest } from '../catalog/fromManifestRender';
import { VISU_TYPES, INTERACTIVE_TYPES } from '../catalog/generated/renderSpec';
import type { FigureVisuType, RenderSpec, ToolMeta } from '../types';

const fixture = parseFixture(
  'f.csv',
  ['gene,lfc,p,sample', 'A,2,0.01,S1', 'B,-1,0.5,S1', 'C,3,0.001,S2'].join('\n'),
);

describe('parse warnings', () => {
  it('reports ragged rows instead of accepting them silently', () => {
    const f = parseFixture('bad.csv', 'a,b,c\n1,2\n3,4,5\n6,7,8,9\n');
    expect(f.parseWarnings?.join(' ')).toMatch(/fewer fields/);
    expect(f.parseWarnings?.join(' ')).toMatch(/more fields/);
  });
  it('flags a header with no data rows', () => {
    expect(parseFixture('h.csv', 'a,b\n').parseWarnings?.[0]).toMatch(/no data rows/);
  });
  it('stays quiet on a clean file', () => {
    expect(fixture.parseWarnings).toBeUndefined();
  });
});

describe('figure types', () => {
  // seedStore pulls in plotly (no URL.createObjectURL in jsdom), so check the
  // generated list it is now built from instead.
  it('generates every catalog visu_type', () => {
    expect(VISU_TYPES.length).toBe(13);
  });
  const xy: Record<string, string> = { x: 'sample', y: 'lfc' };
  for (const visu_type of ['violin', 'strip', 'area', 'ecdf', 'funnel', 'density_heatmap', 'density_contour'] as FigureVisuType[]) {
    it(`previews ${visu_type}`, () => {
      const r: RenderSpec = { uid: 'x', component: 'figure', visu_type, dict_kwargs: visu_type === 'ecdf' ? { x: 'lfc' } : xy };
      const out = buildPreview(fixture, r);
      expect(isUnavailable(out)).toBe(false);
      if (!isUnavailable(out)) expect(out.data.length).toBeGreaterThan(0);
    });
  }
  it('re-imports a violin render and a TextInput control as editable specs', () => {
    expect(renderSpecFromManifest({ component: 'figure', visu_type: 'violin', dict_kwargs: { y: 'lfc' } }, 'u1')).not.toBeNull();
    expect(INTERACTIVE_TYPES).toContain('TextInput');
    expect(
      renderSpecFromManifest({ component: 'interactive', interactive_type: 'TextInput', column_name: 'gene' }, 'u2'),
    ).not.toBeNull();
  });
  it('round-trips headline/priority on a card', () => {
    const spec = renderSpecFromManifest(
      { component: 'card', column: 'lfc', aggregation: 'average', headline: true, priority: 2 },
      'u3',
    );
    expect(spec).toMatchObject({ headline: true, priority: 2 });
  });
});

describe('identity + find fields', () => {
  const tool: ToolMeta = { id: 't', name: 'T', source: 'nf-core', description: 'd', homepage: 'https://x' };
  it('writes stage, canonical EDAM topics and a non-default version', () => {
    const y = genModuleYaml({ ...tool, stage: 'qc', edam_topics: ['topic_0102', 'edam:topic_3168'], version: '1.2.0' });
    expect(y).toContain('stage: qc');
    expect(y).toContain('edam_topics: [http://edamontology.org/topic_0102, http://edamontology.org/topic_3168]');
    expect(y).toContain('version: "1.2.0"');
    expect(genModuleYaml({ ...tool, version: '1.0.0' })).not.toContain('version:');
  });
  it('canonicalises EDAM forms and leaves others for validation to name', () => {
    expect(canonicalEdamTopic('http://edamontology.org/topic_0102')).toBe('http://edamontology.org/topic_0102');
    expect(canonicalEdamTopic('genomics')).toBe('genomics');
  });
  it('writes output name, filename and alternative globs', () => {
    const y = genOutputYaml(tool, { slug: 's', path_glob: '**/a.csv', path_glob_alt: ['**/b.csv'], name: 'S out' }, 'f.csv', []);
    expect(y).toContain('name: "S out"');
    expect(y).toMatch(/find: \{path_glob: "\*\*\/a.csv", path_glob_alt: \["\*\*\/b.csv"\]\}/);
    const byName = genOutputYaml(tool, { slug: 's', path_glob: '', filename: 'stats.txt' }, 'f.csv', []);
    expect(byName).toContain('find: {filename: stats.txt}');
  });
});

import { describe, it, expect } from 'vitest';
import { genModuleYaml, genOutputYaml, renderToFlow, outputId } from '../catalog/yamlGen';
import type { RenderSpec, ToolMeta, OutputMeta } from '../types';

const tool: ToolMeta = { id: 'mytool', name: 'My Tool', source: 'nf-core', nf_core_url: 'https://github.com/nf-core/modules/tree/master/modules/nf-core/mytool' };
const output: OutputMeta = { slug: 'results', path_glob: '**/mytool/*.tsv', description: 'desc' };

describe('outputId', () => {
  it('joins tool + slug', () => {
    expect(outputId('mosdepth', 'coverage')).toBe('mosdepth_coverage');
  });
});

describe('renderToFlow', () => {
  it('serializes a figure with dict_kwargs', () => {
    const r: RenderSpec = { uid: 'r1', component: 'figure', visu_type: 'bar', dict_kwargs: { x: 'a', color: 'b' } };
    expect(renderToFlow(r)).toBe('{ component: figure, visu_type: bar, dict_kwargs: {x: a, color: b} }');
  });
  it('serializes a card', () => {
    const r: RenderSpec = { uid: 'r2', component: 'card', column: 'cov', aggregation: 'average' };
    expect(renderToFlow(r)).toBe('{ component: card, column: cov, aggregation: average }');
  });
  it('serializes a table', () => {
    expect(renderToFlow({ uid: 'r3', component: 'table' })).toBe('{ component: table }');
  });
  it('serializes advanced_viz roles', () => {
    const r: RenderSpec = { uid: 'r4', component: 'advanced_viz', kind: 'volcano', roles: { feature_id: 'g', effect_size: 'lfc', significance: 'p' } };
    expect(renderToFlow(r)).toBe('{ component: advanced_viz, kind: volcano, roles: {feature_id: g, effect_size: lfc, significance: p} }');
  });
  it('quotes unsafe scalars', () => {
    const r: RenderSpec = { uid: 'r5', component: 'card', column: 'has space', aggregation: 'count' };
    expect(renderToFlow(r)).toContain('"has space"');
  });
});

describe('genModuleYaml', () => {
  it('emits the schema header + identity, omitting empty fields', () => {
    const yaml = genModuleYaml(tool);
    expect(yaml).toContain('# yaml-language-server: $schema=../catalog.schema.json');
    expect(yaml).toContain('id: mytool');
    expect(yaml).toContain('name: "My Tool"');
    expect(yaml).toContain('nf_core_url: https://github.com/nf-core/modules/tree/master/modules/nf-core/mytool');
    expect(yaml).not.toContain('biotools_url');
  });
  it('canonicalises a pasted meta.yml/blob URL to the module dir (so validate matches the index)', () => {
    const yaml = genModuleYaml({
      ...tool,
      nf_core_url:
        'https://github.com/nf-core/modules/blob/master/modules/nf-core/ivar/consensus/meta.yml',
    });
    expect(yaml).toContain(
      'nf_core_url: https://github.com/nf-core/modules/tree/master/modules/nf-core/ivar/consensus',
    );
    expect(yaml).not.toContain('meta.yml');
    expect(yaml).not.toContain('/blob/');
  });
});

describe('genOutputYaml', () => {
  it('emits id, find, fixture, renders and OMITS columns', () => {
    const renders: RenderSpec[] = [
      { uid: 'r1', component: 'table' },
      { uid: 'r2', component: 'card', column: 'cov', aggregation: 'average' },
    ];
    const yaml = genOutputYaml(tool, output, 'results.csv', renders);
    expect(yaml).toContain('id: mytool_results');
    expect(yaml).toContain('find: {path_glob: "**/mytool/*.tsv"}');
    expect(yaml).toContain('fixture: results.csv');
    expect(yaml).toContain('renders_as:');
    expect(yaml).toContain('  - { component: table }');
    expect(yaml).not.toContain('columns:');
  });
});

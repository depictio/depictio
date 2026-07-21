import { describe, it, expect } from 'vitest';
import {
  genModuleYaml,
  genOutputYaml,
  renderToFlow,
  outputId,
  appendRendersToYaml,
  appendRenders,
} from '../catalog/yamlGen';
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
  it('emits source_url for a non-nf-core source', () => {
    const yaml = genModuleYaml({
      id: 'samtools_sort',
      name: 'samtools sort',
      source: 'snakemake',
      source_url: 'https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort',
      homepage: 'http://www.htslib.org/',
    });
    expect(yaml).toContain(
      'source_url: https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort',
    );
    expect(yaml).toContain('homepage: http://www.htslib.org/');
    expect(yaml).not.toContain('nf_core_url');
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

describe('appendRendersToYaml', () => {
  const newCard: RenderSpec = {
    uid: 'x',
    component: 'card',
    column: 'cov',
    aggregation: 'average',
    id: 'newcard',
  };

  it('appends into a populated block, keeping existing items and trailing keys', () => {
    const raw = [
      'id: mytool_results',
      'find: {path_glob: "**/x"}',
      'renders_as:',
      '  - { component: table, id: tbl }',
      'fixture: results.csv',
      '',
    ].join('\n');
    const out = appendRendersToYaml(raw, [newCard]);
    const lines = out.split('\n');
    const iTbl = lines.findIndex((l) => l.includes('id: tbl'));
    const iNew = lines.findIndex((l) => l.includes('id: newcard'));
    const iFixture = lines.findIndex((l) => l === 'fixture: results.csv');
    // new item is indented under renders_as, after the existing one, before fixture:
    expect(iTbl).toBeGreaterThan(-1);
    expect(iNew).toBeGreaterThan(iTbl);
    expect(iFixture).toBeGreaterThan(iNew);
    expect(lines[iNew]).toMatch(/^ {2}- \{/);
  });

  it('replaces an inline empty list', () => {
    const out = appendRendersToYaml('id: t\nrenders_as: []\n', [newCard]);
    expect(out).not.toContain('[]');
    expect(out).toMatch(/renders_as:\n {2}- \{[^\n]*id: newcard/);
  });

  it('adds a renders_as block when the key is missing', () => {
    const out = appendRendersToYaml('id: t\nfind: {path_glob: "x"}\n', [newCard]);
    expect(out).toMatch(/renders_as:\n {2}- \{[^\n]*id: newcard/);
  });

  it('is a no-op with no new renders', () => {
    const raw = 'id: t\nrenders_as:\n  - { component: table }\n';
    expect(appendRendersToYaml(raw, [])).toBe(raw);
  });
});

describe('appendRenders addedLines', () => {
  const newCard: RenderSpec = { uid: 'x', component: 'card', column: 'cov', aggregation: 'average', id: 'newcard' };

  it('reports the inserted line index in a populated block (before trailing keys)', () => {
    const raw = [
      'id: mytool_results',
      'find: {path_glob: "**/x"}',
      'renders_as:',
      '  - { component: table, id: tbl }',
      'fixture: results.csv',
      '',
    ].join('\n');
    const { yaml, addedLines } = appendRenders(raw, [newCard]);
    const out = yaml.split('\n');
    expect(addedLines).toHaveLength(1);
    // The reported index points exactly at the new render line.
    expect(out[addedLines[0]]).toContain('id: newcard');
    // …and only the new line is flagged (the existing table isn't).
    expect(out[addedLines[0]]).not.toContain('component: table');
  });

  it('reports the inserted line when replacing an empty list', () => {
    const { yaml, addedLines } = appendRenders('id: t\nrenders_as: []\n', [newCard]);
    const out = yaml.split('\n');
    expect(addedLines).toHaveLength(1);
    expect(out[addedLines[0]]).toContain('id: newcard');
  });

  it('reports the inserted line when the renders_as key is missing', () => {
    const { yaml, addedLines } = appendRenders('id: t\nfind: {path_glob: "x"}\n', [newCard]);
    const out = yaml.split('\n');
    expect(addedLines).toHaveLength(1);
    expect(out[addedLines[0]]).toContain('id: newcard');
  });

  it('flags every line of a multi-line render (code-mode figure)', () => {
    const codeFig: RenderSpec = { uid: 'y', component: 'figure', code: 'fig = px.bar(df)\nfig.update_layout()' };
    const { yaml, addedLines } = appendRenders('id: t\nrenders_as:\n  - { component: table }\n', [codeFig]);
    const out = yaml.split('\n');
    expect(addedLines.length).toBeGreaterThan(1);
    for (const i of addedLines) expect(out[i]).toMatch(/\S/); // every flagged line has content
    expect(addedLines.map((i) => out[i]).join('\n')).toContain('code: |-');
  });
});

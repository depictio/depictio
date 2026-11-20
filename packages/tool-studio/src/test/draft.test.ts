// @vitest-environment node
import { describe, it, expect } from 'vitest';
import {
  DRAFT_FORMAT,
  decodeDraftFromUrl,
  draftFromCatalogFiles,
  encodeDraftForUrl,
  filesFromZip,
  LINK_FIXTURE_ROWS,
  normalizeDraft,
  toDraft,
} from '../catalog/draft';
import yaml from 'js-yaml';
import { generateEntry } from '../catalog/yamlGen';
import { parseFixture } from '../catalog/parseFixture';
import JSZip from 'jszip';
import type { OutputMeta, RenderSpec, ToolMeta } from '../types';

const tool: ToolMeta = {
  id: 'mytool',
  name: 'My Tool',
  source: 'nf-core',
  description: 'd',
  homepage: 'https://x.org',
  stage: 'qc',
  edam_topics: ['http://edamontology.org/topic_0102'],
  version: '1.2.0',
};
const output: OutputMeta = { slug: 'results', path_glob: '**/a/*.csv', path_glob_alt: ['**/b/*.csv'], name: 'Results', description: 'o' };
const fixture = parseFixture('results.csv', 'gene,log2fc,pvalue,sample\nA,2.1,0.01,S1\nB,-1,0.2,S2\n');
const renders: RenderSpec[] = [
  { uid: 'a', component: 'figure', id: 'viol', visu_type: 'violin', dict_kwargs: { x: 'sample', y: 'log2fc' } },
  { uid: 'b', component: 'card', id: 'avg', column: 'log2fc', aggregation: 'average', headline: true, priority: 1 },
  { uid: 'c', component: 'interactive', id: 'pick', interactive_type: 'TextInput', column_name: 'gene' },
  { uid: 'd', component: 'advanced_viz', id: 'volc', kind: 'volcano', roles: { feature_id: 'gene', effect_size: 'log2fc', significance: 'pvalue' } },
];

const strip = (rs: Array<{ uid?: string }>) => rs.map(({ uid: _u, ...r }) => r);

describe('draft round-trip', () => {
  const entry = generateEntry({ tool, output, fixtureFileName: fixture.fileName, fixtureContent: fixture.raw, renders });
  const files = {
    'mytool/module.yaml': entry.moduleYaml,
    [`mytool/${entry.outputYamlName}`]: entry.outputYaml,
    [`mytool/${entry.fixtureName}`]: entry.fixtureContent,
  };

  it('reads the exported files back into the same draft', () => {
    const { draft, notes } = draftFromCatalogFiles(files);
    expect(notes).toEqual([]);
    expect(draft.tool).toEqual({ ...tool });
    expect(draft.output).toEqual(output);
    expect(draft.fixture).toEqual({ fileName: 'results.csv', content: fixture.raw });
    expect(strip(draft.renders)).toEqual(strip(renders));
  });

  it('reads a zip of the same files', async () => {
    const zip = new JSZip();
    for (const [p, t] of Object.entries(files)) zip.file(p, t);
    const back = await filesFromZip(await zip.generateAsync({ type: 'uint8array' }));
    expect(Object.keys(back).sort()).toEqual(Object.keys(files).sort());
  });

  it('notes what it leaves out', () => {
    const extra = { ...files, 'mytool/other.yaml': 'id: mytool_other\nfind: {path_glob: "*"}\nrenders_as: [{component: multiqc}]\n' };
    // Every output comes in now; the requested one leads.
    const all = draftFromCatalogFiles(extra);
    expect(all.draft.output.slug).toBe('results');
    expect(all.draft.moreOutputs?.map((o) => o.output.slug)).toEqual(['other']);
    const other = draftFromCatalogFiles(extra, 'other');
    expect(other.draft.output.slug).toBe('other');
    expect(other.notes.join(' ')).toMatch(/cannot be edited/);
  });

  it('survives the #draft= encoding', async () => {
    const d = toDraft({ tool, output, fixture, renders });
    expect(d.format).toBe(DRAFT_FORMAT);
    const back = await decodeDraftFromUrl(await encodeDraftForUrl(d));
    expect(back.tool).toEqual(d.tool);
    expect(strip(back.renders)).toEqual(d.renders);
    expect(back.fixture?.content).toBe(fixture.raw);
  });

  it('rejects malformed drafts with a reason', () => {
    expect(() => normalizeDraft({ format: 'x' })).toThrow(/Unknown draft format/);
    expect(() => normalizeDraft({ format: DRAFT_FORMAT, tool: {}, output: { slug: 's' } })).toThrow(/tool.id/);
    const ok = normalizeDraft({ format: DRAFT_FORMAT, tool: { id: 't' }, output: { slug: 's' }, renders: [{ component: 'table' }] });
    expect(ok.renders[0].uid).toBeTruthy();
  });
});

describe('recipes round-trip', () => {
  it('exports <slug>.py with `recipe:` and reads it back', () => {
    const code = 'import polars as pl\nSOURCES = []\nOUTPUT_SCHEMA = {"gene": pl.Utf8}\ndef transform(s):\n    return s["raw"]\n';
    const out = { ...output, recipe: { code, inputs: [{ fileName: 'raw.txt', text: 'x' }] } };
    const e = generateEntry({ tool, output: out, fixtureFileName: fixture.fileName, fixtureContent: fixture.raw, renders: [] });
    expect(e.outputYaml).toContain('recipe: mytool/results.py');
    expect(e.recipeFile).toEqual({ name: 'results.py', content: code });
    const { draft, notes } = draftFromCatalogFiles({
      'mytool/module.yaml': e.moduleYaml,
      'mytool/results.yaml': e.outputYaml,
      'mytool/results.csv': e.fixtureContent,
      'mytool/results.py': e.recipeFile!.content,
    });
    expect(notes).toEqual([]);
    // Raw samples are never committed, so they do not come back.
    expect(draft.output.recipe).toEqual({ code });
  });
});

describe('raw recipe samples never leave the tab', () => {
  const code = 'SOURCES = [1]\nOUTPUT_SCHEMA = {"gene": 1}\ndef transform(s):\n    return s\n';
  const withInputs: OutputMeta = { ...output, recipe: { code, inputs: [{ fileName: 'raw.txt', text: 'SECRET-RAW' }] } };

  it('toDraft drops recipe.inputs on every output', () => {
    const d = toDraft({
      tool,
      output: withInputs,
      fixture,
      renders,
      siblings: [{ output: { ...withInputs, slug: 'b' }, fixture: null, renders: [] }],
      activeIndex: 0,
    });
    expect(JSON.stringify(d)).not.toContain('SECRET-RAW');
    expect(d.output.recipe).toEqual({ code });
  });

  it('a link trims every output fixture and strips samples from a hand-built draft', async () => {
    const big = ['a,b', ...Array.from({ length: 500 }, (_, i) => `${i},x`)].join('\n');
    const token = await encodeDraftForUrl({
      format: DRAFT_FORMAT,
      tool,
      output: withInputs,
      renders: [],
      moreOutputs: [{ output: withInputs, fixture: { fileName: 'b.csv', content: big }, renders: [] }],
    });
    const back = await decodeDraftFromUrl(token);
    expect(JSON.stringify(back)).not.toContain('SECRET-RAW');
    expect(back.moreOutputs![0].fixture!.content.split('\n')).toHaveLength(LINK_FIXTURE_ROWS + 1);
  });
});

describe('normalizeDraft shapes', () => {
  const base = { format: DRAFT_FORMAT, tool: { id: 't' }, output: { slug: 's' } };
  it('names the bad field', () => {
    expect(() => normalizeDraft({ ...base, renders: ['x'] })).toThrow(/draft\.renders\[0\] must be an object/);
    expect(() => normalizeDraft({ ...base, renders: [{ kind: 'volcano' }] })).toThrow(/draft\.renders\[0\]\.component must be a string/);
    expect(() => normalizeDraft({ ...base, moreOutputs: [{ output: { slug: 'o' }, fixture: { fileName: 'a.csv' } }] })).toThrow(
      /draft\.moreOutputs\[0\]\.fixture needs a fileName and a content string/,
    );
    expect(() => normalizeDraft({ ...base, moreOutputs: [{ output: { slug: 'o' }, renders: [{ component: 3 }] }] })).toThrow(
      /draft\.moreOutputs\[0\]\.renders\[0\]\.component/,
    );
    expect(() => normalizeDraft({ ...base, moreOutputs: {} })).toThrow(/moreOutputs must be a list/);
    expect(() => normalizeDraft({ ...base, appendTo: { toolId: 't' } })).toThrow(/appendTo needs/);
  });
  it('keeps a well-formed appendTo', () => {
    const d = normalizeDraft({ ...base, appendTo: { toolId: 't', outputId: 't_s', yamlPath: 'depictio/catalog/t/s.yaml' } });
    expect(d.appendTo).toEqual({ toolId: 't', outputId: 't_s', yamlPath: 'depictio/catalog/t/s.yaml' });
  });
});

describe('import keeps what export writes back', () => {
  const mod = 'id: mytool\nname: My Tool\ndescription: d\nhomepage: https://x.org\nbiotools_url: null\n';
  it('carries output identity fields, columns, table options and render section/priority', () => {
    const yml = [
      'id: mytool_res',
      'name: Res',
      'origin_tool: Cutadapt',
      'mode: amplicon',
      'stage: qc',
      'description: d',
      'nf_core_url: https://github.com/nf-core/modules/tree/master/modules/nf-core/cutadapt',
      'biotools_url: https://bio.tools/cutadapt',
      'edam_operations: [http://edamontology.org/operation_3192]',
      'edam_formats: [http://edamontology.org/format_3475]',
      'find: { path_glob: "**/*.tsv" }',
      'columns:',
      '  gene: String',
      '  "log 2": Float64',
      'fixture: res.csv',
      'renders_as:',
      '  - { component: table, sortable: false, filterable: true, section: Stats, priority: 2 }',
      '  - { component: figure, visu_type: bar, dict_kwargs: {x: gene}, section: Bars, priority: 0 }',
      '  - { component: card, column: gene, aggregation: nunique, secondary_layout: vertical, section: S, priority: 1 }',
    ].join('\n');
    const files = { 'mytool/module.yaml': mod, 'mytool/res.yaml': yml, 'mytool/res.csv': 'gene,log 2\nA,1\n' };
    const { draft } = draftFromCatalogFiles(files);
    const e = generateEntry({
      tool: draft.tool,
      output: draft.output,
      fixtureFileName: draft.fixture!.fileName,
      fixtureContent: draft.fixture!.content,
      renders: draft.renders as RenderSpec[],
    });
    expect(yaml.load(e.outputYaml)).toEqual(yaml.load(yml));
  });

  it('keeps a recipe reference that is not <tool>/<slug>.py, and writes columns only without a recipe', () => {
    const yml = (recipe: string) =>
      `id: mytool_res\nfind: { path_glob: "*" }\nrecipe: ${recipe}\ncolumns: {a: String}\nfixture: res.csv\nrenders_as: [{component: table}]\n`;
    const files = (recipe: string, extra: Record<string, string> = {}) => ({
      'mytool/module.yaml': mod,
      'mytool/res.yaml': yml(recipe),
      'mytool/res.csv': 'a\nx\n',
      ...extra,
    });
    // Pipeline-keyed: kept, no .py written.
    const ext = draftFromCatalogFiles(files('nf-core/ampliseq/x.py'));
    expect(ext.draft.output.recipe).toEqual({ code: '', ref: 'nf-core/ampliseq/x.py' });
    expect(ext.draft.output.columns).toBeUndefined();
    const e1 = generateEntry({ tool: ext.draft.tool, output: ext.draft.output, fixtureFileName: 'res.csv', fixtureContent: 'a\nx\n', renders: [] });
    expect(yaml.load(e1.outputYaml)).toMatchObject({ recipe: 'nf-core/ampliseq/x.py' });
    expect((yaml.load(e1.outputYaml) as Record<string, unknown>).columns).toBeUndefined();
    expect(e1.recipeFile).toBeUndefined();
    // Module-owned under another name: kept, written under that name.
    const own = draftFromCatalogFiles(files('mytool/shared_canonical.py', { 'mytool/shared_canonical.py': 'X = 1\n' }));
    const e2 = generateEntry({ tool: own.draft.tool, output: own.draft.output, fixtureFileName: 'res.csv', fixtureContent: '', renders: [] });
    expect(yaml.load(e2.outputYaml)).toMatchObject({ recipe: 'mytool/shared_canonical.py' });
    expect(e2.recipeFile).toEqual({ name: 'shared_canonical.py', content: 'X = 1\n' });
  });
});

// @vitest-environment node
import { describe, it, expect } from 'vitest';
import {
  DRAFT_FORMAT,
  decodeDraftFromUrl,
  draftFromCatalogFiles,
  encodeDraftForUrl,
  filesFromZip,
  normalizeDraft,
  toDraft,
} from '../catalog/draft';
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

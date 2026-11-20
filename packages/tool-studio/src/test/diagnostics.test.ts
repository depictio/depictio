import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { validateDraft, nfCoreModuleOf, parseIndex, triage, isTodo, type DraftToValidate } from '../catalog/diagnostics';
import { parseFixture } from '../catalog/parseFixture';
import { kindsMapFrom } from '../catalog/kinds';
import type { RenderSpec } from '../types';

const kindsPayload = JSON.parse(
  readFileSync(resolve(__dirname, '..', '..', 'public', 'kinds.json'), 'utf8'),
);
const kinds = kindsMapFrom(kindsPayload.kinds);
const fixture = parseFixture(
  'results.csv',
  'gene,log2fc,pvalue,sample\nA,2.1,0.01,S1\nB,-1.2,0.2,S2\n',
);
const volcano: RenderSpec = {
  uid: 'v',
  component: 'advanced_viz',
  kind: 'volcano',
  roles: { feature_id: 'gene', effect_size: 'log2fc', significance: 'pvalue' },
};

const base = (): DraftToValidate => ({
  tool: { id: 'mytool', name: 'My Tool', source: 'nf-core', description: 'd', homepage: 'https://x.org' },
  output: { slug: 'results', path_glob: '**/mytool/*.csv' },
  fixture,
  renders: [volcano],
  kinds,
});

const codes = (d: DraftToValidate) => validateDraft(d).filter((x) => x.severity === 'error').map((x) => x.code);

describe('validateDraft', () => {
  it('passes a clean draft (schema + grounding + identity)', () => {
    expect(validateDraft(base()).filter((d) => d.severity === 'error')).toEqual([]);
  });

  it('flags missing identity fields with stable codes and paths', () => {
    const d = base();
    d.tool = { ...d.tool, description: '', homepage: undefined };
    const diags = validateDraft(d);
    expect(diags.find((x) => x.code === 'identity.homepage_missing')).toMatchObject({ path: 'tool.homepage', step: 0 });
    expect(codes(d)).toContain('identity.description_missing');
  });

  it('mirrors _check_identity_urls', () => {
    const d = base();
    d.tool = { ...d.tool, biotools_url: 'https://example.org/x', nf_core_url: 'https://github.com/foo/bar', source_url: 'ftp://x' };
    expect(codes(d)).toEqual(expect.arrayContaining(['identity.biotools_url', 'identity.nf_core_url', 'identity.source_url']));
  });

  it('checks nf-core and EDAM existence against the vendored indices', () => {
    const d = base();
    d.tool = { ...d.tool, nf_core_url: 'https://github.com/nf-core/modules/tree/master/modules/nf-core/nope/meta.yml', edam_topics: ['topic_9999'] };
    d.indices = { nfCoreModules: parseIndex('# x\nfastp\n'), edamTerms: parseIndex('topic_0102\n') };
    expect(codes(d)).toEqual(expect.arrayContaining(['index.nf_core_unknown', 'index.edam_unknown']));
    expect(nfCoreModuleOf('https://github.com/nf-core/modules/tree/master/modules/nf-core/samtools/stats/main.nf')).toBe('samtools/stats');
  });

  it('needs a glob or a filename', () => {
    const d = base();
    d.output = { slug: 'results', path_glob: '' };
    expect(codes(d)).toContain('find.missing');
    d.output = { slug: 'results', path_glob: '', filename: 'stats.txt' };
    expect(codes(d)).not.toContain('find.missing');
  });

  it('rejects a header-only fixture and a cross-tool copy', () => {
    const d = base();
    d.fixture = parseFixture('h.csv', 'gene,log2fc,pvalue\n');
    expect(codes(d)).toContain('fixture.no_data');
    const d2 = base();
    d2.fixtureSha256 = 'abc';
    d2.catalog = { tools: [{ id: 'other', name: 'Other', outputs: [{ id: 'other_x', slug: 'x', renders_as: [], fixtureSha256: 'abc' }] }] };
    expect(codes(d2)).toContain('fixture.duplicate');
    // The same tool sharing a fixture between its outputs is fine.
    d2.catalog.tools[0].id = 'mytool';
    expect(codes(d2)).not.toContain('fixture.duplicate');
  });

  it('reports render dtype errors and id collisions', () => {
    const d = base();
    d.renders = [
      { ...volcano, roles: { ...volcano.roles, effect_size: 'sample' } as Record<string, string> },
      { uid: 't', component: 'table', id: 'mytool_results' },
      { uid: 'c1', component: 'card', id: 'dup', column: 'log2fc', aggregation: 'average' },
      { uid: 'c2', component: 'card', id: 'dup', column: 'log2fc', aggregation: 'max' },
    ];
    const diags = validateDraft(d);
    expect(diags.find((x) => x.code === 'render.role_dtype')).toMatchObject({ path: 'renders[0]', renderUid: 'v', step: 2 });
    expect(codes(d)).toEqual(expect.arrayContaining(['render.id_collides_output', 'render.id_duplicate']));
  });

  it('validates generated YAML against the snapshotted JSON Schemas', () => {
    const d = base();
    d.tool = { ...d.tool, version: 'v1' };
    // version fails both the semver rule and the schema pattern.
    expect(codes(d)).toEqual(expect.arrayContaining(['identity.version', 'schema.module']));
  });

  it('sorts errors before warnings', () => {
    const d = base();
    d.fixture = parseFixture('bad.csv', 'gene,log2fc,pvalue\nA,1\nB,2,0.1\n');
    d.tool = { ...d.tool, description: '' };
    const diags = validateDraft(d);
    const firstWarning = diags.findIndex((x) => x.severity === 'warning');
    expect(firstWarning).toBeGreaterThan(0);
    expect(diags.slice(firstWarning).every((x) => x.severity === 'warning')).toBe(true);
  });
});

describe('recipe diagnostics', () => {
  const code = [
    'import polars as pl',
    'SOURCES = [RecipeSource(ref="raw")]',
    'OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {',
    '    "gene": pl.Utf8,  # id',
    "    'log2fc': pl.Float64,",
    '    # "commented": pl.Utf8,',
    '}',
    'def transform(sources):',
    '    return sources["raw"]',
  ].join('\n');

  it('reads OUTPUT_SCHEMA keys statically', async () => {
    const { recipeOutputColumns } = await import('../catalog/diagnostics');
    expect(recipeOutputColumns(code)).toEqual(['gene', 'log2fc']);
  });

  it('requires the load_recipe symbols and a fixture that is the recipe output', () => {
    const d = base();
    d.output = { ...d.output, recipe: { code: code.replace('def transform', 'def other') } };
    expect(codes(d)).toContain('recipe.missing_symbol');
    d.output = { ...d.output, recipe: { code: code.replace("'log2fc'", "'depth'") } };
    expect(validateDraft(d).find((x) => x.code === 'recipe.fixture_mismatch')?.message).toMatch(/depth/);
    d.output = { ...d.output, recipe: { code } };
    expect(codes(d).filter((c) => c.startsWith('recipe.'))).toEqual([]);
  });

  it('does not swallow OPTIONAL_OUTPUT_SCHEMA after a one-line OUTPUT_SCHEMA', async () => {
    const { recipeOutputColumns } = await import('../catalog/diagnostics');
    const oneLine = [
      'OUTPUT_SCHEMA = {"sample": pl.Utf8, "value": pl.List(pl.Float64)}',
      'OPTIONAL_OUTPUT_SCHEMA = {',
      '    "extra": pl.Utf8,',
      '}',
    ].join('\n');
    expect(recipeOutputColumns(oneLine)).toEqual(['sample', 'value']);
  });

  it('skips strings, comments and nested braces inside the literal', async () => {
    const { recipeOutputColumns } = await import('../catalog/diagnostics');
    const tricky = [
      'OUTPUT_SCHEMA = {',
      '    "a}b": pl.Utf8,  # a "fake": key } in a comment',
      "    'nested': pl.Struct({'inner': pl.Utf8}),",
      '    """doc: not a key""" "c": pl.Int64,',
      '}',
      'OPTIONAL_OUTPUT_SCHEMA = {"d": pl.Utf8}',
    ].join('\n');
    expect(recipeOutputColumns(tricky)).toEqual(['a}b', 'nested', 'c']);
    expect(recipeOutputColumns('OUTPUT_SCHEMA = {"a": pl.Utf8')).toBeNull();
  });

  it('keeps an external recipe reference as a warning, not an empty-recipe error', () => {
    const d = base();
    d.output = { ...d.output, recipe: { code: '', ref: 'nf-core/ampliseq/x.py' } };
    expect(validateDraft(d).find((x) => x.code.startsWith('recipe.'))).toMatchObject({ code: 'recipe.external', severity: 'warning' });
  });
});

describe('triage: what is left to fill in vs what is wrong', () => {
  it('an empty draft has only "to do" items, no schema error for renders_as', () => {
    const d: DraftToValidate = {
      tool: { id: 'mytool', name: 'My Tool', source: 'nf-core' },
      output: { slug: 'results', path_glob: '' },
      fixture: null,
      renders: [],
      kinds,
    };
    const all = validateDraft(d);
    const t = triage(all);
    expect(t.errors.map((x) => x.code)).toEqual([]);
    expect(t.todos.map((x) => x.code).sort()).toEqual(
      ['find.missing', 'fixture.missing', 'identity.description_missing', 'identity.homepage_missing', 'renders.empty'].sort(),
    );
    // Still errors for export and the agent API: CI would reject the entry.
    expect(t.todos.every((x) => x.severity === 'error' && isTodo(x))).toBe(true);
  });

  it('warns on brace or comma globs, which fnmatch does not expand', () => {
    const d = base();
    d.output = { ...d.output, path_glob: '**/macs3/*.gappedPeak,*.narrowPeak}' };
    const w = validateDraft(d).filter((x) => x.code === 'find.glob_braces');
    expect(w).toHaveLength(1);
    expect(w[0].severity).toBe('warning');
    expect(validateDraft(base()).some((x) => x.code === 'find.glob_braces')).toBe(false);
  });
});

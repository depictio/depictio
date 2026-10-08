import { describe, expect, it } from 'vitest';

import {
  compareVersions,
  defaultVersionFor,
  findRunPipeline,
  formatVersion,
  groupRunTemplates,
  isRunFolderCapable,
  runTemplateMatch,
  runTemplateMatchText,
  sameVersion,
  splitTemplateId,
} from './runFolderTemplates';

const tpl = (template_id: string, name: string, extra: Record<string, unknown> = {}) => ({
  template_id,
  name,
  description: null,
  ...extra,
});

const CATALOG = [
  tpl('nf-core/ampliseq/2.14.0', 'Ampliseq'),
  tpl('nf-core/ampliseq/2.16.0', 'Ampliseq', { engine: 'nextflow' }),
  tpl('nf-core/ampliseq/2.9.0', 'Ampliseq'),
  tpl('nf-core/rnaseq/3.26.0', 'RNA-seq'),
  tpl('generic/manifest-tables/1', 'Manifest tables', { run_folder_capable: false }),
  tpl('generic/folder-tables/1', 'Folder tables', { run_folder_capable: true }),
  tpl('init/catalog_conformance', 'Catalog conformance'),
  tpl('nf-core/variantbenchmarking/1.4.0/categories/indel', 'Variant benchmarking, indels'),
  tpl('nf-core/variantbenchmarking/1.4.0/categories/small', 'Variant benchmarking, small'),
];

describe('splitTemplateId', () => {
  it('finds the version segment', () => {
    expect(splitTemplateId('nf-core/ampliseq/2.16.0')).toEqual({
      source: 'nf-core',
      pipeline: 'nf-core/ampliseq',
      version: '2.16.0',
      variant: null,
    });
    expect(splitTemplateId('generic/manifest-tables/1').version).toBe('1');
  });

  it('keeps what follows the version as a variant', () => {
    expect(splitTemplateId('nf-core/variantbenchmarking/1.4.0/categories/indel')).toEqual({
      source: 'nf-core',
      pipeline: 'nf-core/variantbenchmarking',
      version: '1.4.0',
      variant: 'categories/indel',
    });
  });

  it('tolerates an id without a version', () => {
    expect(splitTemplateId('init/catalog_conformance')).toEqual({
      source: 'init',
      pipeline: 'init/catalog_conformance',
      version: null,
      variant: null,
    });
  });
});

describe('versions', () => {
  it('compares numerically, segment by segment', () => {
    expect(compareVersions('2.10.0', '2.9.1')).toBeGreaterThan(0);
    expect(compareVersions('v3.1', '3.1.0')).toBe(0);
    expect(compareVersions('2.0.0-rc1', '2.0.0')).toBeLessThan(0);
    expect(compareVersions('2.0.0-rc2', '2.0.0-rc10')).toBeLessThan(0);
  });

  it('spells and compares versions with or without a v', () => {
    expect(formatVersion('2.16.0')).toBe('v2.16.0');
    expect(formatVersion('v2.16.0')).toBe('v2.16.0');
    expect(sameVersion('v2.16.0', '2.16.0')).toBe(true);
    expect(sameVersion(null, '2.16.0')).toBe(false);
  });
});

describe('groupRunTemplates', () => {
  it('keeps one entry per pipeline, versions newest first, latest marked', () => {
    const groups = groupRunTemplates(CATALOG);
    const ampliseq = findRunPipeline(groups, 'nf-core/ampliseq/2.14.0');
    expect(ampliseq?.key).toBe('nf-core/ampliseq');
    expect(ampliseq?.versions.map((v) => v.version)).toEqual(['2.16.0', '2.14.0', '2.9.0']);
    expect(ampliseq?.versions.map((v) => v.latest)).toEqual([true, false, false]);
    expect(ampliseq?.engine).toBe('nextflow');
    expect(ampliseq?.title).toBe('Ampliseq');
  });

  it('groups by source, nf-core first, and drops what cannot read a run folder', () => {
    const groups = groupRunTemplates(CATALOG);
    expect(groups.map((g) => g.label)).toEqual(['nf-core', 'Generic']);
    const ids = groups.flatMap((g) => g.pipelines.flatMap((p) => p.versions.map((v) => v.templateId)));
    expect(ids).not.toContain('generic/manifest-tables/1');
    expect(ids).not.toContain('init/catalog_conformance');
    expect(ids).toContain('generic/folder-tables/1');
  });

  it('gives each variant of a template family its own entry', () => {
    const groups = groupRunTemplates(CATALOG);
    const keys = groups[0].pipelines.map((p) => p.key);
    expect(keys).toContain('nf-core/variantbenchmarking/categories/indel');
    expect(keys).toContain('nf-core/variantbenchmarking/categories/small');
  });

  it('keeps an included template the catalog leaves out', () => {
    const groups = groupRunTemplates(CATALOG, ['nf-core/sarek/3.10.0']);
    expect(findRunPipeline(groups, 'nf-core/sarek/3.10.0')?.title).toBe('nf-core/sarek/3.10.0');
  });

  it('treats a catalog without the flag as capable, init templates aside', () => {
    expect(isRunFolderCapable(tpl('nf-core/x/1.0.0', 'X'))).toBe(true);
    expect(isRunFolderCapable(tpl('init/x', 'X'))).toBe(false);
    expect(isRunFolderCapable(tpl('nf-core/x/1.0.0', 'X', { run_folder_capable: false }))).toBe(
      false,
    );
  });
});

describe('defaultVersionFor', () => {
  const ampliseq = findRunPipeline(groupRunTemplates(CATALOG), 'nf-core/ampliseq/2.16.0')!;

  it('prefers the detected template, then the run version, then the newest', () => {
    expect(defaultVersionFor(ampliseq, { detectedTemplateId: 'nf-core/ampliseq/2.9.0' })).toBe(
      'nf-core/ampliseq/2.9.0',
    );
    expect(defaultVersionFor(ampliseq, { runVersion: '2.14.0' })).toBe('nf-core/ampliseq/2.14.0');
    expect(defaultVersionFor(ampliseq, { detectedTemplateId: 'nf-core/rnaseq/3.26.0' })).toBe(
      'nf-core/ampliseq/2.16.0',
    );
  });
});

describe('runTemplateMatch', () => {
  const run = { runPipeline: 'nf-core/ampliseq', runVersion: '2.15.0' };

  it('is exact when the template targets the run version', () => {
    expect(
      runTemplateMatch({ runPipeline: 'nf-core/ampliseq', runVersion: '2.16.0', templateId: 'nf-core/ampliseq/2.16.0' }),
    ).toBe('exact');
  });

  it('keeps the server verdict for the template it chose', () => {
    expect(
      runTemplateMatch({
        ...run,
        templateId: 'nf-core/ampliseq/2.16.0',
        detectedTemplateId: 'nf-core/ampliseq/2.16.0',
        detectedMatch: 'closest',
      }),
    ).toBe('closest');
  });

  it('flags another version or another pipeline picked by hand', () => {
    expect(
      runTemplateMatch({
        ...run,
        templateId: 'nf-core/ampliseq/2.14.0',
        detectedTemplateId: 'nf-core/ampliseq/2.16.0',
        detectedMatch: 'closest',
      }),
    ).toBe('other-version');
    expect(runTemplateMatch({ ...run, templateId: 'nf-core/rnaseq/3.26.0' })).toBe(
      'other-pipeline',
    );
  });

  it('says none when the run is known but no template is', () => {
    expect(runTemplateMatch({ ...run, detectedMatch: 'none' })).toBe('none');
    expect(runTemplateMatch({ ...run, templateId: null })).toBe('none');
  });

  it('cannot tell without a recognised run', () => {
    expect(runTemplateMatch({ templateId: 'nf-core/ampliseq/2.16.0' })).toBeNull();
    expect(runTemplateMatch({})).toBeNull();
  });
});

describe('runTemplateMatchText', () => {
  it('spells both versions out', () => {
    const text = runTemplateMatchText('closest', { run: '2.15.0', template: '2.16.0' });
    expect(text.label).toBe('Closest available version');
    expect(text.detail).toContain('v2.15.0');
    expect(text.detail).toContain('v2.16.0');
    expect(runTemplateMatchText('exact', { template: '2.16.0' }).label).toBe('Exact match');
    expect(runTemplateMatchText('none').label).toBe('No matching template');
  });
});

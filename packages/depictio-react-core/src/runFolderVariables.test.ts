import { describe, expect, it } from 'vitest';

import { humanizeVariableName, templateSettingValue } from './runFolderVariables';

describe('humanizeVariableName', () => {
  it('writes a name in sentence case, columns and folders spelled out', () => {
    expect(humanizeVariableName('GROUP_COL')).toBe('Group column');
    expect(humanizeVariableName('ANNOTATION_COLS')).toBe('Annotation columns');
    expect(humanizeVariableName('METADATA_FILE')).toBe('Metadata file');
    expect(humanizeVariableName('OUTPUT_DIR')).toBe('Output folder');
    expect(humanizeVariableName('PHYLUM_LEVEL')).toBe('Phylum level');
  });

  it('keeps ID and a few other acronyms in capitals', () => {
    expect(humanizeVariableName('METADATA_ID_COL')).toBe('Metadata ID column');
    expect(humanizeVariableName('SAMPLE_IDS')).toBe('Sample IDs');
    expect(humanizeVariableName('MANIFEST_URL')).toBe('Manifest URL');
    expect(humanizeVariableName('SKIP_QC')).toBe('Skip QC');
    expect(humanizeVariableName('ID_COL')).toBe('ID column');
  });

  it('reads a SKIP_ flag as "Skip ..." and an IS_ flag as what it turns on', () => {
    expect(humanizeVariableName('SKIP_ALPHA_RAREFACTION')).toBe('Skip alpha rarefaction');
    expect(humanizeVariableName('SKIP_ANCOM')).toBe('Skip ancom');
    expect(humanizeVariableName('IS_NANOPORE')).toBe('Nanopore');
    expect(humanizeVariableName('IS_MULTIREGION')).toBe('Multiregion');
    // A bare IS is a word like any other.
    expect(humanizeVariableName('IS')).toBe('Is');
  });

  it('calls DATA_ROOT the run folder, and leaves an empty name empty', () => {
    expect(humanizeVariableName('DATA_ROOT')).toBe('Run folder');
    expect(humanizeVariableName('  ')).toBe('');
  });
});

describe('templateSettingValue', () => {
  const ROOT = '/data/runs/run42';

  it('writes a location under the run folder relative to it', () => {
    expect(templateSettingValue(`${ROOT}/qiime2/phylogenetic_tree/tree.nwk`, ROOT)).toEqual({
      kind: 'run-path',
      relative: 'qiime2/phylogenetic_tree/tree.nwk',
      full: `${ROOT}/qiime2/phylogenetic_tree/tree.nwk`,
    });
    expect(
      templateSettingValue('s3://bucket/runs/run42/input/meta.tsv', 's3://bucket/runs/run42/'),
    ).toEqual({
      kind: 'run-path',
      relative: 'input/meta.tsv',
      full: 's3://bucket/runs/run42/input/meta.tsv',
    });
  });

  it('matches a run folder typed with ~ against a location written in full', () => {
    expect(templateSettingValue('/Users/me/run42/input/meta.tsv', '~/run42')).toMatchObject({
      kind: 'run-path',
      relative: 'input/meta.tsv',
    });
  });

  it('names the run folder itself, and keeps a location elsewhere whole', () => {
    expect(templateSettingValue(`${ROOT}/`, ROOT)).toEqual({ kind: 'run-folder', full: `${ROOT}/` });
    expect(templateSettingValue('/refs/genome.fa', ROOT)).toEqual({
      kind: 'path',
      full: '/refs/genome.fa',
    });
  });

  it('cuts a long list after its first items', () => {
    expect(templateSettingValue('treatment, site,depth,season,batch', ROOT)).toEqual({
      kind: 'list',
      items: ['treatment', 'site', 'depth', 'season', 'batch'],
      shown: ['treatment', 'site', 'depth'],
      more: 2,
    });
    expect(templateSettingValue('a,b', ROOT, { maxItems: 3 })).toEqual({
      kind: 'list',
      items: ['a', 'b'],
      shown: ['a', 'b'],
      more: 0,
    });
  });

  it('leaves other values as they are, and an empty one empty', () => {
    expect(templateSettingValue('habitat', ROOT)).toEqual({ kind: 'text', text: 'habitat' });
    expect(templateSettingValue('true', ROOT)).toEqual({ kind: 'text', text: 'true' });
    // A trailing comma is not a list.
    expect(templateSettingValue('habitat,', ROOT)).toEqual({ kind: 'text', text: 'habitat,' });
    expect(templateSettingValue('  ', ROOT)).toEqual({ kind: 'empty' });
    expect(templateSettingValue(null, ROOT)).toEqual({ kind: 'empty' });
  });
});

import { describe, expect, it } from 'vitest';

import {
  matchesTemplateFilter,
  parseTemplateOrigin,
  templateFilterValues,
} from './templateFilter';

const RNASEQ = { template_id: 'nf-core/rnaseq/3.26.0' };
const VIRALRECON = { template_id: 'nf-core/viralrecon/3.0.0' };
const GALAXY = { template_id: 'galaxy/rnaseq' };

describe('parseTemplateOrigin', () => {
  it('splits a full id into source, repo and version', () => {
    expect(parseTemplateOrigin(RNASEQ)).toEqual({
      full: 'nf-core/rnaseq/3.26.0',
      source: 'nf-core',
      repo: 'rnaseq',
      version: '3.26.0',
    });
  });

  it('accepts the id as a plain string', () => {
    expect(parseTemplateOrigin('nf-core/rnaseq/3.26.0')?.repo).toBe('rnaseq');
  });

  it('leaves version empty when the id omits it', () => {
    expect(parseTemplateOrigin('nf-core/rnaseq')).toEqual({
      full: 'nf-core/rnaseq',
      source: 'nf-core',
      repo: 'rnaseq',
      version: '',
    });
  });

  it('keeps a leading-v version out of the repo slot', () => {
    expect(parseTemplateOrigin('nf-core/rnaseq/v3.26.0')?.version).toBe('v3.26.0');
  });

  it('returns null for a project that came from no template', () => {
    expect(parseTemplateOrigin(null)).toBeNull();
    expect(parseTemplateOrigin(undefined)).toBeNull();
    expect(parseTemplateOrigin('')).toBeNull();
    expect(parseTemplateOrigin('   ')).toBeNull();
    expect(parseTemplateOrigin({})).toBeNull();
  });
});

describe('templateFilterValues', () => {
  it('offers the source and the source/repo pair, never the version', () => {
    expect(templateFilterValues(parseTemplateOrigin(RNASEQ)!)).toEqual([
      'nf-core',
      'nf-core/rnaseq',
    ]);
  });

  it('offers only the source when the id names no pipeline', () => {
    expect(templateFilterValues(parseTemplateOrigin('depictio')!)).toEqual(['depictio']);
  });
});

describe('matchesTemplateFilter', () => {
  it('matches everything when nothing is selected', () => {
    expect(matchesTemplateFilter(RNASEQ, [])).toBe(true);
    expect(matchesTemplateFilter(null, [])).toBe(true);
  });

  it('scopes to a whole source', () => {
    expect(matchesTemplateFilter(RNASEQ, ['nf-core'])).toBe(true);
    expect(matchesTemplateFilter(VIRALRECON, ['nf-core'])).toBe(true);
    expect(matchesTemplateFilter(GALAXY, ['nf-core'])).toBe(false);
  });

  it('scopes to one pipeline without catching its siblings', () => {
    expect(matchesTemplateFilter(RNASEQ, ['nf-core/rnaseq'])).toBe(true);
    expect(matchesTemplateFilter(VIRALRECON, ['nf-core/rnaseq'])).toBe(false);
  });

  it('ignores the version on both sides', () => {
    expect(matchesTemplateFilter(RNASEQ, ['nf-core/rnaseq/1.0.0'])).toBe(true);
    expect(matchesTemplateFilter('nf-core/rnaseq', ['nf-core/rnaseq/3.26.0'])).toBe(true);
  });

  it('accepts a hand-written bare pipeline name', () => {
    expect(matchesTemplateFilter(RNASEQ, ['rnaseq'])).toBe(true);
    expect(matchesTemplateFilter(VIRALRECON, ['rnaseq'])).toBe(false);
    // A bare name is source-agnostic on purpose: it is what someone types.
    expect(matchesTemplateFilter(GALAXY, ['rnaseq'])).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(matchesTemplateFilter(RNASEQ, ['NF-Core/RNAseq'])).toBe(true);
  });

  it('unions the selected values', () => {
    const selected = ['nf-core/rnaseq', 'nf-core/viralrecon'];
    expect(matchesTemplateFilter(RNASEQ, selected)).toBe(true);
    expect(matchesTemplateFilter(VIRALRECON, selected)).toBe(true);
    expect(matchesTemplateFilter(GALAXY, selected)).toBe(false);
  });

  it('excludes projects with no template once a selection exists', () => {
    expect(matchesTemplateFilter(null, ['nf-core'])).toBe(false);
    expect(matchesTemplateFilter({}, ['nf-core'])).toBe(false);
  });
});

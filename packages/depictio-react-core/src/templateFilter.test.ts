import { describe, expect, it } from 'vitest';

import {
  describeRevisionMismatch,
  matchesTemplateFilter,
  parseTemplateOrigin,
  readTemplateRevision,
  templateFilterValues,
  templateRevisionMismatch,
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

describe('readTemplateRevision', () => {
  it('reads a dashboard stamp', () => {
    expect(
      readTemplateRevision({
        template_id: 'nf-core/nascent/2.3.0',
        template_version: '1.2.0',
        imported_at: '2026-10-29 10:14:00',
      }),
    ).toEqual({
      templateId: 'nf-core/nascent/2.3.0',
      version: '1.2.0',
      at: '2026-10-29 10:14:00',
    });
  });

  it('reads a project origin, whose date is applied_at', () => {
    expect(
      readTemplateRevision({
        template_id: 'nf-core/nascent/2.3.0',
        template_version: 'v1.0.0',
        applied_at: '2026-10-01 08:00:00',
      }),
    ).toEqual({
      templateId: 'nf-core/nascent/2.3.0',
      version: '1.0.0',
      at: '2026-10-01 08:00:00',
    });
  });

  it('is null without a revision', () => {
    expect(readTemplateRevision(null)).toBeNull();
    expect(readTemplateRevision('nf-core/rnaseq/3.26.0')).toBeNull();
    expect(readTemplateRevision({ template_id: 'nf-core/rnaseq/3.26.0' })).toBeNull();
    expect(readTemplateRevision({ template_id: 'x', template_version: '  ' })).toBeNull();
  });
});

describe('templateRevisionMismatch', () => {
  const project = { template_id: 'nf-core/nascent/2.3.0', template_version: '1.1.0' };
  const dashboard = (version: string, id = 'nf-core/nascent/2.3.0') => ({
    template_id: id,
    template_version: version,
    imported_at: '2026-10-29 10:14:00',
  });

  it('is null when both sides name the same revision', () => {
    expect(templateRevisionMismatch(dashboard('1.1.0'), project)).toBeNull();
  });

  it('reports a dashboard imported from another revision', () => {
    const mismatch = templateRevisionMismatch(dashboard('1.0.0'), project);
    expect(mismatch?.dashboard.version).toBe('1.0.0');
    expect(mismatch?.project.version).toBe('1.1.0');
  });

  it('reports a dashboard imported from another template of the family', () => {
    expect(templateRevisionMismatch(dashboard('1.1.0', 'nf-core/nascent/2.2.0'), project)).not.toBeNull();
  });

  it('has nothing to compare when either side records no revision', () => {
    expect(templateRevisionMismatch(null, project)).toBeNull();
    expect(templateRevisionMismatch(dashboard('1.0.0'), null)).toBeNull();
    expect(templateRevisionMismatch(dashboard('1.0.0'), { template_id: 'nf-core/nascent/2.3.0' })).toBeNull();
  });
});

describe('describeRevisionMismatch', () => {
  const rev = (templateId: string, version: string) => ({ templateId, version, at: null });

  it('names the two versions when the template is the same', () => {
    const id = 'nf-core/nascent/2.3.0';
    expect(describeRevisionMismatch({ dashboard: rev(id, '1.0.0'), project: rev(id, '1.1.0') })).toBe(
      'Dashboard imported from v1.0.0, project ingested with v1.1.0.',
    );
  });

  it('names the templates when they differ', () => {
    expect(
      describeRevisionMismatch({
        dashboard: rev('nf-core/nascent/2.2.0', '1.0.0'),
        project: rev('nf-core/nascent/2.3.0', '1.0.0'),
      }),
    ).toBe(
      'Dashboard imported from nf-core/nascent/2.2.0 v1.0.0, project ingested with nf-core/nascent/2.3.0 v1.0.0.',
    );
  });
});

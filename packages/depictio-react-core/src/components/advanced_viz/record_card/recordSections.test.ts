import { describe, expect, it } from 'vitest';

import {
  buildRecordSections,
  DEFAULT_SECTION_TITLE,
  descriptionGroup,
} from './recordSections';

describe('descriptionGroup', () => {
  it('reads a short prefix as the group name', () => {
    expect(descriptionGroup('FastQC: percent duplicates')).toBe('FastQC');
  });

  it('ignores prose that merely contains a colon', () => {
    expect(
      descriptionGroup('Mean coverage over the target regions: primary alignments only'),
    ).toBeNull();
  });

  it('ignores a prefix with nothing after it, and an absent description', () => {
    expect(descriptionGroup('Notes:')).toBeNull();
    expect(descriptionGroup(undefined)).toBeNull();
    expect(descriptionGroup('')).toBeNull();
  });
});

describe('buildRecordSections', () => {
  const columns = ['sample', 'reads', 'dup_rate', 'verdict'];

  it('falls back to one Fields section when nothing is described', () => {
    const layout = buildRecordSections({ columns, maxFields: 40 });
    expect(layout.sections).toEqual([{ title: DEFAULT_SECTION_TITLE, columns }]);
    expect(layout.truncated).toBe(0);
  });

  it('groups by the description prefix and keeps the remainder last', () => {
    const layout = buildRecordSections({
      columns,
      descriptions: {
        reads: 'FastQC: total reads',
        dup_rate: 'FastQC: duplicate fraction',
        verdict: 'QC: pass or fail',
      },
      maxFields: 40,
    });
    expect(layout.sections).toEqual([
      { title: 'FastQC', columns: ['reads', 'dup_rate'] },
      { title: 'QC', columns: ['verdict'] },
      { title: DEFAULT_SECTION_TITLE, columns: ['sample'] },
    ]);
  });

  it('honours an explicit layout and drops columns the frame does not carry', () => {
    const layout = buildRecordSections({
      columns,
      sections: { Identity: ['sample', 'missing_col'], Metrics: ['reads'], Empty: ['gone'] },
      maxFields: 40,
    });
    expect(layout.sections).toEqual([
      { title: 'Identity', columns: ['sample'] },
      { title: 'Metrics', columns: ['reads'] },
    ]);
  });

  it('never repeats a heading column as a field', () => {
    const layout = buildRecordSections({
      columns,
      headingColumns: ['sample', 'verdict'],
      maxFields: 40,
    });
    expect(layout.sections[0].columns).toEqual(['reads', 'dup_rate']);
  });

  it('caps the field count across sections and reports the remainder', () => {
    const layout = buildRecordSections({
      columns,
      descriptions: { reads: 'FastQC: total reads', dup_rate: 'FastQC: duplicate fraction' },
      maxFields: 2,
    });
    expect(layout.sections).toEqual([{ title: 'FastQC', columns: ['reads', 'dup_rate'] }]);
    expect(layout.truncated).toBe(2);
  });

  it('keeps at least one field whatever the cap says', () => {
    const layout = buildRecordSections({ columns, maxFields: 0 });
    expect(layout.sections).toEqual([{ title: DEFAULT_SECTION_TITLE, columns: ['sample'] }]);
    expect(layout.truncated).toBe(3);
  });
});

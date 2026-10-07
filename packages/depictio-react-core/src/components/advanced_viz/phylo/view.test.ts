import { describe, expect, it } from 'vitest';

import { nextSummaryRank, rankChoices, summaryBlocker } from './view';

const META = { metadata_wf_id: 'wf', metadata_dc_id: 'dc' };

describe('rankChoices', () => {
  it('lists the rank columns, then the colour column', () => {
    expect(
      rankChoices({ extra_color_cols: ['Phylum', 'Class'], color_col: 'Kingdom' }),
    ).toEqual(['Phylum', 'Class', 'Kingdom']);
  });

  it('keeps a rank set in YAML that no other key names', () => {
    expect(rankChoices({ color_col: 'Kingdom', collapse_rank: 'Genus' })).toEqual([
      'Kingdom',
      'Genus',
    ]);
    expect(rankChoices({ color_col: 'Kingdom' }, 'Order')).toEqual(['Kingdom', 'Order']);
  });

  it('never offers the tip id, and lists each column once', () => {
    expect(
      rankChoices({
        taxon_col: 'asv',
        extra_color_cols: ['asv', 'Phylum', 'Phylum'],
        color_col: 'Phylum',
        collapse_rank: 'asv',
      }),
    ).toEqual(['Phylum']);
    // The default tip id column is `taxon`.
    expect(rankChoices({ color_col: 'taxon' })).toEqual([]);
  });

  it('leaves the label column out: a label is per tip, not a group', () => {
    expect(rankChoices({ color_col: 'group', label_col: 'strain' })).toEqual(['group']);
  });
});

describe('summaryBlocker', () => {
  it('needs the tip metadata, by id or by tag', () => {
    expect(summaryBlocker({ color_col: 'Kingdom' }, ['Kingdom'])).toMatch(/tip-metadata/);
    expect(summaryBlocker({ metadata_dc_tag: 'tips' }, ['Kingdom'])).toBeNull();
    expect(summaryBlocker(META, ['Kingdom'])).toBeNull();
  });

  it('needs a rank column to collapse to', () => {
    expect(summaryBlocker(META, [])).toMatch(/rank column/);
  });
});

describe('nextSummaryRank', () => {
  it('returns to the rank last collapsed to', () => {
    expect(nextSummaryRank(['Kingdom', 'Phylum', 'Class'], 'Class')).toBe('Class');
  });

  it('prefers Phylum, then the first rank', () => {
    expect(nextSummaryRank(['Kingdom', 'phylum', 'Class'], null)).toBe('phylum');
    expect(nextSummaryRank(['group', 'habitat'], null)).toBe('group');
    // A remembered rank no longer offered is forgotten.
    expect(nextSummaryRank(['group', 'habitat'], 'Phylum')).toBe('group');
  });

  it('has nothing to go to without a rank', () => {
    expect(nextSummaryRank([], 'Phylum')).toBeNull();
  });
});

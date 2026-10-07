import { describe, expect, it } from 'vitest';

import {
  nextSummaryRank,
  orderTaxonomicRanks,
  rankChoices,
  summaryBlocker,
  isTaxonomicRank,
  withRanksInOrder,
} from './view';

const META = { metadata_wf_id: 'wf', metadata_dc_id: 'dc' };

describe('rankChoices', () => {
  it('lists the ranks root to leaf, whatever order the config names them in', () => {
    expect(
      rankChoices({ extra_color_cols: ['Phylum', 'Class'], color_col: 'Kingdom' }),
    ).toEqual(['Kingdom', 'Phylum', 'Class']);
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

describe('orderTaxonomicRanks', () => {
  it('puts ranks root to leaf, ignoring case, PR2 levels in their place', () => {
    expect(orderTaxonomicRanks(['Genus', 'class', 'Subdivision', 'Domain', 'Kingdom'])).toEqual([
      'Domain',
      'Kingdom',
      'Subdivision',
      'class',
      'Genus',
    ]);
  });

  it('keeps other columns after the ranks, in the order given', () => {
    expect(orderTaxonomicRanks(['habitat', 'Phylum', 'group', 'Kingdom'])).toEqual([
      'Kingdom',
      'Phylum',
      'habitat',
      'group',
    ]);
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

describe('isTaxonomicRank', () => {
  it('knows the ranks whatever their case, and nothing else', () => {
    expect(['Kingdom', 'phylum', 'Subdivision'].map(isTaxonomicRank)).toEqual([true, true, true]);
    expect(['locality', 'label'].map(isTaxonomicRank)).toEqual([false, false]);
  });
});

describe('withRanksInOrder', () => {
  it('orders the ranks in the slots they hold and leaves the other columns in place', () => {
    expect(withRanksInOrder(['locality', 'Phylum', 'depth', 'Class', 'Kingdom'])).toEqual([
      'locality',
      'Kingdom',
      'depth',
      'Phylum',
      'Class',
    ]);
    expect(withRanksInOrder(['a', 'b'])).toEqual(['a', 'b']);
  });
});

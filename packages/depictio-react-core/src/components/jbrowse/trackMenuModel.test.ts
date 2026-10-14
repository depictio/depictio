import { describe, expect, it } from 'vitest';

import type { JBrowseTrackRow } from '../../api';
import {
  SHOW_ALL_CAP,
  countOpen,
  groupTrackRows,
  hideAllIds,
  manifestTrackIds,
  rowMatchesQuery,
  sectionsOf,
  showAllPlan,
  withSectionCategory,
} from './trackMenuModel';

const row = (
  track_id: string,
  extra: Partial<JBrowseTrackRow> = {},
): JBrowseTrackRow => ({
  track_id,
  name: track_id.toUpperCase(),
  format: 'bigwig',
  sample: null,
  selection_value: null,
  ...extra,
});

const rows: JBrowseTrackRow[] = [
  row('genes', { name: 'Genes', source: 'annotation', format: 'gff' }),
  row('a', { category: 'H3K27ac', sample: 'liver' }),
  row('b', { category: 'H3K4me3', sample: 'liver' }),
  row('c', { category: 'H3K27ac', sample: 'brain', color: '#f00' }),
  row('d'),
  row('ucsc-cons', { name: 'Conservation', source: 'ucsc' }),
  row('extra-1', { name: 'Blacklist', source: 'extra', format: 'bed' }),
];

describe('groupTrackRows', () => {
  it('groups reference first, then manifest categories, then UCSC by group', () => {
    const groups = groupTrackRows(rows);
    expect(groups.map((g) => g.label)).toEqual([
      'Reference',
      'H3K27ac',
      'H3K4me3',
      'Other tracks',
      'UCSC · Other',
    ]);
    expect(groups[0].rows.map((r) => r.track_id)).toEqual(['genes', 'extra-1']);
    expect(groups[1].rows.map((r) => r.track_id)).toEqual(['a', 'c']);
    expect(groups[4].rows.map((r) => r.track_id)).toEqual(['ucsc-cons']);
  });

  it('puts project tracks and external tracks in their own sections', () => {
    const groups = groupTrackRows(rows);
    expect(sectionsOf(groups)).toEqual(['external', 'project']);
    expect(groups.filter((g) => g.section === 'project').map((g) => g.label)).toEqual([
      'H3K27ac',
      'H3K4me3',
      'Other tracks',
    ]);
    expect(groups.filter((g) => g.section === 'external').map((g) => g.label)).toEqual([
      'Reference',
      'UCSC · Other',
    ]);
  });

  it('splits UCSC tracks into one readable section per UCSC group', () => {
    const groups = groupTrackRows([
      row('k', { name: 'knownGene', source: 'ucsc', category: 'genes' }),
      row('m', { name: 'rmsk', source: 'ucsc', category: 'rep' }),
      row('g', { name: 'mane', source: 'ucsc', category: 'genes' }),
      row('z', { name: 'odd', source: 'ucsc', category: 'zz' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      'UCSC · Genes',
      'UCSC · Repeats',
      'UCSC · zz',
    ]);
    expect(groups[0].rows.map((r) => r.track_id)).toEqual(['k', 'g']);
  });

  it('calls uncategorised rows "Tracks" when no row has a category', () => {
    const groups = groupTrackRows([row('x'), row('y')]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('Tracks');
  });

  it('treats rows without a source as manifest rows', () => {
    expect(manifestTrackIds([row('x'), row('y', { source: 'ucsc' })])).toEqual(['x']);
  });

  it('keeps a category named like a fixed group apart from it', () => {
    const groups = groupTrackRows([row('x', { category: 'UCSC' }), row('y', { source: 'ucsc' })]);
    expect(groups.map((g) => g.key)).toEqual(['category:UCSC', 'ucsc:']);
  });

  it('filters on every search term, across fields, and drops empty groups', () => {
    const groups = groupTrackRows(rows, 'h3k27ac LIVER');
    expect(groups.map((g) => g.label)).toEqual(['H3K27ac']);
    expect(groups[0].rows.map((r) => r.track_id)).toEqual(['a']);
    expect(groupTrackRows(rows, 'nothing-matches')).toEqual([]);
  });
});

describe('rowMatchesQuery', () => {
  it('matches everything on an empty query and ignores extra spaces', () => {
    expect(rowMatchesQuery(rows[1], '')).toBe(true);
    expect(rowMatchesQuery(rows[1], '   ')).toBe(true);
    expect(rowMatchesQuery(rows[5], '  conserv ')).toBe(true);
  });
});

describe('showAllPlan', () => {
  it('opens every matching row, in menu order, below the cap', () => {
    const plan = showAllPlan(groupTrackRows(rows));
    expect(plan.ids).toEqual(['genes', 'extra-1', 'a', 'c', 'b', 'd', 'ucsc-cons']);
    expect(plan).toMatchObject({ total: 7, capped: false });
  });

  it('caps at SHOW_ALL_CAP and reports it', () => {
    const many = Array.from({ length: SHOW_ALL_CAP + 5 }, (_, i) => row(`t${i}`));
    const plan = showAllPlan(groupTrackRows(many));
    expect(plan.ids).toHaveLength(SHOW_ALL_CAP);
    expect(plan.ids[0]).toBe('t0');
    expect(plan).toMatchObject({ total: SHOW_ALL_CAP + 5, capped: true });
  });

  it('honours a custom cap', () => {
    expect(showAllPlan(groupTrackRows(rows), 2)).toEqual({
      ids: ['genes', 'extra-1'],
      total: 7,
      capped: true,
    });
  });
});

describe('hideAllIds', () => {
  it('only closes manifest tracks', () => {
    expect(hideAllIds(['genes', 'a', 'ucsc-cons', 'd', 'unknown'], rows)).toEqual(['a', 'd']);
  });
});

describe('countOpen', () => {
  it('counts the open rows', () => {
    expect(countOpen(rows, ['a', 'genes', 'not-a-row'])).toBe(2);
    expect(countOpen(rows, [])).toBe(0);
  });
});

describe('withSectionCategory', () => {
  it('puts manifest tracks under Project and the rest under External', () => {
    const rows = [
      row('sv_1', { source: 'manifest' }),
      row('ucsc_mane', { source: 'ucsc' }),
      row('annot', { source: 'annotation' }),
    ];
    const confs = [
      { trackId: 'sv_1', category: ['GM18939x02'] },
      { trackId: 'ucsc_mane', category: ['UCSC', 'genes'] },
      { trackId: 'annot', category: ['Annotation'] },
    ];
    expect(withSectionCategory(confs, rows)).toEqual([
      { trackId: 'sv_1', category: ['Project tracks', 'GM18939x02'] },
      { trackId: 'ucsc_mane', category: ['External tracks', 'UCSC · Genes'] },
      { trackId: 'annot', category: ['External tracks', 'Annotation'] },
    ]);
  });

  it('treats a track with no row as external and keeps configs without category', () => {
    const out = withSectionCategory([{ trackId: 'unknown' }], []);
    expect(out).toEqual([{ trackId: 'unknown', category: ['External tracks'] }]);
  });
});

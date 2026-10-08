import { describe, expect, it } from 'vitest';

import {
  groupRunCollections,
  isCollectionReady,
  runCollectionSection,
  runCollectionTotals,
  runFoundNothing,
} from './runFolderReport';

const dc = (tag: string, status: string, matched = 0, optional = false) => ({
  data_collection_tag: tag,
  status,
  matched,
  optional,
});

describe('sections', () => {
  it('puts problems first, ready next, optional last', () => {
    const groups = groupRunCollections([
      dc('a', 'ok', 3),
      dc('b', 'missing'),
      dc('c', 'empty', 0, true),
      dc('d', 'pruned', 0, true),
      dc('e', 'empty'),
    ]);
    expect(groups.missing.map((d) => d.data_collection_tag)).toEqual(['b', 'e']);
    expect(groups.ready.map((d) => d.data_collection_tag)).toEqual(['a']);
    expect(groups.optional.map((d) => d.data_collection_tag)).toEqual(['c', 'd']);
  });

  it('counts an uncounted ok row as ready and a pruned one never', () => {
    expect(isCollectionReady(dc('m', 'ok', 0))).toBe(true);
    expect(isCollectionReady(dc('p', 'pruned', 2))).toBe(false);
    expect(runCollectionSection(dc('o', 'ok', 1, true))).toBe('ready');
  });
});

describe('totals', () => {
  it('leaves pruned collections out of both counts', () => {
    expect(
      runCollectionTotals([dc('a', 'ok', 1), dc('b', 'missing'), dc('c', 'pruned', 0, true)]),
    ).toEqual({ ready: 1, considered: 2 });
  });
});

describe('runFoundNothing', () => {
  it('is true when every counted collection found nothing', () => {
    expect(runFoundNothing([dc('a', 'missing'), dc('b', 'empty')])).toBe(true);
    expect(runFoundNothing([dc('a', 'missing'), dc('m', 'ok', 0)])).toBe(true);
    expect(runFoundNothing([])).toBe(true);
    expect(runFoundNothing([dc('p', 'pruned', 0, true)])).toBe(true);
  });

  it('is false once anything matched, or when nothing could be counted', () => {
    expect(runFoundNothing([dc('a', 'missing'), dc('b', 'ok', 2)])).toBe(false);
    expect(runFoundNothing([dc('m', 'ok', 0)])).toBe(false);
  });
});

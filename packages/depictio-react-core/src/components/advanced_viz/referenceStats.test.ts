import { describe, expect, it, vi } from 'vitest';

import type { StoredMetadata } from '../../api';
import { buildGenomeSpySpec } from './genomespy/genomeSpySpec';
import type { GenomeViewConfig } from './genomespy/genomeSpySpec';
import { loadGenomeViewRows } from './genomespy/genomeViewData';
import {
  computeReferenceStat,
  computeReferenceStats,
  profileReferenceRequests,
  referenceStatLabel,
  resolveProfileReferenceY,
  resolveReference,
  resolveScatterReference,
  resolveScoreThreshold,
  scatterReferenceRequests,
  scoreThresholdRequests,
  scoreThresholdTail,
} from './referenceStats';

describe('referenceStatLabel', () => {
  it('names the statistic as a statistic of the table', () => {
    expect(referenceStatLabel('median')).toBe('median of this table');
    expect(referenceStatLabel('p95')).toBe('95th percentile of this table');
  });
});

describe('resolveReference', () => {
  it('prefers an explicit value over the server statistic', () => {
    expect(resolveReference({ explicit: 3, stat: 'median', computed: 7 })).toEqual({
      value: 3,
      stat: null,
      label: null,
    });
  });

  it('uses the server statistic when no value is set, and names it', () => {
    expect(resolveReference({ explicit: null, stat: 'median', computed: 7 })).toEqual({
      value: 7,
      stat: 'median',
      label: 'median of this table',
    });
  });

  it("keeps the author's label over the generated one", () => {
    const ref = resolveReference({ explicit: undefined, stat: 'p90', computed: 1, label: 'p90' });
    expect(ref.label).toBe('p90');
  });

  it('draws nothing when the statistic did not come back', () => {
    expect(resolveReference({ explicit: null, stat: 'median', computed: null }).value).toBeNull();
    expect(resolveReference({ explicit: NaN, stat: null, computed: 4 }).value).toBeNull();
  });
});

describe('scatter_xy', () => {
  const config = { x_col: 'x', y_col: 'y', reference_stat: 'median' as const };

  it('asks for the statistic of the axis the line crosses', () => {
    expect(scatterReferenceRequests(config, 'horizontal', null)).toEqual({
      reference_value: { column: 'y', stat: 'median' },
    });
    expect(scatterReferenceRequests(config, 'vertical', null)).toEqual({
      reference_value: { column: 'x', stat: 'median' },
    });
    expect(scatterReferenceRequests(config, 'diagonal', null)).toBeUndefined();
    expect(scatterReferenceRequests(config, 'horizontal', 2)).toBeUndefined();
    expect(scatterReferenceRequests({ x_col: 'x', y_col: 'y' }, 'horizontal', null)).toBeUndefined();
  });

  it('prefers reference_stats over a missing value, and the reader value over both', () => {
    const stats = { reference_value: 12.5 };
    expect(resolveScatterReference(config, 'horizontal', null, stats)).toMatchObject({
      value: 12.5,
      label: 'median of this table',
    });
    expect(resolveScatterReference(config, 'horizontal', 3, stats).value).toBe(3);
    expect(resolveScatterReference(config, 'diagonal', null, stats).value).toBeNull();
  });
});

describe('profile', () => {
  it('asks for and draws the horizontal statistic', () => {
    const config = { y_col: 'signal', reference_y_stat: 'mean' as const };
    expect(profileReferenceRequests(config)).toEqual({
      reference_y: { column: 'signal', stat: 'mean' },
    });
    expect(resolveProfileReferenceY(config, { reference_y: 0.7 })).toMatchObject({
      value: 0.7,
      label: 'mean of this table',
    });
  });

  it('keeps an authored reference_y and its label', () => {
    const config = { y_col: 'signal', reference_y: 1, reference_y_stat: 'mean' as const };
    expect(profileReferenceRequests(config)).toBeUndefined();
    expect(resolveProfileReferenceY({ ...config, reference_y_label: 'CpG' }, { reference_y: 9 })).toEqual({
      value: 1,
      stat: null,
      label: 'CpG',
    });
  });
});

describe('manhattan / genome_view threshold', () => {
  const config = { score_col: 'score', score_threshold_stat: 'p95' as const };

  it('uses the server statistic unless a threshold is set', () => {
    expect(resolveScoreThreshold(config, undefined, { score_threshold: 4.1 })).toMatchObject({
      value: 4.1,
      label: '95th percentile of this table',
    });
    expect(resolveScoreThreshold(config, 2, { score_threshold: 4.1 }).value).toBe(2);
    expect(resolveScoreThreshold({ score_col: 'score' }, null, { score_threshold: 4 }).value).toBeNull();
  });

  it('sends the statistic as the tail cut, an explicit value as a number', () => {
    expect(scoreThresholdTail(config, null, 'high')).toEqual({
      column: 'score',
      direction: 'high',
      threshold_stat: 'p95',
    });
    expect(scoreThresholdTail(config, 5, 'low')).toEqual({
      column: 'score',
      direction: 'low',
      threshold: 5,
    });
    expect(scoreThresholdTail({ score_col: 'score' }, null, 'high')).toBeUndefined();
    expect(scoreThresholdRequests(config, null)).toEqual({
      score_threshold: { column: 'score', stat: 'p95' },
    });
    expect(scoreThresholdRequests(config, 3)).toBeUndefined();
  });
});

describe('genome_view data path', () => {
  const metadata = { index: 'gv', wf_id: 'wf1', dc_id: 'dc1' } as unknown as StoredMetadata;
  const config: GenomeViewConfig = {
    chr_col: 'chrom',
    pos_col: 'start',
    score_col: 'coverage',
    score_threshold_stat: 'p95',
  };

  it('asks for the statistic and hands back reference_stats', async () => {
    const fetcher = vi.fn(async () => ({
      rows: { chrom: ['chr1'], start: [1], coverage: [3] },
      reference_stats: { score_threshold: 41 },
    }));
    const res = await loadGenomeViewRows(fetcher, { metadata, config, filters: [] });
    const req = (fetcher.mock.calls as unknown as any[][])[0][0];
    expect(req.referenceStats).toEqual({ score_threshold: { column: 'coverage', stat: 'p95' } });
    expect(req.tail).toEqual({ column: 'coverage', direction: 'high', threshold_stat: 'p95' });
    expect(res.referenceStats).toEqual({ score_threshold: 41 });
  });

  it('labels the rule when a statistic placed it', () => {
    const colors = {
      textColor: 'text',
      gridColor: 'grid',
      ruleColor: 'rule',
      palette: ['a'],
    } as any;
    const rows = { chrom: ['chr1', 'chr1'], start: [1, 50], coverage: [1, 2] };
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...config, score_threshold: 41 },
      colors,
      thresholdLabel: '95th percentile of this table',
    });
    const text = JSON.stringify(spec);
    expect(text).toContain('95th percentile of this table');
    expect(text).toContain('"datum":41');
  });
});

describe('computeReferenceStat (hosts holding every row)', () => {
  it('matches the server: nulls ignored, linear quantiles', () => {
    expect(computeReferenceStat([5, 1, 3, null, 'x', 2, 4], 'median')).toBe(3);
    expect(computeReferenceStat([1, 2, 3, 4], 'median')).toBe(2.5);
    expect(computeReferenceStat([10, 20], 'p90')).toBeCloseTo(19);
    expect(computeReferenceStat(Array.from({ length: 101 }, (_, i) => i), 'p95')).toBeCloseTo(95);
    expect(computeReferenceStat([1, Infinity, 3], 'mean')).toBe(2);
    expect(computeReferenceStat([], 'median')).toBeNull();
  });

  it('answers a request off whole columns', () => {
    const columns: Record<string, unknown[]> = { y: [1, 2, 3] };
    expect(
      computeReferenceStats(
        { reference_value: { column: 'y', stat: 'median' }, other: { column: 'z', stat: 'mean' } },
        (name) => columns[name],
      ),
    ).toEqual({ reference_value: 2, other: null });
    expect(computeReferenceStats(undefined, () => undefined)).toBeUndefined();
  });
});

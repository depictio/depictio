import { describe, expect, it } from 'vitest';
import { readableAxisTitle, withReadableTitle } from './axisTitle';

describe('readableAxisTitle', () => {
  it('reads a fallback column name as words', () => {
    expect(readableAxisTitle('lane_label')).toBe('Lane');
    expect(readableAxisTitle('mean_depth')).toBe('Mean depth');
    expect(readableAxisTitle('genome_pct')).toBe('Genome (%)');
    expect(readableAxisTitle('faith_pd')).toBe('Faith PD');
    expect(readableAxisTitle('offset_bp')).toBe('Offset (bp)');
    expect(readableAxisTitle('aa_pos')).toBe('AA pos');
  });
  it('keeps the log transform in front', () => {
    expect(readableAxisTitle('neg_log10_padj')).toBe('−log10 padj');
    expect(readableAxisTitle('log10_gap_length')).toBe('log10 gap length');
  });
  it('leaves written titles and sample ids alone', () => {
    expect(readableAxisTitle('Mean signal')).toBe('Mean signal');
    expect(readableAxisTitle('SRR7961102_GSM3415666_MShef11')).toBe('SRR7961102_GSM3415666_MShef11');
    expect(readableAxisTitle('depth')).toBe('depth');
  });
  it('rewrites both title shapes', () => {
    expect(withReadableTitle({ title: 'read_label' })).toEqual({ title: 'Read' });
    expect(withReadableTitle({ title: { text: 'sample_id', font: { size: 11 } } })).toEqual({
      title: { text: 'Sample ID', font: { size: 11 } },
    });
  });
});

import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import {
  buildGenomeAxis,
  classifyLog2,
  copyNumberBucket,
  CnvRow,
  decimateBins,
  formatBp,
  genomeX,
  hoverText,
  isSegmentValue,
  parseCnvRows,
  segmentStrokes,
  sortChromosomes,
} from './cnvLayout';

const COLS = {
  sample: 'sample',
  chrom: 'chrom',
  start: 'start',
  end: 'end',
  log2: 'log2',
  baf: 'baf',
  copyNumber: 'copy_number',
  segment: 'segment',
  label: 'label',
};

function bin(chrom: string, start: number, log2: number, baf: number | null = null): CnvRow {
  return {
    sample: 'T1',
    chrom,
    start,
    end: start + 100,
    log2,
    baf,
    copyNumber: null,
    label: null,
    kind: 'bin',
  };
}

describe('parseCnvRows', () => {
  it('reads the required roles and resolves every optional one', () => {
    const rows = parseCnvRows(
      {
        sample: ['T1', 'T1'],
        chrom: ['chr1', 'chr1'],
        start: ['0', 1000],
        end: [1000, 2000],
        log2: ['0.5', -1.2],
        baf: [0.5, null],
        copy_number: [3, null],
        segment: ['bin', 'segment'],
        label: ['MYC', ''],
      },
      COLS,
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ chrom: 'chr1', start: 0, end: 1000, log2: 0.5, kind: 'bin' });
    expect(rows[0].baf).toBe(0.5);
    expect(rows[0].copyNumber).toBe(3);
    expect(rows[0].label).toBe('MYC');
    expect(rows[1].kind).toBe('segment');
    expect(rows[1].baf).toBeNull();
    expect(rows[1].label).toBeNull();
  });

  it('drops rows that cannot be placed and defaults end to start', () => {
    const rows = parseCnvRows(
      {
        sample: ['T1', 'T1', 'T1'],
        chrom: ['chr1', '', 'chr2'],
        start: [10, 20, 'not-a-number'],
        end: [null, 30, 40],
        log2: [0.1, 0.2, 0.3],
      },
      { sample: 'sample', chrom: 'chrom', start: 'start', end: 'end', log2: 'log2' },
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ chrom: 'chr1', start: 10, end: 10, kind: 'bin' });
  });

  it('treats every row as a bin when no segment column is bound', () => {
    const rows = parseCnvRows(
      { sample: ['T1'], chrom: ['chr1'], start: [0], end: [10], log2: [0], segment: ['segment'] },
      { sample: 'sample', chrom: 'chrom', start: 'start', end: 'end', log2: 'log2' },
    );
    expect(rows[0].kind).toBe('bin');
  });
});

describe('isSegmentValue', () => {
  it('accepts the canonical spelling and the truthy variants', () => {
    for (const v of ['segment', 'SEGMENT', ' seg ', 'true', '1', 'yes', true]) {
      expect(isSegmentValue(v)).toBe(true);
    }
  });

  it('rejects bins, blanks and nulls', () => {
    for (const v of ['bin', 'window', '', null, undefined, 0, false]) {
      expect(isSegmentValue(v)).toBe(false);
    }
  });
});

describe('sortChromosomes', () => {
  it('orders numerically, then X, Y, MT, then the rest', () => {
    expect(sortChromosomes(['chrX', 'chr10', 'chr2', 'chrMT', 'chr1', 'chrY', 'chrUn_1'])).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
      'chrY',
      'chrMT',
      'chrUn_1',
    ]);
  });
});

describe('buildGenomeAxis', () => {
  const rows = [bin('chr1', 0, 0), bin('chr1', 900, 0), bin('chr2', 0, 0), bin('chr2', 400, 0)];

  it('lays chromosomes end to end with a pad and centres the ticks', () => {
    const axis = buildGenomeAxis(rows, ['chr1', 'chr2']);
    expect(axis.chroms).toEqual(['chr1', 'chr2']);
    expect(axis.offset.get('chr1')).toBe(0);
    // chr1 extends to 1000 (start 900 + end 100), so chr2 starts past it.
    expect(axis.offset.get('chr2')!).toBeGreaterThan(1000);
    expect(axis.span.get('chr1')!.mid).toBe(500);
    expect(axis.ticktext).toEqual(['chr1', 'chr2']);
    expect(axis.tickvals).toHaveLength(2);
    expect(axis.boundaries).toHaveLength(1);
    expect(axis.range[0]).toBeLessThan(0);
    expect(axis.range[1]).toBeGreaterThan(axis.span.get('chr2')!.end);
  });

  it('zooms onto the selected chromosome instead of leaving dead space', () => {
    const axis = buildGenomeAxis(rows, ['chr2']);
    expect(axis.chroms).toEqual(['chr2']);
    expect(axis.offset.get('chr2')).toBe(0);
    expect(axis.boundaries).toEqual([]);
    expect(genomeX(axis, 'chr2', 400)).toBe(400);
    expect(genomeX(axis, 'chr1', 400)).toBeNull();
  });

  it('ignores chromosomes with no rows', () => {
    const axis = buildGenomeAxis(rows, ['chr1', 'chr2', 'chr3']);
    expect(axis.chroms).toEqual(['chr1', 'chr2']);
  });
});

describe('decimateBins', () => {
  it('returns the bins untouched when already under the cap', () => {
    const bins = [bin('chr1', 0, 1), bin('chr1', 100, 2)];
    expect(decimateBins(bins, 10)).toHaveLength(2);
  });

  it('averages consecutive bins and keeps the window span', () => {
    const bins = [bin('chr1', 0, 1), bin('chr1', 100, 3), bin('chr1', 200, 5), bin('chr1', 300, 7)];
    const out = decimateBins(bins, 2);
    expect(out).toHaveLength(2);
    expect(out[0].log2).toBe(2);
    expect(out[0].start).toBe(0);
    expect(out[0].end).toBe(200);
    expect(out[1].log2).toBe(6);
  });

  it('never merges across a chromosome boundary', () => {
    const bins = [bin('chr1', 0, 1), bin('chr2', 0, 3), bin('chr2', 100, 5)];
    const out = decimateBins(bins, 2);
    expect(out.map((r) => r.chrom)).toEqual(['chr1', 'chr2']);
    expect(out[0].log2).toBe(1);
    expect(out[1].log2).toBe(4);
  });

  it('averages only the bins that carry a BAF, and keeps null when none do', () => {
    const withBaf = decimateBins([bin('chr1', 0, 0, 0.5), bin('chr1', 100, 0, null)], 1);
    expect(withBaf[0].baf).toBe(0.5);
    const withoutBaf = decimateBins([bin('chr1', 0, 0, null), bin('chr1', 100, 0, null)], 1);
    expect(withoutBaf[0].baf).toBeNull();
  });

  it('stays the identity when the cap is not a positive number', () => {
    const bins = [bin('chr1', 0, 1), bin('chr1', 100, 2)];
    expect(decimateBins(bins, 0)).toHaveLength(2);
  });
});

describe('classifyLog2', () => {
  it('splits on the two thresholds, inclusive', () => {
    expect(classifyLog2(0.4, 0.3, -0.3)).toBe('gain');
    expect(classifyLog2(0.3, 0.3, -0.3)).toBe('gain');
    expect(classifyLog2(0, 0.3, -0.3)).toBe('neutral');
    expect(classifyLog2(-0.3, 0.3, -0.3)).toBe('loss');
    expect(classifyLog2(-1.4, 0.3, -0.3)).toBe('loss');
  });

  it('reads a missing value as neutral', () => {
    expect(classifyLog2(null, 0.3, -0.3)).toBe('neutral');
    expect(classifyLog2(Number.NaN, 0.3, -0.3)).toBe('neutral');
  });
});

describe('copyNumberBucket', () => {
  it('maps the five levels of the copy-number ramp', () => {
    expect(copyNumberBucket(0)).toBe(0);
    expect(copyNumberBucket(1)).toBe(1);
    expect(copyNumberBucket(2)).toBe(2);
    expect(copyNumberBucket(2.4)).toBe(2);
    expect(copyNumberBucket(4)).toBe(3);
    expect(copyNumberBucket(12)).toBe(4);
    expect(copyNumberBucket(null)).toBe(2);
  });
});

describe('formatBp', () => {
  it('switches unit with magnitude', () => {
    expect(formatBp(1_234_567)).toBe('1.23 Mb');
    expect(formatBp(12_300)).toBe('12.3 kb');
    expect(formatBp(87)).toBe('87 bp');
  });
});

describe('hoverText', () => {
  it('names the locus, the value and every optional role that is bound', () => {
    const row: CnvRow = {
      sample: 'T1',
      chrom: 'chr8',
      start: 127_000_000,
      end: 127_500_000,
      log2: 1.802,
      baf: 0.14,
      copyNumber: 7,
      label: 'MYC',
      kind: 'segment',
    };
    expect(hoverText(row, 'segment log2')).toBe(
      '<b>chr8</b> 127.00 Mb - 127.50 Mb<br>segment log2: 1.802<br>copy number: 7<br>BAF: 0.140<br>MYC',
    );
  });

  it('drops the unbound roles and collapses a zero-width span', () => {
    const row: CnvRow = {
      sample: '',
      chrom: 'chr1',
      start: 1000,
      end: 1000,
      log2: -0.5,
      baf: null,
      copyNumber: null,
      label: null,
      kind: 'bin',
    };
    expect(hoverText(row, 'bin log2')).toBe('<b>chr1</b> 1.0 kb<br>bin log2: -0.500');
  });
});

describe('segmentStrokes', () => {
  const rows = [bin('chr1', 0, 0), bin('chr2', 0, 0)];
  const axis = buildGenomeAxis(rows, ['chr1', 'chr2']);

  function seg(chrom: string, start: number, end: number, log2: number): CnvRow {
    return { sample: 'T1', chrom, start, end, log2, baf: null, copyNumber: null, label: null, kind: 'segment' };
  }

  it('emits a break between segments so they are never joined', () => {
    const { x, y } = segmentStrokes([seg('chr1', 0, 50, 0.6), seg('chr1', 60, 90, -1)], axis);
    expect(x).toEqual([0, 50, null, 60, 90, null]);
    expect(y).toEqual([0.6, 0.6, null, -1, -1, null]);
  });

  it('offsets a segment onto its chromosome block', () => {
    const offset = axis.offset.get('chr2')!;
    const { x } = segmentStrokes([seg('chr2', 10, 40, 0)], axis);
    expect(x).toEqual([offset + 10, offset + 40, null]);
  });

  it('skips a segment on a chromosome the axis does not draw', () => {
    const { x, hover } = segmentStrokes([seg('chrX', 0, 10, 0)], axis);
    expect(x).toEqual([]);
    expect(hover).toEqual([]);
  });
});

// The showcase fixture at its real size, through the whole pure layer. Guards
// the two things a small hand-written case cannot: that 20 000 rows come out
// of the parser intact, and that the decimation leaves every planted call in
// place while it thins the evidence under them.
describe('the showcase fixture end to end', () => {
  const tsv = readFileSync(
    new URL(
      '../../../../../../depictio/projects/init/advanced_viz_showcase/data/cnv_profile_demo.tsv',
      import.meta.url,
    ),
    'utf8',
  );

  const lines = tsv.trim().split('\n');
  const header = lines[0].split('\t');
  const columns: Record<string, unknown[]> = Object.fromEntries(header.map((h) => [h, []]));
  for (const line of lines.slice(1)) {
    const cells = line.split('\t');
    header.forEach((h, i) => (columns[h] as unknown[]).push(cells[i] === '' ? null : cells[i]));
  }

  const rows = parseCnvRows(columns, COLS);

  it('parses every row of the committed fixture', () => {
    expect(rows.length).toBe(lines.length - 1);
    expect(rows.filter((r) => r.kind === 'segment').length).toBeGreaterThanOrEqual(12);
  });

  it('lays the five chromosomes out in order with no overlap', () => {
    const chroms = sortChromosomes(rows.map((r) => r.chrom));
    expect(chroms).toEqual(['chr1', 'chr2', 'chr3', 'chr4', 'chr5']);
    const axis = buildGenomeAxis(rows, chroms);
    for (let i = 1; i < chroms.length; i += 1) {
      expect(axis.span.get(chroms[i])!.start).toBeGreaterThan(axis.span.get(chroms[i - 1])!.end);
    }
  });

  it('thins one sample down to the cap and never touches its calls', () => {
    const mine = rows.filter((r) => r.sample === 'TUMOUR_A');
    const bins = mine.filter((r) => r.kind === 'bin');
    const segments = mine.filter((r) => r.kind === 'segment');
    expect(bins.length).toBe(10_000);

    const thinned = decimateBins(bins, 2000);
    expect(thinned.length).toBeLessThanOrEqual(2000);
    // Same genome covered, and the copy-neutral LOH is still flat after the
    // averaging: a window that straddled the boundary would tilt it.
    expect(thinned[0].start).toBe(bins[0].start);
    expect(thinned[thinned.length - 1].end).toBe(bins[bins.length - 1].end);
    expect(segments.length).toBe(17);
  });

  it('draws one stroke per call, broken between them', () => {
    const chroms = sortChromosomes(rows.map((r) => r.chrom));
    const axis = buildGenomeAxis(rows, chroms);
    const segments = rows.filter((r) => r.kind === 'segment' && r.sample === 'TUMOUR_A');
    const { x, y } = segmentStrokes(segments, axis);
    expect(x.length).toBe(segments.length * 3);
    expect(x.filter((v) => v === null).length).toBe(segments.length);
    expect(y.filter((v) => v === null).length).toBe(segments.length);
  });

  it('classifies the planted events the way the fixture names them', () => {
    const labelled = rows.filter((r) => r.kind === 'segment' && r.label);
    const gain = labelled.find((r) => r.label === 'CN 3 gain')!;
    const loss = labelled.find((r) => r.label === 'CN 1 loss')!;
    const loh = labelled.find((r) => r.label === 'CN 2 copy-neutral LOH')!;
    expect(classifyLog2(gain.log2, 0.3, -0.3)).toBe('gain');
    expect(classifyLog2(loss.log2, 0.3, -0.3)).toBe('loss');
    // The whole reason for the BAF panel: the log2 says nothing here.
    expect(classifyLog2(loh.log2, 0.3, -0.3)).toBe('neutral');
    expect(loh.baf).toBeLessThan(0.2);
  });
});

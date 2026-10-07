import { describe, expect, it } from 'vitest';

import {
  blockBars,
  buildLanes,
  chevronPoints,
  intronSpans,
  laneLabels,
  listGenes,
  normStrand,
  toBlocks,
  type TranscriptBlock,
} from './layout';

const block = (over: Partial<TranscriptBlock> & Pick<TranscriptBlock, 'transcriptId' | 'start' | 'end'>): TranscriptBlock => ({
  geneId: 'G1',
  geneName: 'GENE1',
  chrom: 'chr1',
  coding: false,
  strand: '+',
  sample: null,
  transcriptClass: null,
  expression: null,
  ...over,
});

/** Two isoforms of G1 (one three-exon, one two-exon) plus a single-exon G2. */
const FIXTURE: TranscriptBlock[] = [
  block({ transcriptId: 'T1', start: 100, end: 200, expression: 10 }),
  block({ transcriptId: 'T1', start: 400, end: 500, coding: true, expression: 10 }),
  block({ transcriptId: 'T1', start: 800, end: 900, expression: 10 }),
  block({ transcriptId: 'T2', start: 100, end: 200, expression: 50, transcriptClass: 'novel' }),
  block({ transcriptId: 'T2', start: 800, end: 950, expression: 50, transcriptClass: 'novel' }),
  block({ transcriptId: 'T3', geneId: 'G2', geneName: 'GENE2', start: 5000, end: 5200 }),
];

describe('normStrand', () => {
  it('reads every minus spelling as minus', () => {
    expect(['-', 'minus', 'rev', 'reverse', '-1'].map(normStrand)).toEqual(['-', '-', '-', '-', '-']);
  });

  it('points the GFF3 unknown strand somewhere rather than nowhere', () => {
    expect(['+', '.', '', null, undefined, 1].map(normStrand)).toEqual([
      '+',
      '+',
      '+',
      '+',
      '+',
      '+',
    ]);
  });
});

describe('toBlocks', () => {
  const COLUMNS = {
    transcriptId: 'tx',
    geneId: 'gene',
    chrom: 'chrom',
    start: 'start',
    end: 'end',
    feature: 'feature',
    strand: 'strand',
    expression: 'tpm',
  };
  const FEATURES = { exon: 'exon', cds: 'CDS' };

  const frame = {
    tx: ['T1', 'T1', 'T1', 'T1'],
    gene: ['G1', 'G1', 'G1', null],
    chrom: ['chr1', 'chr1', 'chr1', 'chr1'],
    // The last row has no coordinates, the third is a transcript row.
    start: [100, 400, 100, null],
    end: [200, 500, 900, 950],
    feature: ['exon', 'cds', 'transcript', 'exon'],
    strand: ['-', '-', '-', '-'],
    tpm: [7, 7, 7, 7],
  };

  it('keeps only exon and CDS rows that carry both coordinates', () => {
    const blocks = toBlocks(frame, COLUMNS, FEATURES);
    expect(blocks.map((b) => [b.start, b.end, b.coding])).toEqual([
      [100, 200, false],
      [400, 500, true],
    ]);
  });

  it('matches the feature names case-insensitively, as a GFF3 writes them', () => {
    expect(toBlocks(frame, COLUMNS, { exon: 'EXON', cds: 'cds' })).toHaveLength(2);
  });

  it('swaps a block a writer stored end-first rather than dropping it', () => {
    const swapped = { ...frame, start: [200, 400, 100, null], end: [100, 500, 900, 950] };
    expect(toBlocks(swapped, COLUMNS, FEATURES)[0]).toMatchObject({ start: 100, end: 200 });
  });

  it('falls back on the gene id for the name and leaves unbound columns null', () => {
    const [first] = toBlocks(frame, COLUMNS, FEATURES);
    expect(first.geneName).toBe('G1');
    expect(first.sample).toBeNull();
    expect(first.transcriptClass).toBeNull();
    expect(first.expression).toBe(7);
  });

  it('is empty before the frame arrives', () => {
    expect(toBlocks(null, COLUMNS, FEATURES)).toEqual([]);
  });
});

describe('listGenes', () => {
  it('orders genes by isoform count, most first', () => {
    const genes = listGenes(FIXTURE);
    expect(genes.map((g) => g.id)).toEqual(['G1', 'G2']);
    expect(genes[0]).toMatchObject({ name: 'GENE1', transcripts: 2, blocks: 5 });
    expect(genes[1]).toMatchObject({ name: 'GENE2', transcripts: 1, blocks: 1 });
  });

  it('is empty on an empty frame', () => {
    expect(listGenes([])).toEqual([]);
  });
});

describe('buildLanes', () => {
  it('keeps only the asked gene and orders lanes by expression', () => {
    const { lanes, truncated } = buildLanes(FIXTURE, {
      geneId: 'G1',
      sample: null,
      maxTranscripts: 30,
    });
    expect(lanes.map((l) => l.transcriptId)).toEqual(['T2', 'T1']);
    expect(truncated).toBe(0);
    // Lane bounds span the whole transcript, blocks stay sorted.
    expect(lanes[1].start).toBe(100);
    expect(lanes[1].end).toBe(900);
    expect(lanes[1].blocks.map((b) => b.start)).toEqual([100, 400, 800]);
    expect(lanes[1].hasCoding).toBe(true);
    expect(lanes[0].hasCoding).toBe(false);
  });

  it('carries the transcript class and expression up from the blocks', () => {
    const { lanes } = buildLanes(FIXTURE, { geneId: 'G1', sample: null, maxTranscripts: 30 });
    expect(lanes[0].transcriptClass).toBe('novel');
    expect(lanes[0].expression).toBe(50);
    expect(lanes[1].transcriptClass).toBeNull();
  });

  it('truncates the lowest-expressed isoforms, not an arbitrary tail', () => {
    const { lanes, truncated } = buildLanes(FIXTURE, {
      geneId: 'G1',
      sample: null,
      maxTranscripts: 1,
    });
    expect(lanes.map((l) => l.transcriptId)).toEqual(['T2']);
    expect(truncated).toBe(1);
  });

  it('splits lanes per sample only while several samples are on screen', () => {
    const multi = FIXTURE.filter((b) => b.geneId === 'G1').flatMap((b) => [
      { ...b, sample: 'S1' },
      { ...b, sample: 'S2' },
    ]);
    const all = buildLanes(multi, { geneId: 'G1', sample: null, maxTranscripts: 30 });
    expect(all.samples).toEqual(['S1', 'S2']);
    expect(all.lanes).toHaveLength(4);
    expect(new Set(all.lanes.map((l) => l.key)).size).toBe(4);

    const one = buildLanes(multi, { geneId: 'G1', sample: 'S1', maxTranscripts: 30 });
    expect(one.lanes).toHaveLength(2);
    expect(one.lanes.every((l) => l.sample === 'S1')).toBe(true);
    // The sample list stays complete so the selector can still offer S2.
    expect(one.samples).toEqual(['S1', 'S2']);
  });

  it('returns nothing for a gene that is not in the frame', () => {
    expect(buildLanes(FIXTURE, { geneId: 'nope', sample: null, maxTranscripts: 30 }).lanes).toEqual(
      [],
    );
  });
});

describe('intronSpans', () => {
  const lanes = buildLanes(FIXTURE, { geneId: 'G1', sample: null, maxTranscripts: 30 }).lanes;

  it('is the gaps between consecutive blocks', () => {
    const t1 = lanes.find((l) => l.transcriptId === 'T1')!;
    expect(intronSpans(t1)).toEqual([
      [200, 400],
      [500, 800],
    ]);
  });

  it('has no gap for a single-block transcript', () => {
    const { lanes: g2 } = buildLanes(FIXTURE, { geneId: 'G2', sample: null, maxTranscripts: 30 });
    expect(intronSpans(g2[0])).toEqual([]);
  });

  it('ignores a block fully contained in the one before it', () => {
    const lane = buildLanes(
      [
        block({ transcriptId: 'T', start: 100, end: 900 }),
        block({ transcriptId: 'T', start: 200, end: 300, coding: true }),
        block({ transcriptId: 'T', start: 1200, end: 1300 }),
      ],
      { geneId: 'G1', sample: null, maxTranscripts: 30 },
    ).lanes[0];
    expect(intronSpans(lane)).toEqual([[900, 1200]]);
  });
});

describe('chevronPoints', () => {
  it('spaces marks inside the span and never touches its edges', () => {
    const points = chevronPoints([[0, 100]], 25);
    expect(points).toEqual([20, 40, 60, 80]);
  });

  it('gives a narrow intron one mark at its midpoint', () => {
    expect(chevronPoints([[0, 10]], 100)).toEqual([5]);
  });

  it('caps the marks of one intron', () => {
    expect(chevronPoints([[0, 10000]], 1)).toHaveLength(6);
  });

  it('drops empty and inverted spans', () => {
    expect(chevronPoints([[5, 5] as [number, number], [10, 4] as [number, number]], 1)).toEqual([]);
  });
});

describe('blockBars', () => {
  const lanes = buildLanes(FIXTURE, { geneId: 'G1', sample: null, maxTranscripts: 30 }).lanes;
  const OPTS = {
    exonHeight: 0.4,
    cdsHeight: 0.64,
    exonLabel: 'exon',
    cdsLabel: 'CDS',
    byClass: false,
  };

  it('gives a coding block the taller bar', () => {
    const bars = blockBars(lanes, OPTS).get('')!;
    const coding = bars.filter((b) => b.coding);
    const plain = bars.filter((b) => !b.coding);
    expect(coding).toHaveLength(1);
    expect(coding[0].height).toBe(0.64);
    expect(plain.every((b) => b.height === 0.4)).toBe(true);
  });

  it('draws the coding blocks after the exons that carry them', () => {
    const bars = blockBars(lanes, OPTS).get('')!;
    const firstCoding = bars.findIndex((b) => b.coding);
    expect(firstCoding).toBe(bars.length - 1);
  });

  it('carries base, width and lane index for a horizontal bar', () => {
    const bars = blockBars(lanes, OPTS).get('')!;
    const t2 = bars.filter((b) => b.y === 0);
    expect(t2.map((b) => [b.base, b.width])).toEqual([
      [100, 100],
      [800, 150],
    ]);
  });

  it('never gives a zero-width bar, which Plotly would not draw', () => {
    const point = buildLanes([block({ transcriptId: 'T', start: 500, end: 500 })], {
      geneId: 'G1',
      sample: null,
      maxTranscripts: 30,
    }).lanes;
    expect(blockBars(point, OPTS).get('')![0].width).toBe(1);
  });

  it('splits into one bucket per class only when asked to', () => {
    expect([...blockBars(lanes, OPTS).keys()]).toEqual(['']);
    const byClass = blockBars(lanes, { ...OPTS, byClass: true });
    expect([...byClass.keys()].sort()).toEqual(['', 'novel']);
  });

  it('names the block in the hover the way the author configured it', () => {
    const bars = blockBars(lanes, { ...OPTS, cdsLabel: 'coding' }).get('')!;
    const coding = bars.find((b) => b.coding)!;
    expect(coding.hover[6]).toBe('coding');
    expect(coding.hover[0]).toBe('T1');
  });
});

describe('laneLabels', () => {
  const NEUTRAL = new Set(['known', '']);
  const lanes = buildLanes(FIXTURE, { geneId: 'G1', sample: null, maxTranscripts: 30 }).lanes;

  it('badges a novel isoform and leaves a plain one alone', () => {
    expect(laneLabels(lanes, { perSample: false, neutralClasses: NEUTRAL })).toEqual([
      'T2 [novel]',
      'T1',
    ]);
  });

  it('does not badge a class that carries no novelty claim', () => {
    const known = lanes.map((l) => ({ ...l, transcriptClass: 'known' }));
    expect(laneLabels(known, { perSample: false, neutralClasses: NEUTRAL })).toEqual(['T2', 'T1']);
  });

  it('names the sample only when several share the figure', () => {
    const withSample = lanes.map((l) => ({ ...l, sample: 'S1' }));
    expect(laneLabels(withSample, { perSample: true, neutralClasses: NEUTRAL })[1]).toBe('T1 · S1');
    expect(laneLabels(withSample, { perSample: false, neutralClasses: NEUTRAL })[1]).toBe('T1');
  });
});

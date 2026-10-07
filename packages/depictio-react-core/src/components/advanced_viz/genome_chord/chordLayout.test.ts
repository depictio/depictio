import { describe, expect, it } from 'vitest';

import {
  ASSEMBLY_CHROM_SIZES,
  angleAt,
  angularSeparation,
  arcPath,
  assemblySizes,
  bisectAngle,
  buildRing,
  chordControlPoint,
  chordPath,
  chordStrokeWidth,
  chromOrderKey,
  chromSizesFor,
  compareChrom,
  formatBp,
  isIntraChromosomal,
  linkSummary,
  normaliseChrom,
  parseChordRows,
  polarPoint,
  prepareLinks,
  tickStepFor,
  ticksFor,
  type ChordLink,
} from './chordLayout';

const TAU = Math.PI * 2;

function link(partial: Partial<ChordLink> & Pick<ChordLink, 'chromA' | 'chromB'>): ChordLink {
  return {
    posA: 1_000_000,
    posB: 2_000_000,
    label: null,
    weight: null,
    category: null,
    sample: null,
    row: 0,
    ...partial,
  };
}

describe('parseChordRows', () => {
  const COLS = {
    chromA: 'chrom_a',
    posA: 'pos_a',
    chromB: 'chrom_b',
    posB: 'pos_b',
    label: 'fusion',
    weight: 'reads',
    category: 'kind',
    sample: 'sample',
  };

  it('reads the required roles and resolves every optional one', () => {
    const links = parseChordRows(
      {
        chrom_a: ['chr1', 'chr4'],
        pos_a: ['1000', 2000],
        chrom_b: ['chr2', 'chr4'],
        pos_b: [3000, '4000'],
        fusion: ['BCR--ABL1', ''],
        reads: ['12', null],
        kind: ['translocation', 'inversion'],
        sample: ['S1', 'S2'],
      },
      COLS,
    );
    expect(links).toHaveLength(2);
    expect(links[0]).toEqual({
      chromA: 'chr1',
      posA: 1000,
      chromB: 'chr2',
      posB: 3000,
      label: 'BCR--ABL1',
      weight: 12,
      category: 'translocation',
      sample: 'S1',
      row: 0,
    });
    // An empty label and an absent weight stay null rather than becoming '' or 0.
    expect(links[1].label).toBeNull();
    expect(links[1].weight).toBeNull();
    expect(links[1].row).toBe(1);
  });

  it('leaves the unbound roles null', () => {
    const [link] = parseChordRows(
      { chrom_a: ['chr1'], pos_a: [1], chrom_b: ['chr2'], pos_b: [2], reads: [9] },
      { chromA: 'chrom_a', posA: 'pos_a', chromB: 'chrom_b', posB: 'pos_b' },
    );
    expect(link).toMatchObject({ label: null, weight: null, category: null, sample: null });
  });

  it('drops a link that cannot be placed on the ring', () => {
    const links = parseChordRows(
      {
        chrom_a: ['chr1', '', 'chr3'],
        pos_a: [10, 20, 'not-a-number'],
        chrom_b: ['chr2', 'chr2', 'chr4'],
        pos_b: [30, 40, 50],
      },
      { chromA: 'chrom_a', posA: 'pos_a', chromB: 'chrom_b', posB: 'pos_b' },
    );
    expect(links.map((l) => l.row)).toEqual([0]);
  });

  it('stops at the shortest required column and tolerates a missing one', () => {
    expect(
      parseChordRows(
        { chrom_a: ['chr1', 'chr2'], pos_a: [1, 2], chrom_b: ['chr3'], pos_b: [3, 4] },
        { chromA: 'chrom_a', posA: 'pos_a', chromB: 'chrom_b', posB: 'pos_b' },
      ),
    ).toHaveLength(1);
    expect(
      parseChordRows(
        { chrom_a: ['chr1'], pos_a: [1], chrom_b: ['chr3'] },
        { chromA: 'chrom_a', posA: 'pos_a', chromB: 'chrom_b', posB: 'pos_b' },
      ),
    ).toEqual([]);
  });
});

describe('normaliseChrom / ordering', () => {
  it('folds the chr prefix and case into one key', () => {
    expect(normaliseChrom('chr7')).toBe('7');
    expect(normaliseChrom('Chr7')).toBe('7');
    expect(normaliseChrom(' 7 ')).toBe('7');
    expect(normaliseChrom('chrX')).toBe('x');
  });

  it('orders 1..22 then X, Y, M, then contigs', () => {
    const names = ['chrY', 'chr10', 'GL000009.2', 'chr2', 'chrM', 'chrX', 'chr1'];
    expect([...names].sort(compareChrom)).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
      'chrY',
      'chrM',
      'GL000009.2',
    ]);
    expect(chromOrderKey('chr1')).toBeLessThan(chromOrderKey('chr10'));
    expect(chromOrderKey('chr22')).toBeLessThan(chromOrderKey('chrX'));
  });
});

describe('chromSizesFor', () => {
  it('lays the whole assembly out when one is named', () => {
    const sizes = chromSizesFor([link({ chromA: 'chr4', chromB: 'chr7' })], 'hg38');
    // 24 primary chromosomes; chrM is only drawn when the data lands on it.
    expect(sizes).toHaveLength(24);
    expect(sizes.map((s) => s.name)).not.toContain('chrM');
    // Table order, not data order: the ring is the genome, so chr1 comes first
    // whether or not a link lands on it.
    expect(sizes[0]).toEqual({ name: 'chr1', size: ASSEMBLY_CHROM_SIZES.hg38.chr1 });
  });

  it('adds the mitochondrion only when a link lands on it', () => {
    const sizes = chromSizesFor([link({ chromA: 'chrM', posA: 500, chromB: 'chr1' })], 'hg38');
    expect(sizes.map((s) => s.name)).toContain('chrM');
  });

  it('keeps a contig the assembly table does not name', () => {
    const sizes = chromSizesFor(
      [link({ chromA: 'chr1', chromB: 'GL000009.2', posB: 100_000 })],
      'hg38',
    );
    const contig = sizes.find((s) => s.name === 'GL000009.2');
    expect(contig).toBeDefined();
    expect(contig!.size).toBeGreaterThanOrEqual(100_000);
  });

  it('grows an arc that a locus would otherwise fall off', () => {
    const past = ASSEMBLY_CHROM_SIZES.hg38.chr21 + 5_000_000;
    const sizes = chromSizesFor([link({ chromA: 'chr21', posA: past, chromB: 'chr1' })], 'hg38');
    expect(sizes.find((s) => s.name === 'chr21')!.size).toBe(past);
  });

  it('derives sizes from the data when no assembly is named', () => {
    const sizes = chromSizesFor(
      [
        link({ chromA: 'chr2', posA: 500, chromB: 'chr1', posB: 1000 }),
        link({ chromA: 'chr1', posA: 4000, chromB: 'chr2', posB: 200 }),
      ],
      null,
    );
    expect(sizes.map((s) => s.name)).toEqual(['chr1', 'chr2']);
    // Furthest locus on the chromosome, padded so it is not on the boundary.
    expect(sizes[0].size).toBeGreaterThan(4000);
    expect(sizes[1].size).toBeGreaterThan(500);
  });

  it('keeps the naming the data uses', () => {
    const sizes = chromSizesFor([link({ chromA: '4', posA: 10, chromB: '7' })], 'hg38');
    expect(sizes[3]).toEqual({ name: '4', size: ASSEMBLY_CHROM_SIZES.hg38.chr4 });
    expect(sizes[6]).toEqual({ name: '7', size: ASSEMBLY_CHROM_SIZES.hg38.chr7 });
    expect(sizes[0].name).toBe('chr1');
  });

  it('returns nothing for an unknown assembly name with no data', () => {
    expect(assemblySizes('grch99')).toBeNull();
    expect(chromSizesFor([], 'grch99')).toEqual([]);
  });
});

describe('buildRing', () => {
  const sizes = [
    { name: 'chr1', size: 200 },
    { name: 'chr2', size: 100 },
    { name: 'chr3', size: 100 },
  ];

  it('spends the whole circle on bands and gaps', () => {
    const pad = 0.02;
    const ring = buildRing(sizes, { padAngle: pad });
    const spans = ring.arcs.reduce((acc, a) => acc + (a.end - a.start), 0);
    expect(spans + pad * sizes.length).toBeCloseTo(TAU, 10);
  });

  it('makes each band proportional to its chromosome', () => {
    const ring = buildRing(sizes, { padAngle: 0 });
    const [a, b, c] = ring.arcs.map((arc) => arc.end - arc.start);
    expect(a).toBeCloseTo(b + c, 10);
    expect(b).toBeCloseTo(c, 10);
  });

  it('lays the bands out in order without overlapping', () => {
    const ring = buildRing(sizes, { padAngle: 0.05 });
    for (let i = 1; i < ring.arcs.length; i++) {
      expect(ring.arcs[i].start).toBeGreaterThan(ring.arcs[i - 1].end);
    }
    expect(ring.arcs[0].start).toBe(0);
  });

  it('is empty rather than degenerate when nothing has a size', () => {
    const ring = buildRing([{ name: 'chr1', size: 0 }]);
    expect(ring.arcs).toEqual([]);
    expect(ring.totalSize).toBe(0);
  });
});

describe('angleAt', () => {
  const ring = buildRing([
    { name: 'chr1', size: 1000 },
    { name: 'chr2', size: 1000 },
  ]);

  it('places a locus inside its own band, monotonically', () => {
    const arc = ring.byName.get('1')!;
    const a0 = angleAt(ring, 'chr1', 0)!;
    const mid = angleAt(ring, 'chr1', 500)!;
    const a1 = angleAt(ring, 'chr1', 1000)!;
    expect(a0).toBeCloseTo(arc.start, 10);
    expect(a1).toBeCloseTo(arc.end, 10);
    expect(mid).toBeGreaterThan(a0);
    expect(mid).toBeLessThan(a1);
  });

  it('accepts the other naming of the same chromosome', () => {
    expect(angleAt(ring, '1', 500)).toBeCloseTo(angleAt(ring, 'chr1', 500)!, 10);
  });

  it('clamps a locus past the end rather than drawing it off the ring', () => {
    expect(angleAt(ring, 'chr1', 9_999_999)).toBeCloseTo(ring.byName.get('1')!.end, 10);
  });

  it('returns null for a chromosome that is not on the ring', () => {
    expect(angleAt(ring, 'chr9', 10)).toBeNull();
  });
});

describe('geometry', () => {
  it('measures angles clockwise from twelve o clock', () => {
    expect(polarPoint(0, 0, 10, 0).y).toBeCloseTo(-10, 10);
    expect(polarPoint(0, 0, 10, Math.PI / 2).x).toBeCloseTo(10, 10);
  });

  it('takes the shorter way round when bisecting', () => {
    expect(angularSeparation(0.1, TAU - 0.1)).toBeCloseTo(0.2, 10);
    expect(Math.cos(bisectAngle(0.1, TAU - 0.1))).toBeCloseTo(1, 10);
  });

  it('closes each chromosome band', () => {
    const path = arcPath(500, 500, 400, 420, 0, 1);
    expect(path.startsWith('M ')).toBe(true);
    expect(path.endsWith('Z')).toBe(true);
    expect(path).toContain('A 420 420');
    expect(path).toContain('A 400 400');
  });

  it('draws a chord as one quadratic Bezier', () => {
    const path = chordPath(500, 500, 400, 0, Math.PI);
    expect(path).toMatch(/^M [\d.-]+ [\d.-]+ Q [\d.-]+ [\d.-]+ [\d.-]+ [\d.-]+$/);
  });

  it('pulls the control point to the centre as the loci move apart', () => {
    const far = chordControlPoint(0, 0, 400, 0, Math.PI, 0.8);
    const near = chordControlPoint(0, 0, 400, 0, 0.1, 0.8);
    expect(Math.hypot(far.x, far.y)).toBeCloseTo(0, 6);
    expect(Math.hypot(near.x, near.y)).toBeGreaterThan(300);
  });
});

describe('chordStrokeWidth', () => {
  it('spans the full width range and stays monotonic', () => {
    expect(chordStrokeWidth(1, 1, 1000, 1, 8)).toBeCloseTo(1, 10);
    expect(chordStrokeWidth(1000, 1, 1000, 1, 8)).toBeCloseTo(8, 10);
    const a = chordStrokeWidth(10, 1, 1000, 1, 8);
    const b = chordStrokeWidth(100, 1, 1000, 1, 8);
    expect(b).toBeGreaterThan(a);
  });

  it('is logarithmic, not linear', () => {
    const mid = chordStrokeWidth(100, 1, 10_000, 1, 9);
    // Linear would put 100/10000 near the bottom of the range; log10 puts it in
    // the middle, which is the point of the scale.
    expect(mid).toBeGreaterThan(4);
    expect(mid).toBeLessThan(6);
  });

  it('clamps outside the observed range', () => {
    expect(chordStrokeWidth(0, 10, 1000, 2, 8)).toBe(2);
    expect(chordStrokeWidth(99_999, 10, 1000, 2, 8)).toBe(8);
  });

  it('draws mid-width when no weight is bound or the range is flat', () => {
    expect(chordStrokeWidth(null, 0, 0, 2, 8)).toBe(5);
    expect(chordStrokeWidth(7, 7, 7, 2, 8)).toBe(5);
  });
});

describe('ticks and labels', () => {
  it('keeps the tick count down on a long chromosome', () => {
    const step = tickStepFor(248_956_422, 5);
    expect(248_956_422 / step).toBeLessThanOrEqual(5);
    expect(ticksFor(248_956_422, step).length).toBeLessThanOrEqual(5);
  });

  it('never emits a tick at or past the chromosome end', () => {
    expect(ticksFor(100, 25)).toEqual([25, 50, 75]);
    expect(ticksFor(100, 0)).toEqual([]);
  });

  it('formats positions at the scale a reader expects', () => {
    expect(formatBp(1_806_934)).toBe('1.8 Mb');
    expect(formatBp(140_787_584)).toBe('141 Mb');
    expect(formatBp(640_000)).toBe('640 kb');
    expect(formatBp(812)).toBe('812 bp');
  });
});

describe('linkSummary', () => {
  it('names the link, the two loci and every bound role', () => {
    expect(
      linkSummary(
        link({
          chromA: 'chr22',
          posA: 23_290_413,
          chromB: 'chr9',
          posB: 130_854_064,
          label: 'BCR--ABL1',
          category: 'translocation',
          sample: 'S1',
        }),
        'weight 12',
      ),
    ).toEqual([
      'BCR--ABL1',
      'chr22:23 Mb to chr9:131 Mb',
      'weight 12',
      'translocation',
      'S1',
    ]);
  });

  it('drops the unbound roles and keeps the loci', () => {
    expect(linkSummary(link({ chromA: 'chr1', posA: 500, chromB: 'chr2', posB: 900 }), null)).toEqual(
      ['chr1:500 bp to chr2:900 bp'],
    );
  });
});

describe('prepareLinks', () => {
  const links: ChordLink[] = [
    link({ chromA: 'chr1', chromB: 'chr2', weight: 5, row: 0 }),
    link({ chromA: 'chr3', chromB: 'chr3', weight: 100, row: 1 }),
    link({ chromA: 'chr4', chromB: 'chr5', weight: 50, row: 2 }),
    link({ chromA: 'chr6', chromB: 'chr7', weight: 1, row: 3 }),
  ];

  it('keeps the heaviest links first and reports what it dropped', () => {
    const { kept, dropped } = prepareLinks(links, {
      maxLinks: 2,
      intraChromosomal: true,
    });
    expect(kept.map((l) => l.weight)).toEqual([100, 50]);
    expect(dropped).toBe(2);
  });

  it('drops intra-chromosomal links when the toggle is off', () => {
    const { kept } = prepareLinks(links, { maxLinks: 10, intraChromosomal: false });
    expect(kept.every((l) => !isIntraChromosomal(l))).toBe(true);
    expect(kept).toHaveLength(3);
  });

  it('applies the weight threshold', () => {
    const { kept } = prepareLinks(links, {
      maxLinks: 10,
      intraChromosomal: true,
      minWeight: 50,
    });
    expect(kept.map((l) => l.weight)).toEqual([100, 50]);
  });

  it('reports the weight range of what it kept', () => {
    const { minWeight, maxWeight } = prepareLinks(links, {
      maxLinks: 10,
      intraChromosomal: true,
    });
    expect(minWeight).toBe(1);
    expect(maxWeight).toBe(100);
  });

  it('keeps every unweighted link and orders it by row', () => {
    const unweighted = links.map((l, i) => ({ ...l, weight: null, row: i }));
    const { kept, minWeight, maxWeight } = prepareLinks(unweighted, {
      maxLinks: 10,
      intraChromosomal: true,
      minWeight: 42,
    });
    expect(kept.map((l) => l.row)).toEqual([0, 1, 2, 3]);
    expect([minWeight, maxWeight]).toEqual([0, 0]);
  });
});

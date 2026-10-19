import { describe, expect, it } from 'vitest';

import {
  alongPx,
  autoBinSize,
  bandSummary,
  barForChrom,
  barSummary,
  chromosomeBars,
  compareSample,
  countByChrom,
  densityBands,
  effectiveMode,
  facetColumns,
  featureSummary,
  featuresOf,
  formatValue,
  GEOMETRY,
  idealHeight,
  layoutPanels,
  parseIdeogramRows,
  planFacets,
  pointerAlong,
  positionAt,
  regionFromGesture,
  scaleT,
  spanRect,
  tickStep,
  valueExtent,
  type ChromBar,
  type IdeogramFeature,
} from './ideogramLayout';

const COLS = {
  chrom: 'chrom',
  start: 'start',
  end: 'end',
  value: 'value',
  category: 'category',
  sample: 'sample',
  label: 'label',
  chromLength: 'len',
};

function feature(partial: Partial<IdeogramFeature> & { chrom: string; start: number }): IdeogramFeature {
  return {
    end: partial.start,
    value: null,
    category: null,
    sample: null,
    label: null,
    chromLength: null,
    row: 0,
    ...partial,
  };
}

const bar = (name: string, length: number): ChromBar => ({
  name,
  key: name.replace(/^chr/i, '').toLowerCase(),
  length,
  source: 'data',
});

describe('parseIdeogramRows', () => {
  it('reads every bound role and keeps the frame index', () => {
    const out = parseIdeogramRows(
      {
        chrom: ['chr1', 'chr2'],
        start: [100, '250'],
        end: [200, 300],
        value: [1.5, 'x'],
        category: ['Complete', ''],
        sample: ['G1', 'G2'],
        label: ['b1', null],
        len: [1000, 2000],
      },
      COLS,
    );
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual({
      chrom: 'chr1',
      start: 100,
      end: 200,
      value: 1.5,
      category: 'Complete',
      sample: 'G1',
      label: 'b1',
      chromLength: 1000,
      row: 0,
    });
    // Non-numeric values and empty strings read as unbound, not as zero.
    expect(out[1].value).toBeNull();
    expect(out[1].category).toBeNull();
    expect(out[1].start).toBe(250);
    expect(out[1].row).toBe(1);
  });

  it('drops rows that cannot be placed and fixes reversed or missing ends', () => {
    const out = parseIdeogramRows(
      { chrom: ['chr1', '', 'chr3', 'chr4'], start: [500, 10, null, 40], end: [100, 20, 30, null] },
      { chrom: 'chrom', start: 'start', end: 'end' },
    );
    expect(out.map((f) => f.chrom)).toEqual(['chr1', 'chr4']);
    expect([out[0].start, out[0].end]).toEqual([100, 500]);
    expect([out[1].start, out[1].end]).toEqual([40, 40]);
  });

  it('treats an unbound end as a point and missing optional columns as null', () => {
    const out = parseIdeogramRows({ chrom: ['1'], start: [7] }, { chrom: 'chrom', start: 'start' });
    expect(out[0]).toMatchObject({ start: 7, end: 7, value: null, sample: null, chromLength: null });
  });
});

describe('planFacets', () => {
  const fs = [
    feature({ chrom: '1', start: 1, sample: 'G10' }),
    feature({ chrom: '1', start: 1, sample: 'G2' }),
    feature({ chrom: '1', start: 1, sample: 'G1' }),
  ];

  it('is one unnamed karyotype without a sample column', () => {
    expect(planFacets([feature({ chrom: '1', start: 1 })], { facetBySample: true, maxFacets: 3 })).toEqual({
      shown: [null],
      all: [],
      dropped: 0,
    });
  });

  it('orders samples numerically and caps the facets', () => {
    expect(planFacets(fs, { facetBySample: true, maxFacets: 2 })).toEqual({
      shown: ['G1', 'G2'],
      all: ['G1', 'G2', 'G10'],
      dropped: 1,
    });
  });

  it('shows the chosen sample when not faceting, else the first', () => {
    expect(planFacets(fs, { facetBySample: false, sample: 'G10', maxFacets: 6 }).shown).toEqual(['G10']);
    expect(planFacets(fs, { facetBySample: false, sample: 'nope', maxFacets: 6 }).shown).toEqual(['G1']);
  });

  it('filters the features of one karyotype', () => {
    expect(featuresOf(fs, 'G2')).toHaveLength(1);
    expect(featuresOf(fs, null)).toHaveLength(3);
    expect(compareSample('S2', 'S10')).toBeLessThan(0);
  });
});

describe('chromosomeBars', () => {
  it('sorts naturally and sizes from the furthest feature without a length source', () => {
    const { bars, dropped } = chromosomeBars([
      feature({ chrom: 'chr10', start: 5, end: 900 }),
      feature({ chrom: 'chrX', start: 1, end: 50 }),
      feature({ chrom: 'chr2', start: 1, end: 300 }),
      feature({ chrom: 'chr2', start: 400, end: 700 }),
      feature({ chrom: 'scaffold_10', start: 1, end: 9 }),
      feature({ chrom: 'scaffold_2', start: 1, end: 9 }),
    ]);
    expect(dropped).toBe(0);
    expect(bars.map((b) => b.name)).toEqual(['chr2', 'chr10', 'chrX', 'scaffold_2', 'scaffold_10']);
    expect(bars[0]).toMatchObject({ length: 700, source: 'data', key: '2' });
  });

  it('prefers a stated length, and a feature past it grows the bar', () => {
    const { bars } = chromosomeBars([
      feature({ chrom: 'Chr1', start: 10, end: 20, chromLength: 1000 }),
      feature({ chrom: 'Chr2', start: 10, end: 5000, chromLength: 3000 }),
    ]);
    expect(bars.map((b) => [b.name, b.length, b.source])).toEqual([
      ['Chr1', 1000, 'column'],
      ['Chr2', 5000, 'column'],
    ]);
  });

  it('draws every chromosome of an assembly, the mitochondrion only when used', () => {
    const { bars } = chromosomeBars([feature({ chrom: 'chr7', start: 1, end: 2 })], {
      assembly: 'hg38',
    });
    expect(bars).toHaveLength(24);
    expect(bars.find((b) => b.key === '1')).toMatchObject({ length: 248956422, source: 'assembly' });
    expect(bars.some((b) => b.key === 'm')).toBe(false);
    const withM = chromosomeBars([feature({ chrom: 'chrM', start: 1, end: 2 })], { assembly: 'hg38' });
    expect(withM.bars.some((b) => b.key === 'm')).toBe(true);
    // A contig the table does not know still gets a bar, after the assembly's.
    const decoy = chromosomeBars([feature({ chrom: 'chrUn_KI270302v1', start: 1, end: 900 })], {
      assembly: 'hg38',
    });
    expect(decoy.bars[decoy.bars.length - 1]).toMatchObject({ name: 'chrUn_KI270302v1', source: 'data' });
    // Names follow the data's own spelling when the data names a chromosome.
    const bare = chromosomeBars([feature({ chrom: '7', start: 1, end: 2 })], { assembly: 'hg38' });
    expect(bare.bars.find((b) => b.key === '7')?.name).toBe('7');
  });

  it('restricts and orders by the configured list, ignoring prefix and case', () => {
    const fs = ['chr1', 'chr2', 'chr3'].map((c) => feature({ chrom: c, start: 1, end: 10 }));
    const { bars } = chromosomeBars(fs, { order: ['3', 'CHR1', 'chr9', 'chr3'] });
    expect(bars.map((b) => b.name)).toEqual(['chr3', 'chr1']);
  });

  it('keeps the longest bars under max_chromosomes, in their order', () => {
    const fs = [
      feature({ chrom: 'c1', start: 0, end: 50 }),
      feature({ chrom: 'c2', start: 0, end: 500 }),
      feature({ chrom: 'c3', start: 0, end: 5 }),
      feature({ chrom: 'c4', start: 0, end: 400 }),
    ];
    const { bars, dropped } = chromosomeBars(fs, { maxChromosomes: 2 });
    expect(bars.map((b) => b.name)).toEqual(['c2', 'c4']);
    expect(dropped).toBe(2);
  });
});

describe('effectiveMode', () => {
  it('switches marks to density above the guard and says so', () => {
    expect(effectiveMode('marks', 10, 100)).toEqual({ mode: 'marks', guarded: false });
    expect(effectiveMode('marks', 101, 100)).toEqual({ mode: 'density', guarded: true });
    expect(effectiveMode('density', 1e6, 100)).toEqual({ mode: 'density', guarded: false });
  });
});

describe('densityBands', () => {
  const bars = [bar('chr1', 1000), bar('chr2', 450)];

  it('counts features per bin by their midpoint, clipping the last bin', () => {
    const fs = [
      feature({ chrom: 'chr1', start: 10, end: 20 }),
      feature({ chrom: 'chr1', start: 90, end: 120 }), // midpoint 105 -> bin 1
      feature({ chrom: 'chr1', start: 150, end: 160 }),
      feature({ chrom: 'chr2', start: 420, end: 440 }),
      feature({ chrom: 'chr9', start: 1, end: 2 }), // no bar: not drawn
    ];
    const res = densityBands(fs, bars, { binSize: 100, useValue: false });
    expect(res.binSize).toBe(100);
    expect(res.bands.get('1')).toEqual([
      { start: 0, end: 100, value: 1, count: 1 },
      { start: 100, end: 200, value: 2, count: 2 },
    ]);
    expect(res.bands.get('2')).toEqual([{ start: 400, end: 450, value: 1, count: 1 }]);
    expect(res.bands.has('9')).toBe(false);
    // A count scale starts at zero.
    expect([res.min, res.max]).toEqual([0, 2]);
  });

  it('keeps already-binned rows as their own bands when a value is bound', () => {
    const fs = [
      feature({ chrom: 'chr1', start: 100, end: 200, value: 3 }),
      feature({ chrom: 'chr1', start: 0, end: 100, value: 1 }),
      feature({ chrom: 'chr1', start: 200, end: 300, value: null }),
    ];
    const res = densityBands(fs, bars, { binSize: null, useValue: true });
    expect(res.binSize).toBeNull();
    expect(res.bands.get('1')?.map((b) => [b.start, b.value])).toEqual([
      [0, 1],
      [100, 3],
    ]);
    expect([res.min, res.max]).toEqual([1, 3]);
  });

  it('averages the value per bin when a bin size is set', () => {
    const fs = [
      feature({ chrom: 'chr1', start: 0, end: 10, value: 2 }),
      feature({ chrom: 'chr1', start: 20, end: 30, value: 4 }),
    ];
    const res = densityBands(fs, bars, { binSize: 100, useValue: true });
    expect(res.bands.get('1')).toEqual([{ start: 0, end: 100, value: 3, count: 2 }]);
  });

  it('picks a bin width when none is set, and survives no features', () => {
    const res = densityBands([feature({ chrom: 'chr1', start: 1, end: 1 })], bars, { useValue: false });
    expect(res.binSize).toBe(autoBinSize(1000));
    const empty = densityBands([], bars, { useValue: false });
    expect([empty.min, empty.max, empty.bands.size]).toEqual([0, 0, 0]);
  });
});

describe('scales and steps', () => {
  it('autoBinSize gives at most the target bins in 1-2-5 steps', () => {
    expect(autoBinSize(248_956_422)).toBe(5_000_000);
    expect(autoBinSize(100_000, 100)).toBe(1_000);
    expect(autoBinSize(0)).toBe(1_000);
  });

  it('tickStep fits the target number of ticks', () => {
    expect(tickStep(250_000_000, 5)).toBe(50_000_000);
    expect(tickStep(30_000_000, 4)).toBe(10_000_000);
  });

  it('scaleT clamps and puts a flat scale at its top', () => {
    expect(scaleT(5, 0, 10)).toBe(0.5);
    expect(scaleT(-1, 0, 10)).toBe(0);
    expect(scaleT(11, 0, 10)).toBe(1);
    expect(scaleT(3, 3, 3)).toBe(1);
    expect(scaleT(Number.NaN, 0, 1)).toBe(0);
  });

  it('valueExtent ignores unbound values', () => {
    expect(valueExtent([feature({ chrom: '1', start: 1 })])).toBeNull();
    expect(
      valueExtent([
        feature({ chrom: '1', start: 1, value: 4 }),
        feature({ chrom: '1', start: 1, value: -2 }),
      ]),
    ).toEqual([-2, 4]);
  });
});

describe('layoutPanels', () => {
  const panelA = { title: 'G1', bars: [bar('chr1', 1000), bar('chr2', 500)] };
  const panelB = { title: 'G2', bars: [bar('chr1', 250)] };

  it('places horizontal bars from a common origin on one shared scale', () => {
    const [a, b] = layoutPanels([panelA, panelB], { width: 900, height: 300, orientation: 'horizontal' });
    expect(facetColumns(900, 2, 'horizontal')).toBe(2);
    expect(a.x).toBe(0);
    expect(b.x).toBe(450);
    expect(a.scaleLength).toBe(1000);
    expect(b.scaleLength).toBe(1000);
    // Common origin: every bar of a panel starts at the same x.
    expect(new Set(a.bars.map((g) => g.x)).size).toBe(1);
    // Scaled to length: chr2 is half of chr1, G2's chr1 a quarter of G1's.
    expect(a.bars[1].w / a.bars[0].w).toBeCloseTo(0.5, 5);
    expect(b.bars[0].w / a.bars[0].w).toBeCloseTo(0.25, 5);
    // Rows are stacked top to bottom inside the plot band.
    expect(a.bars[1].y).toBeGreaterThan(a.bars[0].y);
    expect(a.bars[0].y).toBeGreaterThanOrEqual(GEOMETRY.titleH);
    // Labels sit left of the origin, the axis under the bars, inside the panel.
    expect(a.bars[0].labelX).toBeLessThan(a.origin);
    expect(a.ticks[0]).toMatchObject({ pos: 0, label: '0', px: a.origin });
    for (const t of a.ticks) {
      expect(t.px).toBeGreaterThanOrEqual(a.origin);
      expect(t.px).toBeLessThanOrEqual(a.far + 1e-6);
    }
    expect(a.far).toBeLessThanOrEqual(a.x + a.w - GEOMETRY.rightPad + 1e-6);
  });

  it('stacks panels when the width only fits one column', () => {
    const [a, b] = layoutPanels([panelA, panelB], { width: 320, height: 400, orientation: 'horizontal' });
    expect(a.x).toBe(b.x);
    expect(b.y).toBe(200);
  });

  it('stands vertical bars side by side from a top origin', () => {
    const [p] = layoutPanels([{ title: null, bars: panelA.bars }], {
      width: 400,
      height: 300,
      orientation: 'vertical',
    });
    expect(p.bars[0].y).toBe(p.origin);
    expect(p.bars[1].x).toBeGreaterThan(p.bars[0].x);
    expect(p.bars[1].h / p.bars[0].h).toBeCloseTo(0.5, 5);
    expect(p.bars[0].labelY).toBeGreaterThan(p.far);
    expect(p.bars.every((g) => g.showLabel)).toBe(true);
  });

  it('thins vertical labels that would collide', () => {
    const many = Array.from({ length: 40 }, (_, i) => bar(`scaffold_${i + 1}`, 1000 - i));
    const [p] = layoutPanels([{ title: null, bars: many }], { width: 400, height: 300, orientation: 'vertical' });
    const shown = p.bars.filter((g) => g.showLabel).length;
    expect(shown).toBeGreaterThan(0);
    expect(shown).toBeLessThan(40);
  });

  it('returns nothing for an empty box or no panels', () => {
    expect(layoutPanels([], { width: 100, height: 100, orientation: 'horizontal' })).toEqual([]);
    expect(layoutPanels([panelA], { width: 0, height: 100, orientation: 'horizontal' })).toEqual([]);
  });
});

describe('glyphs and gestures', () => {
  const [panel] = layoutPanels([{ title: null, bars: [bar('chr1', 1000)] }], {
    width: 600,
    height: 200,
    orientation: 'horizontal',
  });
  const geom = panel.bars[0];

  it('maps positions to pixels and back', () => {
    expect(alongPx(panel, 0)).toBe(panel.origin);
    expect(alongPx(panel, 1000)).toBeCloseTo(panel.far, 6);
    expect(positionAt(panel, geom, alongPx(panel, 250))).toBe(250);
    // Clamped to the chromosome.
    expect(positionAt(panel, geom, panel.origin - 50)).toBe(0);
    expect(positionAt(panel, geom, panel.far + 50)).toBe(1000);
    expect(pointerAlong(panel, 12, 34)).toBe(12);
  });

  it('draws a wide feature inside the bar and a narrow one as an overhanging tick', () => {
    const wide = spanRect(panel, geom, 100, 600, { overhang: 3 });
    expect(wide.tick).toBe(false);
    expect([wide.y, wide.h]).toEqual([geom.y, geom.h]);
    expect(wide.x).toBeCloseTo(alongPx(panel, 100), 6);
    const narrow = spanRect(panel, geom, 500, 500, { minPx: 2, overhang: 3 });
    expect(narrow.tick).toBe(true);
    expect(narrow.w).toBe(2);
    expect(narrow.h).toBe(geom.h + 6);
    expect(narrow.x + narrow.w / 2).toBeCloseTo(alongPx(panel, 500), 6);
  });

  it('turns vertical spans along y', () => {
    const [vp] = layoutPanels([{ title: null, bars: [bar('chr1', 1000)] }], {
      width: 300,
      height: 300,
      orientation: 'vertical',
    });
    const r = spanRect(vp, vp.bars[0], 0, 500);
    expect(r.x).toBe(vp.bars[0].x);
    expect(r.y).toBe(vp.origin);
    expect(r.h).toBeCloseTo(vp.bars[0].h / 2, 6);
    expect(pointerAlong(vp, 12, 34)).toBe(34);
  });

  it('reads a click as the whole chromosome and a drag as a range', () => {
    const b = bar('chr7', 1000);
    expect(regionFromGesture(b, 400, 402, 10)).toEqual({ chroms: ['chr7'], range: null });
    expect(regionFromGesture(b, 700, 200.4, 10)).toEqual({ chroms: ['chr7'], range: [200, 700] });
    expect(regionFromGesture(b, -50, 5000, 10)).toEqual({ chroms: ['chr7'], range: [0, 1000] });
  });

  it('finds the bar a region names, whatever its prefix', () => {
    expect(barForChrom(panel, '1')?.bar.name).toBe('chr1');
    expect(barForChrom(panel, 'chr9')).toBeNull();
  });
});

describe('sizing and wording', () => {
  it('asks for a row per bar horizontally and a fixed panel vertically', () => {
    const panels = [{ title: 'a', bars: Array.from({ length: 12 }, (_, i) => bar(`c${i}`, 10)) }];
    expect(idealHeight(800, panels, 'horizontal')).toBe(
      GEOMETRY.titleH + GEOMETRY.axisH + 12 * GEOMETRY.minPitch,
    );
    expect(idealHeight(800, [...panels, ...panels, ...panels], 'vertical')).toBe(
      GEOMETRY.verticalPanelH,
    );
    expect(idealHeight(800, [], 'horizontal')).toBe(0);
  });

  it('summarises a feature, a band and a bar', () => {
    expect(
      featureSummary(
        feature({ chrom: 'chr1', start: 1_500_000, end: 1_600_000, label: 'b1', category: 'Complete', sample: 'G1' }),
      ),
    ).toEqual(['b1', 'chr1:1.5 Mb-1.6 Mb', 'Complete', 'G1']);
    expect(featureSummary(feature({ chrom: 'chr1', start: 812, value: 0.5 }), 'density')).toEqual([
      'chr1:812 bp',
      'density 0.5',
    ]);
    const b = bar('chr2', 2_000_000);
    expect(bandSummary(b, { start: 0, end: 1_000_000, value: 3, count: 3 }, false)).toBe(
      'chr2:0 bp-1.0 Mb  ·  3 features',
    );
    expect(bandSummary(b, { start: 0, end: 1_000_000, value: 2.25, count: 3 }, true, 'density')).toBe(
      'chr2:0 bp-1.0 Mb  ·  mean density 2.25',
    );
    expect(barSummary(b, 1)).toBe('chr2  ·  2.0 Mb (to the last feature)  ·  1 feature');
    expect(barSummary({ ...b, source: 'column' }, 4)).toBe('chr2  ·  2.0 Mb  ·  4 features');
  });

  it('formats values compactly and counts features per chromosome', () => {
    expect(formatValue(12345)).toBe('12,345');
    expect(formatValue(0.123456)).toBe('0.123');
    expect(formatValue(1234.6)).toBe('1,235');
    expect(formatValue(Number.NaN)).toBe('');
    const counts = countByChrom([
      feature({ chrom: 'chr1', start: 1 }),
      feature({ chrom: '1', start: 2 }),
      feature({ chrom: 'chr2', start: 2 }),
    ]);
    expect(counts.get('1')).toBe(2);
    expect(counts.get('2')).toBe(1);
  });
});

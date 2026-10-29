import { describe, expect, it } from 'vitest';

import {
  BRUSH_PARAM,
  DATASET_NAME,
  DATA_ASSEMBLY,
  FACET_LANE_HEIGHT,
  FACET_LANE_MAX_HEIGHT,
  GENES_DATASET_NAME,
  GENOME_SCALE_NAME,
  HOVER_COLOR_PARAM,
  PICK_PARAM,
  buildGenomeSpySpec,
  contigsFromRows,
  effectiveMark,
  facetValues,
  facetingEnabled,
  markColourOf,
  resolveColorScale,
  DEFAULT_WINDOW_OPACITY,
  STICKY_AXIS_NAME,
  latchSeedRows,
  regionFromInterval,
  requiredColumns,
  rowsToObjects,
  sortChromosomes,
} from './genomeSpySpec';
import type { GenomeViewConfig } from './genomeSpySpec';
import { sequentialColor } from '../../../categoryColors';

const colors = {
  textColor: 'text',
  gridColor: 'grid',
  ruleColor: 'rule',
  palette: ['c0', 'c1', 'c2'],
};

const rows = {
  chr: ['chr2', 'chr1', 'chrX', 'chr1', null, 'chr10'],
  pos: [100, 50, 7, 900, 1, 5],
  score: [1.5, 2.5, 8.1, 0.2, 3, 4],
  feature: ['a', 'b', 'c', 'd', 'e', 'f'],
};

const base: GenomeViewConfig = { chr_col: 'chr', pos_col: 'pos', score_col: 'score' };

/** The one data lane of a non-faceted spec. */
const lane = (spec: any) => spec.vconcat[0];
/** The data lanes and the gene lane, in order, whether or not the lanes sit in
 *  GenomeSpy's scrolling viewport (stacked lanes always do). */
const stack = (spec: any): any[] =>
  spec.vconcat[0]?.name === 'lanes'
    ? [...spec.vconcat[0].vconcat, ...spec.vconcat.filter((v: any) => v.name === 'annotation')]
    : spec.vconcat;
const marks = (spec: any) => lane(spec).layer[0];

describe('sortChromosomes', () => {
  it('orders numerically, then X/Y/MT, then the rest', () => {
    expect(sortChromosomes(['chrX', 'chr10', 'chr2', 'chrMT', 'scaffold_1', 'chr1', 'chrY'])).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
      'chrY',
      'chrMT',
      'scaffold_1',
    ]);
  });
});

describe('rowsToObjects', () => {
  it('drops rows without a chromosome or position and keeps only the asked columns', () => {
    const out = rowsToObjects(rows, ['chr', 'pos', 'score'], 'chr', 'pos');
    expect(out).toHaveLength(5);
    expect(out[0]).toEqual({ chr: 'chr2', pos: 100, score: 1.5 });
    expect(out.every((r) => !('feature' in r))).toBe(true);
  });
});

describe('contigsFromRows', () => {
  it('sizes each contig past its last position, in natural order', () => {
    const data = rowsToObjects(rows, ['chr', 'pos'], 'chr', 'pos');
    const contigs = contigsFromRows(data, 'chr', 'pos');
    expect(contigs.map((c) => c.name)).toEqual(['chr1', 'chr2', 'chr10', 'chrX']);
    const chr1 = contigs.find((c) => c.name === 'chr1')!;
    expect(chr1.size).toBeGreaterThan(900);
  });

  it('uses the interval end when one is bound', () => {
    const data = [{ chr: 'chr1', start: 10, end: 500 }];
    expect(contigsFromRows(data, 'chr', 'start', 'end')[0].size).toBeGreaterThan(500);
  });
});

describe('latchSeedRows', () => {
  const empty = { chr: [], pos: [], score: [] };
  const unusable = { chr: [null, ''], pos: [1, 2], score: [1, 2] };

  it('empty first rows do not seed contigs', () => {
    expect(latchSeedRows(null, null, 'chr', 'pos')).toBeNull();
    expect(latchSeedRows(null, empty, 'chr', 'pos')).toBeNull();
    // Rows that fail the chromosome / position guard count as no rows.
    expect(latchSeedRows(null, unusable, 'chr', 'pos')).toBeNull();
    // What a seed built from them would have fixed into the spec: no contigs.
    const { spec, contigs } = buildGenomeSpySpec({ rows: empty, config: base, colors });
    expect(contigs).toEqual([]);
    expect((spec as any).genomes[DATA_ASSEMBLY].contigs).toEqual([]);
  });

  it('latches the first non-empty rows and keeps them through a later empty fetch', () => {
    const seed = latchSeedRows(null, rows, 'chr', 'pos');
    expect(seed).toBe(rows);
    const later = { ...rows, chr: ['chr5'], pos: [1], score: [1], feature: ['z'] };
    expect(latchSeedRows(seed, later, 'chr', 'pos')).toBe(rows);
    expect(latchSeedRows(seed, empty, 'chr', 'pos')).toBe(rows);
    expect(latchSeedRows(seed, null, 'chr', 'pos')).toBe(rows);
  });
});

describe('latchSeedRows on a faceted tile', () => {
  const faceted: GenomeViewConfig = { ...base, sample_col: 's', facet_by_sample: true, max_facets: 3 };
  const rowsOf = (samples: string[]) => ({
    chr: samples.map(() => 'chr1'),
    pos: samples.map((_, i) => i + 1),
    score: samples.map(() => 1),
    s: samples,
  });

  it('keeps the seed while the libraries drawn stay the same', () => {
    const seed = rowsOf(['A', 'B']);
    expect(latchSeedRows(seed, rowsOf(['B', 'A', 'B']), 'chr', 'pos', faceted)).toBe(seed);
    expect(latchSeedRows(seed, seed, 'chr', 'pos', faceted)).toBe(seed);
  });

  it('seeds again when a filter narrows or widens the lanes', () => {
    const seed = rowsOf(['A', 'B', 'C']);
    const narrowed = rowsOf(['B']);
    expect(latchSeedRows(seed, narrowed, 'chr', 'pos', faceted)).toBe(narrowed);
    const widened = rowsOf(['A', 'B']);
    expect(latchSeedRows(narrowed, widened, 'chr', 'pos', faceted)).toBe(widened);
    // The lanes of the new seed are the ones the spec draws.
    const built = buildGenomeSpySpec({ rows: narrowed, config: faceted, colors });
    expect(built.facets).toEqual(['B']);
  });

  it('ignores lanes past max_facets and fetches with nothing to draw', () => {
    const seed = rowsOf(['A', 'B', 'C']);
    expect(latchSeedRows(seed, rowsOf(['A', 'B', 'C', 'D']), 'chr', 'pos', faceted)).toBe(seed);
    expect(latchSeedRows(seed, rowsOf([]), 'chr', 'pos', faceted)).toBe(seed);
    expect(latchSeedRows(seed, null, 'chr', 'pos', faceted)).toBe(seed);
  });

  it('never re-seeds a tile that is not faceted', () => {
    const seed = rowsOf(['A']);
    expect(latchSeedRows(seed, rowsOf(['B']), 'chr', 'pos', { ...faceted, facet_by_sample: false })).toBe(seed);
    expect(latchSeedRows(seed, rowsOf(['B']), 'chr', 'pos', null)).toBe(seed);
  });
});

describe('requiredColumns / effectiveMark', () => {
  it('adds every optional column once and never duplicates', () => {
    expect(
      requiredColumns(
        {
          ...base,
          feature_col: 'feature',
          end_col: 'end',
          sample_col: 'sample',
          category_col: 'region',
        },
        'feature',
      ),
    ).toEqual(['chr', 'pos', 'score', 'end', 'feature', 'sample', 'region']);
  });

  it('degrades rect to point without an end column, but keeps bar', () => {
    expect(effectiveMark({ ...base, mark: 'rect' })).toBe('point');
    expect(effectiveMark({ ...base, mark: 'rect', end_col: 'end' })).toBe('rect');
    // A bar is a height from a baseline, which needs no interval to exist.
    expect(effectiveMark({ ...base, mark: 'bar' })).toBe('bar');
  });

  it('draws intervals by default when there is an end column', () => {
    expect(effectiveMark({ ...base, mark: undefined, end_col: 'end' })).toBe('rect');
    expect(effectiveMark({ ...base, mark: undefined })).toBe('point');
  });
});

describe('facetValues / facetingEnabled', () => {
  it('needs both the switch and a bound sample column', () => {
    expect(facetingEnabled({ ...base, facet_by_sample: true })).toBe(false);
    expect(facetingEnabled({ ...base, facet_by_sample: true, sample_col: 's' })).toBe(true);
    expect(facetingEnabled({ ...base, sample_col: 's' })).toBe(false);
  });

  it('sorts samples naturally and reports what max_facets left out', () => {
    const data = [
      { s: 'S10' },
      { s: 'S2' },
      { s: 'S1' },
      { s: 'S2' },
      { s: '' },
      { s: null as unknown as string },
    ];
    expect(facetValues(data, 's', 10)).toEqual({ kept: ['S1', 'S2', 'S10'], dropped: 0 });
    expect(facetValues(data, 's', 2)).toEqual({ kept: ['S1', 'S2'], dropped: 1 });
  });
});

describe('regionFromInterval', () => {
  const contigs = [
    { name: 'chr1', size: 1000 },
    { name: 'chr2', size: 500 },
    { name: 'chr3', size: 200 },
  ];

  it('maps a single-contig interval to a chromosome and a position range', () => {
    expect(regionFromInterval(contigs, [1100, 1300])).toEqual({
      chroms: ['chr2'],
      range: [100, 300],
    });
  });

  it('normalises a backwards drag', () => {
    expect(regionFromInterval(contigs, [1300, 1100])).toEqual({
      chroms: ['chr2'],
      range: [100, 300],
    });
  });

  it('drops the range when the brush spans several contigs', () => {
    expect(regionFromInterval(contigs, [900, 1600])).toEqual({
      chroms: ['chr1', 'chr2', 'chr3'],
      range: null,
    });
  });

  it('returns null for an absent, empty or inverted-to-zero interval', () => {
    expect(regionFromInterval(contigs, null)).toBeNull();
    expect(regionFromInterval(contigs, [5])).toBeNull();
    expect(regionFromInterval(contigs, [100, 100])).toBeNull();
    expect(regionFromInterval(contigs, [9000, 9500])).toBeNull();
  });
});

describe('buildGenomeSpySpec', () => {
  it('shows a crosshair over the lanes and a pointer over marks a click filters on', () => {
    const plain = buildGenomeSpySpec({ rows, config: base, colors }).spec as any;
    expect(plain.vconcat[0].cursor).toBe('crosshair');
    expect(plain.vconcat[0].layer[0].mark.cursor).toBeUndefined();
    const clickable = buildGenomeSpySpec({ rows, config: base, colors, clickable: true }).spec as any;
    expect(clickable.vconcat[0].layer[0].mark.cursor).toBe('pointer');
  });

  it('builds a locus-scaled point track over a data-derived assembly', () => {
    const { spec, contigs, rowCount } = buildGenomeSpySpec({ rows, config: base, colors });
    const s = spec as any;
    expect(s.assembly).toBe(DATA_ASSEMBLY);
    expect(s.genomes[DATA_ASSEMBLY].contigs.map((c: any) => c.name)).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
    ]);
    expect(contigs.map((c) => c.name)).toEqual(['chr1', 'chr2', 'chr10', 'chrX']);
    expect(s.data).toEqual({ name: DATASET_NAME });
    expect(s.datasets[DATASET_NAME]).toHaveLength(5);
    expect(rowCount).toBe(5);
    expect(s.vconcat).toHaveLength(1);
    const track = marks(s);
    expect(track.mark.type).toBe('point');
    expect(track.encoding.x).toMatchObject({ chrom: 'chr', pos: 'pos', type: 'locus' });
    expect(track.encoding.x.scale).toEqual({ name: GENOME_SCALE_NAME });
    expect(track.encoding.x2).toBeUndefined();
    expect(track.encoding.y2).toBeUndefined();
    // The pick param sits on the marks unit view, not on the layer above:
    // GenomeSpy allocates the selection texture from the mark's own view.
    expect(lane(s).params).toBeUndefined();
    expect(track.params.map((p: any) => p.name)).toEqual([PICK_PARAM]);
    // No category, no sample colour: one neutral colour, never one per contig.
    expect(track.encoding.color).toEqual({ value: 'c0' });
  });

  it('wears the track colour of each sample, on a lane or by sample', () => {
    const sampled = { ...rows, s: ['A', 'B', 'A', 'B', 'A', 'B'] };
    const laneColors = { A: '#aa0000' };
    const faceted = buildGenomeSpySpec({
      rows: sampled,
      config: { ...base, sample_col: 's', facet_by_sample: true },
      colors: { ...colors, laneColors, neutral: 'grey' },
    }).spec as any;
    const laneColours = stack(faceted)
      .filter((l: any) => l.name?.startsWith('track'))
      .map((l: any) => l.layer[0].encoding.color);
    expect(laneColours).toEqual([{ value: '#aa0000' }, { value: 'grey' }]);

    const flat = buildGenomeSpySpec({
      rows: sampled,
      config: { ...base, sample_col: 's' },
      colors: { ...colors, laneColors },
    }).spec;
    expect(marks(flat).encoding.color).toMatchObject({
      field: 's',
      scale: { domain: ['A', 'B'], range: ['#aa0000', 'c0'] },
    });
  });

  it('keeps the colours the dashboard pins and cycles the palette for the rest', () => {
    const { spec } = buildGenomeSpySpec({
      rows: { ...rows, cls: ['x', 'y', 'x', 'z', 'y', 'z'] },
      config: { ...base, category_col: 'cls' },
      colors: { ...colors, pinned: { cls: { y: '#123456' } } },
    });
    expect(marks(spec).encoding.color.field).toBe('cls');
    expect(marks(spec).encoding.color.scale).toEqual({
      domain: ['x', 'y', 'z'],
      range: ['c0', '#123456', 'c2'],
    });
  });

  it('declares the region brush once, on the vconcat root', () => {
    const { spec } = buildGenomeSpySpec({ rows, config: base, colors });
    expect((spec as any).params.map((p: any) => p.name)).toEqual([BRUSH_PARAM]);
    expect((spec as any).params[0].select).toEqual({
      type: 'interval',
      encodings: ['x'],
      on: 'mousedown',
    });
  });

  it('hands a plain drag to panning in pan mode, the brush to shift + drag', () => {
    const { spec } = buildGenomeSpySpec({ rows, config: { ...base, drag_mode: 'pan' }, colors });
    expect((spec as any).params[0].select.on).toEqual({ type: 'mousedown', filter: 'event.shiftKey' });
    expect((spec as any).vconcat?.[0]?.cursor ?? (spec as any).cursor).toBe('grab');
  });

  it('takes the brush trigger and the cursor from the interaction mode', () => {
    const built = (config: Partial<GenomeViewConfig>) =>
      buildGenomeSpySpec({ rows, config: { ...base, ...config }, colors }).spec as any;
    const select = built({ interaction_mode: 'select' });
    expect(select.params[0].select.on).toBe('mousedown');
    expect(select.vconcat[0].cursor).toBe('crosshair');
    const pan = built({ interaction_mode: 'pan' });
    expect(pan.params[0].select.on).toEqual({ type: 'mousedown', filter: 'event.shiftKey' });
    expect(pan.vconcat[0].cursor).toBe('grab');
    // The pointer brushes on nothing and leaves the arrow.
    const pointer = built({ interaction_mode: 'pointer' });
    expect(pointer.params[0].select.on).toEqual({ type: 'mousedown', filter: 'false' });
    expect(pointer.vconcat[0].cursor).toBeUndefined();
  });

  it('lets the mode win over the older drag_mode, which still decides without one', () => {
    const built = (config: Partial<GenomeViewConfig>) =>
      buildGenomeSpySpec({ rows, config: { ...base, ...config }, colors }).spec as any;
    expect(built({ drag_mode: 'pan', interaction_mode: 'select' }).params[0].select.on).toBe('mousedown');
    expect(built({ drag_mode: 'pan', interaction_mode: null }).params[0].select.on).toEqual({
      type: 'mousedown',
      filter: 'event.shiftKey',
    });
  });

  it('omits the brush param when the region filter is off', () => {
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...base, region_filter_enabled: false },
      colors,
    });
    expect((spec as any).params).toBeUndefined();
  });

  it('uses a built-in assembly when named and its contigs are supplied', () => {
    const assemblyContigs = [
      { name: 'chr1', size: 248956422 },
      { name: 'chr2', size: 242193529 },
    ];
    const { spec, contigs } = buildGenomeSpySpec({
      rows,
      config: { ...base, assembly: 'hg38' },
      colors,
      assemblyContigs,
    });
    expect((spec as any).assembly).toBe('hg38');
    expect((spec as any).genomes).toBeUndefined();
    expect(contigs).toEqual(assemblyContigs);
  });

  it('derives contigs when a built-in assembly is named but not yet loaded', () => {
    const { spec, contigs } = buildGenomeSpySpec({
      rows,
      config: { ...base, assembly: 'hg38' },
      colors,
    });
    expect((spec as any).assembly).toBe('hg38');
    // The spec still needs a contig list, and the rows are the only source.
    expect((spec as any).genomes[DATA_ASSEMBLY].contigs).toHaveLength(4);
    expect(contigs).toHaveLength(4);
  });

  it('falls back to the data assembly for an unknown assembly name', () => {
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...base, assembly: 'MN908947.3' },
      colors,
    });
    expect((spec as any).assembly).toBe(DATA_ASSEMBLY);
  });

  it('draws intervals when rect and an end column are set', () => {
    const r = { chrom: ['chr1', 'chr1'], start: [10, 60], end: [50, 90], cov: [3, 9] };
    const { spec } = buildGenomeSpySpec({
      rows: r,
      config: { chr_col: 'chrom', pos_col: 'start', score_col: 'cov', end_col: 'end', mark: 'rect' },
      colors,
    });
    const track = marks(spec);
    expect(track.mark.type).toBe('rect');
    expect(track.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
    // A level segment at the score, not a bar from the baseline.
    expect(track.encoding.y2).toEqual({ field: 'cov' });
    expect(track.mark.minHeight).toBe(2);
  });

  it('anchors a bar at the baseline, because GenomeSpy has no area mark', () => {
    const r = { chrom: ['chr1', 'chr1'], start: [10, 60], end: [50, 90], cov: [3, 9] };
    const { spec } = buildGenomeSpySpec({
      rows: r,
      config: { chr_col: 'chrom', pos_col: 'start', score_col: 'cov', end_col: 'end', mark: 'bar' },
      colors,
    });
    const track = marks(spec);
    expect(track.mark.type).toBe('rect');
    expect(track.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
    expect(track.encoding.y2).toEqual({ datum: 0 });
  });

  it('colours by the category column when one is bound', () => {
    const r = {
      chr: ['chr1', 'chr1', 'chr2'],
      pos: [1, 2, 3],
      score: [1, 2, 3],
      region: ['S', 'N', 'S'],
    };
    const { spec } = buildGenomeSpySpec({
      rows: r,
      config: { ...base, category_col: 'region' },
      colors,
    });
    const color = marks(spec).encoding.color;
    expect(color.field).toBe('region');
    expect(color.scale.domain).toEqual(['N', 'S']);
  });

  it('adds the threshold rule only when a threshold is set', () => {
    const withRule = buildGenomeSpySpec({ rows, config: { ...base, score_threshold: 5 }, colors });
    const layers = lane(withRule.spec).layer;
    expect(layers).toHaveLength(2);
    expect(layers[1].mark).toMatchObject({ type: 'rule', color: 'rule' });
    expect(layers[1].encoding.y.datum).toBe(5);
    const without = buildGenomeSpySpec({ rows, config: { ...base, score_threshold: null }, colors });
    expect(lane(without.spec).layer).toHaveLength(1);
  });

  it('carries the selection column into the dataset when selection is on', () => {
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...base, selection_enabled: true, selection_column: 'feature' },
      colors,
    });
    expect((spec as any).datasets[DATASET_NAME][0]).toHaveProperty('feature', 'a');
  });

  describe('per-sample lanes', () => {
    const r = {
      chr: ['chr1', 'chr1', 'chr1', 'chr1'],
      pos: [1, 2, 1, 2],
      score: [5, 6, 7, 8],
      s: ['S1', 'S1', 'S2', 'S2'],
    };
    const faceted: GenomeViewConfig = { ...base, sample_col: 's', facet_by_sample: true };

    it('stacks one filtered lane per sample over one shared dataset', () => {
      const { spec, facets, droppedFacets } = buildGenomeSpySpec({ rows: r, config: faceted, colors });
      const s = spec as any;
      expect(facets).toEqual(['S1', 'S2']);
      expect(droppedFacets).toBe(0);
      const lanes = stack(s);
      expect(lanes).toHaveLength(2);
      expect(lanes[0].transform).toEqual([{ type: 'filter', expr: 'datum["s"] === "S1"' }]);
      expect(lanes[1].transform).toEqual([{ type: 'filter', expr: 'datum["s"] === "S2"' }]);
      // Lane names sit above each lane, horizontal; the score is named once.
      expect(lanes[0].title).toMatchObject({ text: 'S1 | score', orient: 'top' });
      expect(lanes[1].title.text).toBe('S2');
      expect(lanes[1].layer[0].encoding.y.title).toBeNull();
      // Lanes share the tile's height between a floor and a cap, so fullscreen
      // draws them taller and a few lanes in a tall tile do not turn into slabs.
      expect(lanes[0].height).toEqual({ grow: 1, minPx: 26, maxPx: FACET_LANE_MAX_HEIGHT });
      // A set lane height fixes the lanes; they scroll in the same viewport.
      const tall = buildGenomeSpySpec({ rows: r, config: { ...faceted, lane_height: 64 }, colors });
      expect(stack(tall.spec)[1].height).toBe(64);
      // One dataset, N lanes: the rows are not copied per lane.
      expect(Object.keys(s.datasets)).toEqual([DATASET_NAME]);
      expect(s.datasets[DATASET_NAME]).toHaveLength(4);
      // The x scale is shared so every lane pans and zooms together.
      expect(s.resolve.scale.x).toBe('shared');
      expect(s.vconcat[0].resolve).toMatchObject({ scale: { x: 'shared' }, axis: { x: 'shared' } });
    });

    it('shares one y ruler by default and scales each lane with facet_y_scale', () => {
      // The lanes' own viewport resolves their y; the root one stays apart.
      const shared = buildGenomeSpySpec({ rows: r, config: faceted, colors }).spec as any;
      expect(shared.vconcat[0].resolve.scale.y).toBe('shared');
      const own = buildGenomeSpySpec({
        rows: r,
        config: { ...faceted, facet_y_scale: 'independent' },
        colors,
      }).spec as any;
      expect(own.vconcat[0].resolve.scale.y).toBe('independent');
    });

    it('gives every lane its own pick param, because names must be unique', () => {
      const { spec } = buildGenomeSpySpec({ rows: r, config: faceted, colors });
      const names = stack(spec).map((v: any) => v.layer[0].params[0].name);
      expect(names).toEqual([`${PICK_PARAM}_0`, `${PICK_PARAM}_1`]);
      expect(new Set(names).size).toBe(names.length);
    });

    it('caps the lanes at max_facets and reports the remainder', () => {
      const { spec, facets, droppedFacets } = buildGenomeSpySpec({
        rows: r,
        config: { ...faceted, max_facets: 1 },
        colors,
      });
      expect(facets).toEqual(['S1']);
      expect(droppedFacets).toBe(1);
      expect((spec as any).vconcat).toHaveLength(1);
    });

    it('stays a single lane when the sample column is not bound', () => {
      const { spec, facets } = buildGenomeSpySpec({
        rows: r,
        config: { ...base, facet_by_sample: true },
        colors,
      });
      expect(facets).toEqual([]);
      expect((spec as any).vconcat).toHaveLength(1);
    });
  });

  describe('gene annotation lane', () => {
    const genes = [
      { name: 'AAA', chrom: 'chr1', start: 10, end: 200, strand: '+' },
      { name: 'BBB', chrom: 'chr2', start: 5, end: 40, strand: '-' },
      { name: 'CCC', chrom: 'chr99', start: 5, end: 40, strand: '+' },
    ];

    it('appends a lane with its own dataset and a semantic-zoom label layer', () => {
      const { spec, geneCount } = buildGenomeSpySpec({ rows, config: base, colors, genes });
      const s = spec as any;
      // chr99 is not a contig in view, so its gene is dropped.
      expect(geneCount).toBe(2);
      expect(s.vconcat).toHaveLength(2);
      const annotation = s.vconcat[1];
      expect(annotation.name).toBe('annotation');
      expect(annotation.data).toEqual({ name: GENES_DATASET_NAME });
      expect(s.datasets[GENES_DATASET_NAME]).toHaveLength(2);
      const [rect, labels] = annotation.layer;
      expect(rect.mark.type).toBe('rect');
      expect(rect.encoding.x).toMatchObject({ chrom: 'chrom', pos: 'start', type: 'locus' });
      expect(rect.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
      // Constant positional values are normalised within the lane, so the lane
      // resolves no y scale against the data tracks' score axis.
      expect(rect.encoding.y).toEqual({ value: 0.3 });
      expect(labels.mark.type).toBe('text');
      expect(labels.opacity).toMatchObject({ values: [0, 1] });
    });

    it('draws no lane without genes', () => {
      const { spec, geneCount } = buildGenomeSpySpec({ rows, config: base, colors, genes: [] });
      expect(geneCount).toBe(0);
      expect((spec as any).vconcat).toHaveLength(1);
      expect((spec as any).datasets[GENES_DATASET_NAME]).toBeUndefined();
    });

    it('sits under every sample lane, not inside one', () => {
      const r = { chr: ['chr1', 'chr1'], pos: [1, 2], score: [5, 6], s: ['S1', 'S2'] };
      const { spec } = buildGenomeSpySpec({
        rows: r,
        config: { ...base, sample_col: 's', facet_by_sample: true },
        colors,
        genes,
      });
      const names = stack(spec).map((v: any) => v.name);
      expect(names).toEqual(['track_0', 'track_1', 'annotation']);
    });
  });
});

describe('color_scale', () => {
  const sampled = {
    chr: ['chr1', 'chr1', 'chr1', 'chr1'],
    pos: [1, 2, 3, 4],
    score: [1, 2, 3, 4],
    tp: ['late', 'early', 'mid', 'early'],
    day: [14, 0, 3, 0],
  };
  const cfg: GenomeViewConfig = {
    chr_col: 'chr',
    pos_col: 'pos',
    score_col: 'score',
    color_scale: { column: 'tp', order_by: 'day', scheme: 'blues' },
  };
  const marksOf = (spec: any) => spec.vconcat[0].layer[0];

  it('asks for the scale column and its order column', () => {
    expect(requiredColumns(cfg)).toEqual(['chr', 'pos', 'score', 'tp', 'day']);
  });

  it('resolves the colour of each value along the ramp, in the order of order_by', () => {
    const data = [
      { tp: 'late', day: 14 },
      { tp: 'early', day: 0 },
      { tp: 'mid', day: 3 },
    ];
    const resolved = resolveColorScale(data, cfg.color_scale);
    expect(resolved?.domain).toEqual(['early', 'mid', 'late']);
    expect(resolved?.colours).toEqual({
      early: sequentialColor('blues', 0),
      mid: sequentialColor('blues', 0.5),
      late: sequentialColor('blues', 1),
    });
    expect(resolveColorScale([], cfg.color_scale)).toBeNull();
    expect(resolveColorScale(data, null)).toBeNull();
  });

  it('colours the marks by the scale column with the ramp as the range', () => {
    const { spec } = buildGenomeSpySpec({ rows: sampled, config: cfg, colors });
    expect(marksOf(spec).encoding.color).toMatchObject({
      field: 'tp',
      scale: {
        domain: ['early', 'mid', 'late'],
        range: [sequentialColor('blues', 0), sequentialColor('blues', 0.5), sequentialColor('blues', 1)],
      },
    });
  });

  it('lets the genome browser colour of a value win over the ramp', () => {
    const { spec } = buildGenomeSpySpec({
      rows: sampled,
      config: cfg,
      colors: { ...colors, groupColors: { mid: '#123456' } },
    });
    expect(marksOf(spec).encoding.color.scale.range[1]).toBe('#123456');
  });

  it('gives a lane of the sample column the sample colour of the scale', () => {
    const { spec } = buildGenomeSpySpec({
      rows: { ...sampled, s: ['late', 'early', 'mid', 'early'] },
      config: { ...cfg, color_scale: { column: 's', scheme: 'viridis' }, sample_col: 's', facet_by_sample: true },
      colors: { ...colors, laneColors: { mid: '#abcdef' } },
    });
    const lanes = stack(spec)
      .filter((l: any) => l.name?.startsWith('track'))
      .map((l: any) => l.layer[0].encoding.color);
    // Sorted naturally: early, late, mid. The browser's colour for mid wins.
    expect(lanes).toEqual([
      { value: sequentialColor('viridis', 0) },
      { value: sequentialColor('viridis', 0.5) },
      { value: '#abcdef' },
    ]);
  });
});

describe('group colours of the genome browser', () => {
  const cat = {
    chr: ['chr1', 'chr1', 'chr1'],
    pos: [1, 2, 3],
    score: [1, 2, 3],
    cls: ['x', 'y', 'z'],
  };
  const cfg: GenomeViewConfig = { ...base, category_col: 'cls' };

  it('colours a category the browser colours, under the dashboard pins', () => {
    const { spec } = buildGenomeSpySpec({
      rows: cat,
      config: cfg,
      colors: { ...colors, groupColors: { x: '#111111', y: '#222222' }, pinned: { cls: { y: '#999999' } } },
    });
    expect((spec as any).vconcat[0].layer[0].encoding.color.scale.range).toEqual([
      '#111111',
      '#999999',
      'c2',
    ]);
  });

  it('reports the colour of a hovered mark, null for the neutral one', () => {
    const { colorOf } = buildGenomeSpySpec({
      rows: cat,
      config: cfg,
      colors: { ...colors, groupColors: { x: '#111111' } },
    });
    expect(colorOf({ cls: 'x' })).toBe('#111111');
    expect(colorOf({ cls: 'y' })).toBe('c1');
    expect(colorOf({ cls: null })).toBeNull();
    expect(colorOf({ cls: 'unseen' })).toBeNull();
  });

  it('reports the sample colour of a mark without categories, as a lane wears it', () => {
    const of = markColourOf(
      { ...base, sample_col: 's' },
      { ...colors, laneColors: { A: '#aa0000' } },
      [],
    );
    expect(of({ s: 'A' })).toBe('#aa0000');
    expect(of({ s: 'B' })).toBeNull();
  });
});

describe('the overlays of a lane', () => {
  const lane0 = (overlay: any) =>
    (buildGenomeSpySpec({ rows, config: base, colors: { ...colors, overlay } }).spec as any).vconcat[0].layer;

  it('fills the window band clearly, from the theme when it says', () => {
    const band = lane0({ windowColor: 'w', hoverColor: 'h' }).find((l: any) => l.name === 'track-window');
    expect(band.mark.opacity).toBe(DEFAULT_WINDOW_OPACITY);
    expect(DEFAULT_WINDOW_OPACITY).toBeGreaterThan(0.1);
    expect(DEFAULT_WINDOW_OPACITY).toBeLessThan(0.3);
    const dark = lane0({ windowColor: 'w', hoverColor: 'h', windowOpacity: 0.24 }).find(
      (l: any) => l.name === 'track-window',
    );
    expect(dark.mark.opacity).toBe(0.24);
  });

  it('draws the hover rule in the colour of a param, the renderer setting it from the hovering tile', () => {
    const hover = lane0({ windowColor: 'w', hoverColor: 'h' }).find((l: any) => l.name === 'track-hover');
    expect(hover.mark.color).toEqual({ expr: HOVER_COLOR_PARAM });
    expect(hover.encoding.color).toBeUndefined();
  });
});

describe('the hover rule next to a coloured mark', () => {
  // GenomeSpy 0.88: a `scale: null` colour channel has no range for the WebGL
  // range texture ("o.range is not a function"), and merged into the marks'
  // colour scale it throws "Cannot merge objects with nulls!" (the embed never
  // builds). The rule's colour must not be a colour channel at all.
  const coloured: GenomeViewConfig = { ...base, category_col: 'feature' };
  const overlay = { windowColor: 'w', hoverColor: 'h' };

  it('takes its colour from a param, with no colour channel of its own', () => {
    const built = buildGenomeSpySpec({ rows, config: coloured, colors: { ...colors, overlay } });
    const lane0 = (built.spec as any).vconcat[0];
    const hover = lane0.layer.find((l: any) => l.name === 'track-hover');
    expect(lane0.layer[0].encoding.color.scale).toBeTruthy();
    expect(hover.encoding.color).toBeUndefined();
    expect(hover.mark.color).toEqual({ expr: HOVER_COLOR_PARAM });
    expect((built.spec as any).params).toContainEqual({ name: HOVER_COLOR_PARAM, value: 'h' });
  });

  it('keeps the brush param next to it', () => {
    const built = buildGenomeSpySpec({ rows, config: coloured, colors: { ...colors, overlay } });
    const names = ((built.spec as any).params as any[]).map((p) => p.name);
    expect(names).toEqual([BRUSH_PARAM, HOVER_COLOR_PARAM]);
  });

  it('declares no param without overlays', () => {
    const built = buildGenomeSpySpec({ rows, config: coloured, colors });
    expect(((built.spec as any).params as any[]).map((p) => p.name)).toEqual([BRUSH_PARAM]);
  });
});

describe('the sticky genome axis of scrolling lanes', () => {
  const sampled = { ...rows, s: ['A', 'B', 'A', 'B', 'A', 'B'] };
  const faceted: GenomeViewConfig = { ...base, sample_col: 's', facet_by_sample: true };
  const genes = [{ name: 'G', chrom: 'chr1', start: 1, end: 100, strand: '+' }];

  it('fits the lanes to the tile between a floor and a cap, the axis still sticky (no lane_height)', () => {
    const built = buildGenomeSpySpec({ rows: sampled, config: faceted, colors });
    expect(built.scrolls).toBe(true);
    const spec = built.spec as any;
    expect(spec.vconcat.map((v: any) => v.name)).toEqual(['lanes', STICKY_AXIS_NAME]);
    const lanes = spec.vconcat[0].vconcat;
    expect(lanes.map((l: any) => l.name)).toEqual(['track_0', 'track_1']);
    // Lanes that fit the tile fill it; lanes that do not scroll in the viewport.
    expect(lanes[0].height).toEqual({ grow: 1, minPx: FACET_LANE_HEIGHT, maxPx: FACET_LANE_MAX_HEIGHT });
    expect(spec.vconcat[0].viewportHeight).toEqual({ grow: 1 });
    expect(spec.resolve.axis.x).toBe('independent');
    expect(lanes[0].layer[0].encoding.x.axis).toMatchObject({ chromGrid: true, labels: false });
  });

  it('puts fixed lanes in a scrolling viewport with an axis view of its own', () => {
    const built = buildGenomeSpySpec({
      rows: sampled,
      config: { ...faceted, lane_height: 60, facet_y_scale: 'independent' },
      colors,
      genes,
    });
    expect(built.scrolls).toBe(true);
    const spec = built.spec as any;
    expect(spec.vconcat.map((v: any) => v.name)).toEqual(['lanes', 'annotation', STICKY_AXIS_NAME]);
    const [lanes, annotation, axis] = spec.vconcat;
    expect(lanes.viewportHeight).toEqual({ grow: 1 });
    expect(lanes.vconcat.map((l: any) => l.name)).toEqual(['track_0', 'track_1']);
    expect(lanes.resolve.scale.y).toBe('independent');
    // The lanes keep the chromosome grid and draw no axis of their own.
    const x = lanes.vconcat[0].layer[0].encoding.x;
    expect(x.axis).toMatchObject({ chromGrid: true, labels: false, ticks: false, domain: false });
    expect(annotation.layer[0].encoding.x.axis).toBeNull();
    // One scale shared by the lanes and the axis view, which draws the axis.
    expect(axis.encoding.x.scale.name).toBe(GENOME_SCALE_NAME);
    expect(axis.encoding.x.axis.title).toBeNull();
    expect(spec.resolve.axis.x).toBe('independent');
  });

  it('does not nest a single lane or an unfaceted tile', () => {
    expect(buildGenomeSpySpec({ rows, config: { ...base, lane_height: 60 }, colors }).scrolls).toBe(false);
    expect(buildGenomeSpySpec({ rows, config: base, colors }).scrolls).toBe(false);
  });
});

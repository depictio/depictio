import { describe, expect, it } from 'vitest';

import { DATA_ASSEMBLY, GENES_DATASET_NAME, GENOME_SCALE_NAME } from '../genomespy/genomeSpySpec';
import {
  buildSashimiGenomeSpySpec,
  COVERAGE_DATASET,
  coverageData,
  EXONS_DATASET,
  JUNCTIONS_DATASET,
  junctionData,
  sashimiContigs,
  UNANNOTATED,
} from './sashimiGenomeSpySpec';
import type { BuildSashimiSpecInput } from './sashimiGenomeSpySpec';

const junctions = junctionData([
  { chrom: 'chr12', start: 1000, end: 5000, count: 180, lane: 'CTRL', annotation: 'known' },
  { chrom: 'chr12', start: 1000, end: 9000, count: 0, lane: 'KD', annotation: null },
]);
const coverage = coverageData(
  { chromosome: ['chr12', 'chr12', ''], position: [900, 950, 1], depth: [10, 12, 3], end: [950, 1000, 2], sample: ['CTRL', 'KD', 'KD'] },
  { chr: 'chromosome', pos: 'position', value: 'depth', end: 'end', sample: 'sample' },
  '(all)',
  false,
);

function input(overrides: Partial<BuildSashimiSpecInput> = {}): BuildSashimiSpecInput {
  return {
    lanes: ['CTRL', 'KD'],
    annotations: ['known', UNANNOTATED],
    colorBy: 'annotation',
    laneColours: ['c0', 'c1'],
    annotationColours: ['a0', 'a1'],
    colors: { textColor: 't', gridColor: 'g', ruleColor: 'r', palette: ['p0', 'p1'] },
    contigs: sashimiContigs(junctions, coverage),
    assembly: null,
    initialRegion: { chrom: 'chr12', start: 800, end: 9500 },
    junctions,
    coverage,
    coverageShared: false,
    coverageTitle: 'depth',
    exons: [{ chrom: 'chr12', start: 5000, end: 5200, terminal: false }],
    genes: null,
    logWidth: true,
    maxArcWidth: 2,
    showCounts: true,
    ...overrides,
  };
}

type View = Record<string, any>;

describe('junction and coverage shaping', () => {
  it('keeps a log-safe width and names unannotated junctions', () => {
    expect(junctions[1].width).toBe(1);
    expect(junctions[1].annotation).toBe(UNANNOTATED);
  });
  it('drops rows with no chromosome and keeps bin ends', () => {
    expect(coverage).toHaveLength(2);
    expect(coverage[0]).toMatchObject({ pos: 900, end: 950, lane: 'CTRL' });
  });
  it('compresses depth when asked', () => {
    const logged = coverageData({ c: ['chr1'], p: [1], v: [99] }, { chr: 'c', pos: 'p', value: 'v' }, 'x', true);
    expect(logged[0].value).toBeCloseTo(2);
    expect(logged[0].lane).toBe('x');
  });
});

describe('buildSashimiGenomeSpySpec', () => {
  it('draws one lane per sample plus the exon model, with dome links sized by count', () => {
    const { spec } = buildSashimiGenomeSpySpec(input());
    const lanes = spec.vconcat as View[];
    expect(lanes.map((l) => l.name)).toEqual(['lane_0', 'lane_1', 'exon_model']);
    const [cov, group] = lanes[0].layer as View[];
    expect(cov.data).toEqual({ name: COVERAGE_DATASET });
    expect(cov.transform[0].expr).toBe('datum.lane === "CTRL"');
    expect(group.transform[0].expr).toBe('datum.lane === "CTRL"');
    // Domes and apex labels share one y scale: it lives on the group.
    expect(group.encoding.y).toMatchObject({ field: 'count', axis: null });
    const [arcs, headroom, counts] = group.layer as View[];
    expect(headroom.encoding.y.field).toBe('headroom');
    expect(arcs.mark).toMatchObject({ type: 'link', linkShape: 'dome', orient: 'vertical' });
    expect(arcs.encoding.y2).toEqual({ datum: 0 });
    expect(arcs.encoding.size.scale).toEqual({ type: 'log', range: [1, 4] });
    expect(arcs.encoding.color.scale).toEqual({ domain: ['known', UNANNOTATED], range: ['a0', 'a1'] });
    expect(counts.mark.type).toBe('text');
    expect(lanes[0].title.text).toBe('CTRL');
  });

  it('carries every dataset and opens on the requested window', () => {
    const { spec } = buildSashimiGenomeSpySpec(input());
    const datasets = spec.datasets as Record<string, unknown[]>;
    expect(Object.keys(datasets).sort()).toEqual([COVERAGE_DATASET, EXONS_DATASET, JUNCTIONS_DATASET].sort());
    expect(spec.assembly).toBe(DATA_ASSEMBLY);
    const x = (spec.encoding as View).x;
    expect(x.scale).toEqual({
      name: GENOME_SCALE_NAME,
      domain: [
        { chrom: 'chr12', pos: 800 },
        { chrom: 'chr12', pos: 9500 },
      ],
    });
  });

  it('omits the coverage layer when none is bound and the lane filter when it is shared', () => {
    const none = buildSashimiGenomeSpySpec(input({ coverage: null })).spec;
    expect(((none.vconcat as View[])[0].layer as View[])[0].name).toBe('junctions_0');
    expect((none.datasets as View)[COVERAGE_DATASET]).toBeUndefined();
    const shared = buildSashimiGenomeSpySpec(input({ coverageShared: true })).spec;
    const cov = ((shared.vconcat as View[])[0].layer as View[])[0];
    expect(cov.transform).toBeUndefined();
    expect(cov.encoding.color).toEqual({ value: 'g' });
  });

  it('colours arcs per lane when asked and hides counts when off', () => {
    const { spec } = buildSashimiGenomeSpySpec(input({ colorBy: 'sample', showCounts: false, logWidth: false }));
    const layers = (spec.vconcat as View[])[1].layer as View[];
    expect(layers).toHaveLength(2);
    const domes = layers[1].layer as View[];
    expect(domes).toHaveLength(1);
    expect(domes[0].encoding.color.field).toBe('lane');
    expect(domes[0].encoding.size.scale.type).toBe('linear');
  });

  it('uses a built-in assembly and adds a gene lane cut to the axis', () => {
    const built = buildSashimiGenomeSpySpec(
      input({
        assembly: 'hg38',
        contigs: [{ name: 'chr12', size: 133_275_309 }],
        genes: [
          { name: 'CHD4', chrom: 'chr12', start: 900, end: 9800, strand: '-' },
          { name: 'TP53', chrom: 'chr17', start: 1, end: 2, strand: '-' },
        ],
      }),
    );
    expect(built.geneCount).toBe(1);
    expect(built.spec.assembly).toBe('hg38');
    expect(built.spec.genomes).toBeUndefined();
    const lanes = built.spec.vconcat as View[];
    expect(lanes[lanes.length - 1].name).toBe('genes');
    const genes = (built.spec.datasets as Record<string, View[]>)[GENES_DATASET_NAME];
    expect(genes[0].label).toBe('CHD4 (-)');
  });

  it('leaves the lane title off a single unnamed lane', () => {
    const { spec } = buildSashimiGenomeSpySpec(input({ lanes: ['(all)'], laneColours: ['c0'] }));
    expect((spec.vconcat as View[])[0].title).toBeUndefined();
  });
});

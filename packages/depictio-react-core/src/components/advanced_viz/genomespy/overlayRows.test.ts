import { describe, expect, it } from 'vitest';

import {
  GENOME_SCALE_NAME,
  HOVER_COLOR_PARAM,
  HOVER_SOURCE,
  SELECTION_SOURCE,
  WINDOW_SOURCE,
  buildGenomeSpySpec,
  overlaySourceNames,
} from './genomeSpySpec';
import type { Contig, GenomeViewConfig } from './genomeSpySpec';
import {
  compactRegion,
  fallbackBoxes,
  followWindowTarget,
  frameWindow,
  fractionOfDomain,
  hoverRows,
  paddedRegion,
  selectionRows,
  toLinear,
  windowInDomain,
  windowIsRegion,
  windowRows,
} from './overlayRows';

const contigs: Contig[] = [
  { name: 'chr1', size: 1000 },
  { name: 'chr2', size: 500 },
];
const names = contigs.map((c) => c.name);

describe('windowRows', () => {
  it('is one band on the matched contig', () => {
    expect(windowRows({ entity: 'chr2', start: 10, end: 90 }, names)).toEqual([
      { chrom: 'chr2', start: 10, end: 90 },
    ]);
  });
  it('maps the browser\'s spelling onto the view\'s contig name', () => {
    expect(windowRows({ entity: '1', start: 5, end: 50 }, names)).toEqual([
      { chrom: 'chr1', start: 5, end: 50 },
    ]);
    expect(
      windowRows({ entity: 'NC_2', entityAliases: ['chr2'], start: 5, end: 50 }, names),
    ).toEqual([{ chrom: 'chr2', start: 5, end: 50 }]);
  });
  it('is empty for no window, an unknown contig or no extent', () => {
    expect(windowRows(null, names)).toEqual([]);
    expect(windowRows({ entity: 'chr9', start: 1, end: 9 }, names)).toEqual([]);
    expect(windowRows({ entity: 'chr1', start: 9, end: 9 }, names)).toEqual([]);
  });
});

describe('hoverRows', () => {
  it('is one rule at a position and two at a span', () => {
    expect(hoverRows({ refName: 'chr1', start: 40, end: 40 }, names)).toEqual([
      { chrom: 'chr1', pos: 40 },
    ]);
    expect(hoverRows({ refName: 'chr1', start: 40, end: 60 }, names)).toEqual([
      { chrom: 'chr1', pos: 40 },
      { chrom: 'chr1', pos: 60 },
    ]);
  });
  it('is empty off the view\'s contigs', () => {
    expect(hoverRows({ refName: 'chrM', start: 1, end: 1 }, names)).toEqual([]);
    expect(hoverRows(null, names)).toEqual([]);
  });
});

describe('the DOM fallback geometry', () => {
  it('lays contigs end to end', () => {
    expect(toLinear(contigs, 'chr1', 10)).toBe(10);
    expect(toLinear(contigs, 'chr2', 10)).toBe(1010);
    expect(toLinear(contigs, 'chrZ', 10)).toBeNull();
  });
  it('places a position across the visible domain', () => {
    expect(fractionOfDomain(150, [100, 200])).toBe(0.5);
    expect(fractionOfDomain(150, [200, 100])).toBeNull();
  });
  it('clips boxes to the plot and drops what is off screen', () => {
    const boxes = fallbackBoxes(
      contigs,
      [0, 1500],
      [{ chrom: 'chr2', start: 0, end: 500 }],
      [{ chrom: 'chr1', pos: 750 }],
    );
    expect(boxes[0]).toMatchObject({ kind: 'window', left: 1000 / 1500 });
    expect(boxes[0].width).toBeCloseTo(500 / 1500);
    expect(boxes[1]).toMatchObject({ kind: 'hover', left: 0.5 });
    expect(
      fallbackBoxes(contigs, [0, 100], [{ chrom: 'chr2', start: 0, end: 5 }], [{ chrom: 'chr1', pos: 750 }]),
    ).toEqual([]);
    expect(fallbackBoxes(contigs, null, [], [{ chrom: 'chr1', pos: 1 }])).toEqual([]);
  });
});

describe('the overlay layers in the spec', () => {
  const base: GenomeViewConfig = { chr_col: 'chr', pos_col: 'pos', score_col: 'score' };
  const rows = { chr: ['chr1', 'chr2'], pos: [10, 20], score: [1, 2], sample: ['S1', 'S2'] };
  const colors = {
    textColor: 'text',
    gridColor: 'grid',
    ruleColor: 'rule',
    palette: ['c0'],
    overlay: { windowColor: 'win-colour', hoverColor: 'hover-colour' },
  };

  it('adds the selection, the window and a rule on named sources, coloured from the theme', () => {
    const { spec, overlays } = buildGenomeSpySpec({ rows, config: base, colors });
    const layers = (spec as any).vconcat[0].layer;
    const byName = (n: string) => layers.find((l: any) => l.name === `track-${n}`);
    // Marks first, the hover rule last (on top of everything).
    expect(layers[0].name).toBe('track-marks');
    expect(layers[layers.length - 1].name).toBe('track-hover');

    const win = byName('window');
    expect(win.data).toEqual({ name: WINDOW_SOURCE });
    expect(win.mark).toMatchObject({ type: 'rect', color: 'win-colour' });
    expect(win.mark.opacity).toBeLessThan(0.5);
    expect(win.encoding.x).toMatchObject({ chrom: 'chrom', pos: 'start', type: 'locus' });
    expect(win.encoding.x.scale.name).toBe(GENOME_SCALE_NAME);
    expect(win.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
    // The window's edges are dashed, the selection's solid.
    expect(byName('window-start').mark.strokeDash).toEqual([5, 4]);
    expect(byName('window-end').encoding.x.pos).toBe('end');
    expect(byName('selection-start').mark.strokeDash).toBeUndefined();

    // Only the region's edges: nothing veils the rest of its contig.
    expect(layers.some((l: any) => String(l.name).endsWith('selection-out'))).toBe(false);
    expect(byName('selection-start').data).toEqual({ name: SELECTION_SOURCE });
    expect(byName('selection-label').encoding.text).toEqual({ field: 'label' });
    expect(byName('window-label').mark.align).toBe('right');

    const hover = byName('hover');
    expect(hover.data).toEqual({ name: HOVER_SOURCE });
    expect(hover.mark).toMatchObject({ type: 'rule', color: { expr: HOVER_COLOR_PARAM } });
    expect((spec as any).params).toContainEqual({ name: HOVER_COLOR_PARAM, value: 'hover-colour' });
    expect(hover.encoding.x.pos).toBe('pos');
    expect(overlays).toEqual([overlaySourceNames(0)]);
    expect((spec as any).datasets[WINDOW_SOURCE]).toEqual([]);
    expect((spec as any).datasets[SELECTION_SOURCE]).toEqual([]);
  });

  it('keeps the marks layer first and brush-free', () => {
    const { spec } = buildGenomeSpySpec({ rows, config: base, colors });
    const s = spec as any;
    expect(s.vconcat[0].layer[0].params).toBeDefined();
    // Brush plus the hover colour param; nothing that selects or filters.
    expect(s.params.map((p: any) => p.name)).toEqual(['brush', HOVER_COLOR_PARAM]);
  });

  it('gives each faceted lane its own pair of source names', () => {
    const { spec, overlays } = buildGenomeSpySpec({
      rows,
      config: { ...base, sample_col: 'sample', facet_by_sample: true },
      colors,
    });
    expect(overlays.map((o) => o.window)).toEqual([WINDOW_SOURCE, `${WINDOW_SOURCE}_1`]);
    const lanes = (spec as any).vconcat[0].vconcat;
    const used = lanes.map(
      (l: any) => l.layer.find((x: any) => x.name.endsWith('-window')).data.name,
    );
    expect(new Set(used).size).toBe(2);
    // Only the first lane names the overlays.
    const labels = lanes.map(
      (l: any) => l.layer.filter((x: any) => x.mark.type === 'text').length,
    );
    expect(labels).toEqual([2, 0]);
  });

  it('adds nothing without overlay colours', () => {
    const { spec, overlays } = buildGenomeSpySpec({
      rows,
      config: base,
      colors: { ...colors, overlay: undefined },
    });
    expect((spec as any).vconcat[0].layer).toHaveLength(1);
    expect(overlays).toEqual([]);
    expect(Object.keys((spec as any).datasets)).toEqual(['rows']);
  });
});

describe('windowIsRegion', () => {
  const region = { chrom: 'chr6', start: 26_000_000, end: 26_300_000 };
  it('matches the browser window on the tile region, within the tolerance', () => {
    expect(windowIsRegion([{ chrom: 'chr6', start: 26_000_017, end: 26_300_017 }], region)).toBe(true);
    expect(windowIsRegion([{ chrom: '6', start: 26_000_000, end: 26_300_000 }], region)).toBe(true);
  });
  it('keeps the band for another window, no region, or a whole contig', () => {
    expect(windowIsRegion([{ chrom: 'chr6', start: 26_100_000, end: 26_150_000 }], region)).toBe(false);
    expect(windowIsRegion([{ chrom: 'chr7', start: 26_000_000, end: 26_300_000 }], region)).toBe(false);
    expect(windowIsRegion([{ chrom: 'chr6', start: 0, end: 10 }], null)).toBe(false);
    expect(
      windowIsRegion([{ chrom: 'chr6', start: 0, end: 10 }], { chrom: 'chr6', start: 0, end: Infinity }),
    ).toBe(false);
  });
});

describe('paddedRegion', () => {
  it('widens a region by the pad on each side, within its contig', () => {
    expect(paddedRegion({ chrom: 'chr1', start: 100, end: 200 }, 1000, 0.15)).toEqual({
      chrom: 'chr1',
      start: 85,
      end: 215,
    });
    expect(paddedRegion({ chrom: 'chr1', start: 10, end: 990 }, 1000, 0.15)).toEqual({
      chrom: 'chr1',
      start: 0,
      end: 1000,
    });
  });
  it('only clamps at 0 when the contig size is unknown', () => {
    expect(paddedRegion({ chrom: 'chr1', start: 0, end: 100 }, null, 0.5)).toEqual({
      chrom: 'chr1',
      start: 0,
      end: 150,
    });
  });
  it('leaves an open-ended region as it is', () => {
    const whole = { chrom: 'chr1', start: 0, end: Infinity };
    expect(paddedRegion(whole, 1000)).toBe(whole);
  });
});

describe('compactRegion', () => {
  it('reads in the unit the span reads best in', () => {
    expect(compactRegion('chr6', 26_000_017, 26_300_017)).toBe('chr6:26.00-26.30 Mb');
    expect(compactRegion('chr6', 18_200_000, 46_000_000)).toBe('chr6:18.2-46.0 Mb');
    expect(compactRegion('chr1', 12_000, 52_000)).toBe('chr1:12.0-52.0 kb');
    expect(compactRegion('chr1', 100, 900)).toBe('chr1:100-900 bp');
  });
  it('is the bare contig for an open end', () => {
    expect(compactRegion('chr1', 0, Infinity)).toBe('chr1');
  });
});

describe('selectionRows', () => {
  it('frames the region only, on the drawn contig name', () => {
    expect(selectionRows({ chrom: '1', start: 100, end: 200 }, contigs, 'Filter x')).toEqual([
      { chrom: 'chr1', start: 100, end: 200, label: 'Filter x' },
    ]);
  });
  it('is empty with no region, an open end or an unknown contig', () => {
    expect(selectionRows(null, contigs)).toEqual([]);
    expect(selectionRows({ chrom: 'chr1', start: 0, end: Infinity }, contigs)).toEqual([]);
    expect(selectionRows({ chrom: 'chrM', start: 1, end: 9 }, contigs)).toEqual([]);
  });
});

describe('windowInDomain', () => {
  const names = ['chr1', 'chr2', 'chr3'];
  const dom = (a: [string, number], b: [string, number]) => [
    { chrom: a[0], pos: a[1] },
    { chrom: b[0], pos: b[1] },
  ];

  it('holds for a window inside the domain, on one contig or across several', () => {
    expect(windowInDomain(dom(['chr2', 0], ['chr2', 500]), { chrom: 'chr2', start: 100, end: 200 }, names)).toBe(true);
    expect(windowInDomain(dom(['chr1', 900], ['chr3', 10]), { chrom: 'chr2', start: 0, end: 50 }, names)).toBe(true);
  });

  it('fails for a window past either edge or on another contig', () => {
    const d = dom(['chr2', 100], ['chr2', 500]);
    expect(windowInDomain(d, { chrom: 'chr2', start: 50, end: 200 }, names)).toBe(false);
    expect(windowInDomain(d, { chrom: 'chr2', start: 400, end: 600 }, names)).toBe(false);
    expect(windowInDomain(d, { chrom: 'chr3', start: 0, end: 10 }, names)).toBe(false);
  });

  it('holds when the domain or a contig cannot be read, so nothing moves', () => {
    expect(windowInDomain(null, { chrom: 'chr2', start: 0, end: 1 }, names)).toBe(true);
    expect(windowInDomain(dom(['chr2', 0], ['chr2', 9]), { chrom: 'chrZ', start: 0, end: 1 }, names)).toBe(true);
  });
});

describe('the hover rule colour', () => {
  it('wears the colour of the tile that hovered, else the fallback', () => {
    expect(hoverRows({ refName: 'chr1', start: 40, end: 60 }, names, '#ff0000', '#000000')).toEqual([
      { chrom: 'chr1', pos: 40, color: '#ff0000' },
      { chrom: 'chr1', pos: 60, color: '#ff0000' },
    ]);
    expect(hoverRows({ refName: 'chr1', start: 40, end: 40 }, names, null, '#000000')).toEqual([
      { chrom: 'chr1', pos: 40, color: '#000000' },
    ]);
  });
  it('carries it into the DOM fallback boxes', () => {
    const boxes = fallbackBoxes(contigs, [0, 1000], [], [{ chrom: 'chr1', pos: 500, color: '#ff0000' }]);
    expect(boxes).toEqual([expect.objectContaining({ kind: 'hover', color: '#ff0000' })]);
  });
});

describe('windowInDomain tolerance', () => {
  const names3 = ['chr1', 'chr2'];
  const dom = [
    { chrom: 'chr1', pos: 1000 },
    { chrom: 'chr1', pos: 5000 },
  ];
  it('takes a window a hair past the edge as the same window coming back', () => {
    expect(windowInDomain(dom, { chrom: 'chr1', start: 998, end: 5001 }, names3)).toBe(true);
    expect(windowInDomain(dom, { chrom: 'chr1', start: 1000 - 50, end: 5000 + 50 }, names3)).toBe(true);
  });
  it('still fails for a window that really left', () => {
    expect(windowInDomain(dom, { chrom: 'chr1', start: 800, end: 4000 }, names3)).toBe(false);
    expect(windowInDomain(dom, { chrom: 'chr1', start: 4000, end: 6000 }, names3)).toBe(false);
  });
});

describe('frameWindow', () => {
  it('centres the window at three times its width', () => {
    expect(frameWindow({ chrom: 'chr1', start: 4000, end: 5000 })).toEqual({
      chrom: 'chr1',
      start: 3000,
      end: 6000,
    });
  });
  it('keeps a floor under a tiny window and stays inside the contig', () => {
    expect(frameWindow({ chrom: 'chr1', start: 10, end: 11 }, 5000)).toEqual({
      chrom: 'chr1',
      start: 0,
      end: 1000,
    });
    expect(frameWindow({ chrom: 'chr1', start: 4990, end: 5000 }, 5000)).toEqual({
      chrom: 'chr1',
      start: 4000,
      end: 5000,
    });
  });
});

describe('followWindowTarget', () => {
  const names = ['chr1', 'chr2'];
  const domain = (chrom: string, a: number, b: number, c2 = chrom) => [
    { chrom, pos: a },
    { chrom: c2, pos: b },
  ];
  const win = (start: number, end: number, chrom = 'chr1') => ({ chrom, start, end });

  it('keeps follow_context_bp of context around a small window', () => {
    const size = 48_000_000;
    // Opening on the whole genome: frame 7 Mb around a 200 kb window.
    expect(
      followWindowTarget(domain('chr1', 0, 9_000_000, 'chr2'), win(10_900_000, 11_100_000), names, size, 7_000_000),
    ).toEqual({ chrom: 'chr1', start: 7_500_000, end: 14_500_000 });
    // A view already narrower than the context is widened to it.
    expect(
      followWindowTarget(domain('chr1', 10_000_000, 12_000_000), win(10_900_000, 11_100_000), names, size, 7_000_000),
    ).toEqual({ chrom: 'chr1', start: 7_500_000, end: 14_500_000 });
    // A view that already shows the context stays.
    expect(
      followWindowTarget(domain('chr1', 7_500_000, 14_500_000), win(10_900_000, 11_100_000), names, size, 7_000_000),
    ).toBe('stay');
  });
  it('stays while the window sits in the middle of the view', () => {
    expect(followWindowTarget(domain('chr1', 0, 1000), win(400, 500), names)).toBe('stay');
    // A brush the browser followed: the window is the region the view was framed on.
    expect(followWindowTarget(domain('chr1', 0, 1300), win(150, 1150), names)).toBe('stay');
  });

  it('centres the window, keeping the zoom, when it drifts to an edge', () => {
    expect(followWindowTarget(domain('chr1', 0, 1000), win(900, 960), names)).toEqual({
      chrom: 'chr1',
      start: 430,
      end: 1430,
    });
  });

  it('opens out to 1.5 times a window wider than the view', () => {
    const t = followWindowTarget(domain('chr1', 400, 500), win(0, 1000), names);
    expect(t).toEqual({ chrom: 'chr1', start: 0, end: 1500 });
  });

  it('shifts to stay inside the contig', () => {
    expect(followWindowTarget(domain('chr1', 0, 400), win(950, 990), names, 1000)).toEqual({
      chrom: 'chr1',
      start: 600,
      end: 1000,
    });
    expect(followWindowTarget(domain('chr1', 500, 900), win(10, 40), names, 1000)).toEqual({
      chrom: 'chr1',
      start: 0,
      end: 400,
    });
  });

  it('frames a window that is a sliver of a whole chromosome', () => {
    // The follow used to find the window "inside" and never move.
    expect(followWindowTarget(domain('chr1', 0, 1_000_000), win(400_000, 410_000), names, 1_000_000)).toEqual({
      chrom: 'chr1',
      start: 390_000,
      end: 420_000,
    });
  });

  it('frames the window out of the whole-genome domain the axis opens on', () => {
    expect(followWindowTarget(domain('chr1', 0, 500, 'chr2'), win(100, 400), names, 1000)).toEqual({
      chrom: 'chr1',
      start: 0,
      end: 1000,
    });
    // Once framed it is a third of the view: nothing left to do.
    expect(followWindowTarget(domain('chr1', 0, 900), win(300, 600), names)).toBe('stay');
  });

  it('leaves the call to the caller when it cannot tell', () => {
    expect(followWindowTarget(null, win(1, 2), names)).toBeNull();
    expect(followWindowTarget(domain('chr1', 0, 100), win(1, 2, 'chr2'), names)).toBeNull();
    expect(followWindowTarget(domain('chrZ', 0, 100), win(1, 2, 'chrZ'), names)).toBeNull();
  });
});

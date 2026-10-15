import { describe, expect, it } from 'vitest';

import { PLDDT_BANDS, rgbCss, SECONDARY_STRUCTURE_COLOURS } from '../protein/residueColours';
import {
  buildFigure,
  CLASS_SYMBOLS,
  hoverText,
  MAX_LEGEND_GROUPS,
  residueRing,
  summaryLine,
  TICKS,
  type ColourMode,
  type FigureArgs,
  type FigureTheme,
} from './figure';
import { REGION_NOTE, regionSet } from './regions';
import type { AnnotatedPoint } from './torsions';

const THEME: FigureTheme = {
  text: '#111',
  dimmed: '#666',
  grid: 'rgba(0,0,0,0.1)',
  zeroLine: 'rgba(0,0,0,0.4)',
  accent: '#1c7ed6',
  accentFill: 'rgba(28,126,214,0.15)',
  highlight: '#f76707',
  neutral: '#adb5bd',
  categorical: ['#c0', '#c1', '#c2', '#c3', '#c4', '#c5', '#c6', '#c7', '#c8', '#c9'],
  valueScale: 'Viridis',
};

let counter = 0;
function point(over: Partial<AnnotatedPoint> = {}): AnnotatedPoint {
  counter += 1;
  return {
    chain: 'A',
    position: counter,
    insertionCode: '',
    resName: 'ALA',
    oneLetter: 'A',
    phi: -57,
    psi: -47,
    bfactor: 95,
    cls: 'general',
    value: null,
    category: null,
    ...over,
  };
}

const gly = (over: Partial<AnnotatedPoint> = {}) =>
  point({ resName: 'GLY', oneLetter: 'G', cls: 'glycine', phi: 60, psi: -150, ...over });
const pro = (over: Partial<AnnotatedPoint> = {}) =>
  point({ resName: 'PRO', oneLetter: 'P', cls: 'proline', phi: -65, psi: -35, ...over });
const prePro = (over: Partial<AnnotatedPoint> = {}) =>
  point({ resName: 'VAL', oneLetter: 'V', cls: 'pre_proline', phi: -100, psi: 150, ...over });

function args(points: AnnotatedPoint[], over: Partial<FigureArgs> = {}): FigureArgs {
  return {
    points,
    mode: 'residue_class',
    markerSize: 6,
    showRegions: true,
    regionSet: 'general',
    theme: THEME,
    plddtFractional: false,
    bfactorLabel: 'pLDDT',
    dragmode: 'select',
    uirevision: 'P1',
    selectionrevision: 'sel-0',
    ...over,
  };
}

const names = (fig: ReturnType<typeof buildFigure>) => fig.data.map((t) => t.name);
const markerOf = (t: Record<string, unknown>) => t.marker as Record<string, unknown>;
const mixed = () => [point(), point({ bfactor: 80 }), gly(), pro(), prePro()];

describe('traces per residue class', () => {
  it('draws one trace per class present, in class order', () => {
    const fig = buildFigure(args(mixed()));
    expect(names(fig)).toEqual(['General', 'Glycine', 'Proline', 'Pre-proline']);
  });

  it('gives each class its own marker symbol', () => {
    const fig = buildFigure(args(mixed()));
    const symbols = fig.data.map((t) => new Set(markerOf(t).symbol as string[]));
    expect(symbols.map((s) => Array.from(s))).toEqual([
      [CLASS_SYMBOLS.general],
      [CLASS_SYMBOLS.glycine],
      [CLASS_SYMBOLS.proline],
      [CLASS_SYMBOLS.pre_proline],
    ]);
    expect(new Set(Object.values(CLASS_SYMBOLS)).size).toBe(4);
  });

  it('colours each class from the palette in class order', () => {
    const fig = buildFigure(args(mixed()));
    expect(fig.data.map((t) => markerOf(t).color)).toEqual(THEME.categorical.slice(0, 4));
  });

  it('skips a class that has no residues', () => {
    const fig = buildFigure(args([point(), gly()]));
    expect(names(fig)).toEqual(['General', 'Glycine']);
  });

  it('is an SVG scatter, never a GL trace', () => {
    const fig = buildFigure(args(mixed()));
    expect(fig.data.every((t) => t.type === 'scatter' && t.mode === 'markers')).toBe(true);
  });

  it('plots phi on x and psi on y, and points back at the residue it came from', () => {
    const points = mixed();
    const fig = buildFigure(args(points));
    fig.data.forEach((t, k) => {
      const idx = t.customdata as number[];
      expect(idx).toEqual(fig.members[k]);
      expect(t.x).toEqual(idx.map((i) => points[i].phi));
      expect(t.y).toEqual(idx.map((i) => points[i].psi));
    });
  });

  it('lists every point exactly once', () => {
    const points = mixed();
    const fig = buildFigure(args(points));
    expect(fig.members.flat().sort((a, b) => a - b)).toEqual(points.map((_, i) => i));
  });
});

describe('colour modes', () => {
  it('pLDDT: one trace per AlphaFold band, in band order, in the band colours', () => {
    const points = [
      point({ bfactor: 95 }),
      point({ bfactor: 75 }),
      point({ bfactor: 55 }),
      point({ bfactor: 20 }),
      point({ bfactor: null }),
    ];
    const fig = buildFigure(args(points, { mode: 'plddt' }));
    expect(fig.legendTitle).toBe('pLDDT');
    expect(fig.data.map((t) => markerOf(t).color)).toEqual([
      ...PLDDT_BANDS.map((b) => rgbCss(b.rgb)),
      THEME.neutral,
    ]);
    expect(names(fig)[names(fig).length - 1]).toBe('No B-factor');
  });

  it('pLDDT: reads a 0-1 scale as percent once decided for the structure', () => {
    const points = [point({ bfactor: 0.95 }), point({ bfactor: 0.4 })];
    const fractional = buildFigure(args(points, { mode: 'plddt', plddtFractional: true }));
    expect(fractional.data.map((t) => markerOf(t).color)).toEqual([
      rgbCss(PLDDT_BANDS[0].rgb),
      rgbCss(PLDDT_BANDS[3].rgb),
    ]);
    const plain = buildFigure(args(points, { mode: 'plddt', plddtFractional: false }));
    expect(plain.data).toHaveLength(1);
    expect(markerOf(plain.data[0]).color).toBe(rgbCss(PLDDT_BANDS[3].rgb));
  });

  it('changes the grouping and the colours when the mode switches', () => {
    const points = mixed();
    const byClass = buildFigure(args(points, { mode: 'residue_class' }));
    const byPlddt = buildFigure(args(points, { mode: 'plddt' }));
    const byChain = buildFigure(args(points, { mode: 'chain' }));
    expect(names(byClass)).not.toEqual(names(byPlddt));
    expect(byClass.legendTitle).toBe('Residue class');
    expect(byPlddt.legendTitle).toBe('pLDDT');
    expect(byChain.legendTitle).toBe('Chain');
    expect(names(byChain)).toEqual(['A']);
    // The symbols follow the residue, whatever the colour says.
    const plddtSymbols = byPlddt.data.flatMap((t) => markerOf(t).symbol as string[]);
    expect(new Set(plddtSymbols)).toEqual(new Set(Object.values(CLASS_SYMBOLS)));
  });

  it('chain: one trace per chain, a stable colour per chain name', () => {
    const points = [point({ chain: 'B' }), point({ chain: 'A' }), point({ chain: 'B' })];
    const fig = buildFigure(args(points, { mode: 'chain' }));
    expect(names(fig)).toEqual(['A', 'B']);
    expect(fig.data.map((t) => markerOf(t).color)).toEqual([THEME.categorical[0], THEME.categorical[1]]);
    expect(fig.members.map((m) => m.length)).toEqual([1, 2]);
  });

  it('chain: names a file without chain ids with a dash', () => {
    const fig = buildFigure(args([point({ chain: '' })], { mode: 'chain' }));
    expect(names(fig)).toEqual(['-']);
  });

  it('category: groups by the bound category, with the rest as "No annotation"', () => {
    const points = [
      point({ category: 'kinase' }),
      point({ category: 'SH2' }),
      point({ category: 'kinase' }),
      point({ category: null }),
    ];
    const fig = buildFigure(args(points, { mode: 'category', categoryLabel: 'domain' }));
    expect(fig.legendTitle).toBe('domain');
    expect(names(fig)).toEqual(['kinase', 'SH2', 'No annotation']);
    expect(markerOf(fig.data[fig.data.length - 1]).color).toBe(THEME.neutral);
  });

  it('category: keeps a category colour when the universe is given', () => {
    const points = [point({ category: 'b' })];
    const alone = buildFigure(args(points, { mode: 'category' }));
    const keyed = buildFigure(args(points, { mode: 'category', categoryUniverse: ['a', 'b', 'c'] }));
    expect(markerOf(alone.data[0]).color).toBe(THEME.categorical[0]);
    expect(markerOf(keyed.data[0]).color).toBe(THEME.categorical[1]);
  });

  it('category: folds the smallest groups beyond the legend cap into one "Other"', () => {
    const points: AnnotatedPoint[] = [];
    for (let k = 0; k < MAX_LEGEND_GROUPS + 5; k += 1) {
      // Group k has (k + 1) residues, so the smallest are the first ones.
      for (let n = 0; n <= k; n += 1) points.push(point({ category: `c${String(k).padStart(2, '0')}` }));
    }
    const fig = buildFigure(args(points, { mode: 'category' }));
    expect(fig.data).toHaveLength(MAX_LEGEND_GROUPS);
    const other = fig.data.find((t) => String(t.name).startsWith('Other'));
    expect(other?.name).toBe(`Other (${5 + 1})`);
    expect(markerOf(other as Record<string, unknown>).color).toBe(THEME.neutral);
    expect(fig.members.flat()).toHaveLength(points.length);
  });

  it('escapes markup in category names', () => {
    const fig = buildFigure(args([point({ category: '<b>x</b>' })], { mode: 'category' }));
    expect(fig.data[0].name).toBe('&lt;b&gt;x&lt;/b&gt;');
  });
});

describe('value mode', () => {
  it('draws one trace on a colour scale with a bar, and the rest in neutral', () => {
    const points = [point({ value: 2 }), point({ value: 10 }), point({ value: null })];
    const fig = buildFigure(args(points, { mode: 'value', valueLabel: 'conservation' }));
    expect(fig.legendTitle).toBe('conservation');
    expect(fig.data).toHaveLength(2);
    const marker = markerOf(fig.data[0]);
    expect(marker.color).toEqual([2, 10]);
    expect(marker.cmin).toBe(2);
    expect(marker.cmax).toBe(10);
    expect(marker.colorscale).toBe('Viridis');
    expect(marker.showscale).toBe(true);
    expect(fig.data[1].name).toBe('No value');
    expect(markerOf(fig.data[1]).color).toBe(THEME.neutral);
    // The legend moves down to leave the top of the margin to the bar, and
    // drops its heading: the bar already carries the title.
    const legend = fig.layout.legend as { y: number; title: { text: string } };
    expect(legend.y).toBeLessThan(1);
    expect(legend.title.text).toBe('');
  });

  it('widens a flat scale so the bar has a range', () => {
    const fig = buildFigure(args([point({ value: 3 }), point({ value: 3 })], { mode: 'value' }));
    const marker = markerOf(fig.data[0]);
    expect(marker.cmin).toBe(3);
    expect(marker.cmax).toBe(4);
  });

  it('draws everything in neutral, without a bar, when no residue has a value', () => {
    const fig = buildFigure(args([point(), point()], { mode: 'value' }));
    expect(fig.data).toHaveLength(1);
    expect(markerOf(fig.data[0]).color).toBe(THEME.neutral);
    expect(markerOf(fig.data[0]).showscale).toBeUndefined();
    expect((fig.layout.legend as Record<string, unknown>).y).toBe(1);
  });
});

describe('secondary structure mode', () => {
  it('reads the bound column when it holds secondary-structure states', () => {
    const points = [
      point({ category: 'H' }),
      point({ category: 'E' }),
      point({ category: 'C' }),
      point({ category: 'H' }),
    ];
    const fig = buildFigure(args(points, { mode: 'secondary_structure', categoryLabel: 'ss_code' }));
    expect(fig.ssSource).toBe('category');
    expect(fig.legendTitle).toContain('ss_code');
    expect(names(fig)).toEqual(['Helix', 'Strand', 'Coil']);
    expect(markerOf(fig.data[0]).color).toBe(rgbCss(SECONDARY_STRUCTURE_COLOURS.helix));
    expect(markerOf(fig.data[1]).color).toBe(rgbCss(SECONDARY_STRUCTURE_COLOURS.strand));
    expect(markerOf(fig.data[2]).color).toBe(THEME.neutral);
  });

  it('falls back to the phi/psi regions, and says so, for any other category', () => {
    const points = [
      point({ phi: -57, psi: -47, category: 'kinase' }),
      point({ phi: -120, psi: 130, category: 'kinase' }),
      point({ phi: 60, psi: 45, category: 'SH2' }),
      point({ phi: 60, psi: -150, category: 'SH2' }),
    ];
    const fig = buildFigure(args(points, { mode: 'secondary_structure' }));
    expect(fig.ssSource).toBe('torsion');
    expect(fig.legendTitle).toContain('φ/ψ regions');
    expect(fig.legendTitle).toContain('approximate');
    expect(names(fig)).toEqual([
      'Helix (αR region)',
      'Strand (β region)',
      'Left-handed (αL region)',
      'Other (outside the regions)',
    ]);
  });

  it('falls back to the regions when no category is bound at all', () => {
    const fig = buildFigure(args([point()], { mode: 'secondary_structure' }));
    expect(fig.ssSource).toBe('torsion');
  });

  it('judges a glycine against the glycine regions', () => {
    const fig = buildFigure(args([gly()], { mode: 'secondary_structure' }));
    // (60, -150) is outside the general map and inside the glycine one.
    expect(names(fig)).toEqual(['Strand (β region)']);
  });

  it('leaves unmapped states out of the three, under "No annotation"', () => {
    const points = [point({ category: 'H' }), point({ category: 'E' }), point({ category: null })];
    const fig = buildFigure(args(points, { mode: 'secondary_structure' }));
    expect(names(fig)).toEqual(['Helix', 'Strand', 'No annotation']);
  });

  it('reports no secondary-structure source in other modes', () => {
    expect(buildFigure(args(mixed(), { mode: 'plddt' })).ssSource).toBeNull();
  });
});

describe('highlighted points', () => {
  const points = [
    point({ position: 10 }),
    point({ position: 11 }),
    point({ position: 12, chain: 'B' }),
    gly({ position: 11 }),
    pro({ position: 30 }),
  ];

  it('selects the residues of the range in each trace and dims the rest', () => {
    const fig = buildFigure(args(points, { highlight: { start: 10, end: 11, chain: null } }));
    expect(fig.highlighted).toBe(3);
    fig.data.forEach((t, k) => {
      const idx = t.customdata as number[];
      const expected = idx.flatMap((i, j) => (points[i].position <= 11 ? [j] : []));
      expect(t.selectedpoints).toEqual(expected);
      expect((t.unselected as { marker: { opacity: number } }).marker.opacity).toBeLessThan(0.5);
      expect((t.selected as { marker: { opacity: number } }).marker.opacity).toBe(1);
      expect(idx).toEqual(fig.members[k]);
    });
  });

  it('gives a trace with nothing in the range an empty selection, which dims all of it', () => {
    const fig = buildFigure(args(points, { highlight: { start: 10, end: 11, chain: null } }));
    const proline = fig.data.find((t) => t.name === 'Proline') as Record<string, unknown>;
    expect(proline.selectedpoints).toEqual([]);
  });

  it('restricts the selection to a chain when it names one', () => {
    const fig = buildFigure(args(points, { highlight: { start: 10, end: 12, chain: 'B' } }));
    expect(fig.highlighted).toBe(1);
  });

  it('draws plainly, with no selection state at all, when nothing is highlighted', () => {
    const fig = buildFigure(args(points, { highlight: null }));
    expect(fig.highlighted).toBe(0);
    for (const t of fig.data) {
      expect(t).not.toHaveProperty('selectedpoints');
      expect(t).not.toHaveProperty('unselected');
    }
  });

  it('applies to every colour mode, the value mode included', () => {
    const valued = points.map((p, i) => ({ ...p, value: i }));
    const fig = buildFigure(
      args(valued, { mode: 'value', highlight: { start: 30, end: 30, chain: null } }),
    );
    expect(fig.highlighted).toBe(1);
    expect(fig.data.every((t) => Array.isArray(t.selectedpoints))).toBe(true);
  });

  it('numbers the selection by position in the trace, not in the table', () => {
    const fig = buildFigure(args(points, { highlight: { start: 11, end: 11, chain: null } }));
    const general = fig.data.find((t) => t.name === 'General') as Record<string, unknown>;
    const idx = general.customdata as number[];
    const selected = general.selectedpoints as number[];
    expect(selected.map((j) => points[idx[j]].position)).toEqual([11]);
  });
});

describe('residueRing', () => {
  const points = [
    point({ position: 5, phi: -60, psi: -40 }),
    point({ position: 6, phi: -70, psi: 130 }),
    point({ position: 6, chain: 'B', phi: 60, psi: 45 }),
  ];

  it('rings the residues of the range, larger than the marker', () => {
    const ring = residueRing(points, { start: 6, end: 6, chain: null }, THEME.highlight, 6);
    expect(ring).not.toBeNull();
    expect(ring?.x).toEqual([-70, 60]);
    expect(ring?.y).toEqual([130, 45]);
    expect(ring?.hoverinfo).toBe('skip');
    expect(ring?.showlegend).toBe(false);
    const marker = ring?.marker as Record<string, unknown>;
    expect(marker.symbol).toBe('circle-open');
    expect(marker.size).toBeGreaterThan(6);
    expect(marker.color).toBe(THEME.highlight);
    // Never dimmed by a selection elsewhere in the plot.
    expect((ring?.unselected as { marker: { opacity: number } }).marker.opacity).toBe(1);
  });

  it('keeps to one chain when the event names it', () => {
    const ring = residueRing(points, { start: 6, end: 6, chain: 'B' }, THEME.highlight, 6);
    expect(ring?.x).toEqual([60]);
  });

  it('draws nothing for no event or a residue that is not plotted', () => {
    expect(residueRing(points, null, THEME.highlight, 6)).toBeNull();
    expect(residueRing(points, { start: 99, end: 99, chain: null }, THEME.highlight, 6)).toBeNull();
  });
});

describe('layout', () => {
  const fig = buildFigure(args(mixed()));
  const x = fig.layout.xaxis as Record<string, unknown>;
  const y = fig.layout.yaxis as Record<string, unknown>;

  it('spans -180 to 180 on both axes with a tick every 60 degrees', () => {
    expect(x.range).toEqual([-180, 180]);
    expect(y.range).toEqual([-180, 180]);
    expect(x.tickvals).toEqual([-180, -120, -60, 0, 60, 120, 180]);
    expect(y.tickvals).toEqual([...TICKS]);
    for (let k = 1; k < TICKS.length; k += 1) expect(TICKS[k] - TICKS[k - 1]).toBe(60);
    expect(x.ticksuffix).toBe('°');
  });

  it('names the axes with the angles', () => {
    expect((x.title as { text: string }).text).toContain('φ');
    expect((y.title as { text: string }).text).toContain('ψ');
  });

  it('keeps the plot square and draws the origin lines', () => {
    expect(y.scaleanchor).toBe('x');
    expect(y.scaleratio).toBe(1);
    expect(x.constrain).toBe('domain');
    expect(y.constrain).toBe('domain');
    expect(x.zeroline).toBe(true);
    expect(y.zeroline).toBe(true);
  });

  it('passes the interaction state through', () => {
    const f = buildFigure(args(mixed(), { dragmode: 'zoom', uirevision: 'Q9', selectionrevision: 'sel-3' }));
    expect(f.layout.dragmode).toBe('zoom');
    expect(f.layout.uirevision).toBe('Q9');
    expect(f.layout.selectionrevision).toBe('sel-3');
    expect(f.layout.hovermode).toBe('closest');
  });

  it('shows a legend titled by the colour mode', () => {
    expect(fig.layout.showlegend).toBe(true);
    expect((fig.layout.legend as { title: { text: string } }).title.text).toBe('Residue class');
  });
});

describe('favoured regions', () => {
  const subpaths = (shape: Record<string, unknown>) => String(shape.path).split('Z').length - 1;

  it('draws the whole set as one path shape under the points', () => {
    const fig = buildFigure(args(mixed()));
    const shapes = fig.layout.shapes as Record<string, unknown>[];
    expect(shapes).toHaveLength(1);
    const [shape] = shapes;
    expect(shape.type).toBe('path');
    expect(shape.layer).toBe('below');
    expect(String(shape.path).startsWith('M')).toBe(true);
    expect(String(shape.path).endsWith('Z')).toBe(true);
    // One closed sub-path per polygon of the set.
    expect(subpaths(shape)).toBe(regionSet('general').length);
    expect(shape.fillcolor).toBe(THEME.accentFill);
  });

  it('labels the regions as approximate, not as MolProbity contours, in the legend', () => {
    const fig = buildFigure(args(mixed()));
    const [shape] = fig.layout.shapes as Record<string, unknown>[];
    expect(shape.showlegend).toBe(true);
    const text = String(shape.name).replace(/<br>/g, ' ');
    expect(text).toContain(REGION_NOTE);
    expect(text).toContain('general case');
  });

  it('gives the set one legend entry, so one click hides every polygon', () => {
    const fig = buildFigure(args(mixed()));
    const shapes = fig.layout.shapes as Record<string, unknown>[];
    expect(shapes.filter((s) => s.showlegend === true)).toHaveLength(1);
    expect(shapes[0].legendgroup).toBe('regions');
  });

  it('writes the region names on the labelled polygons', () => {
    const fig = buildFigure(args(mixed()));
    const labels = (fig.layout.annotations as { text: string }[]).map((a) => a.text);
    expect(labels.sort()).toEqual(['β', 'αL', 'αR'].sort());
  });

  it('draws the glycine set, and says so, for a plot filtered to glycine', () => {
    const fig = buildFigure(args([gly()], { regionSet: 'glycine' }));
    const [shape] = fig.layout.shapes as Record<string, unknown>[];
    expect(subpaths(shape)).toBe(regionSet('glycine').length);
    expect(String(shape.name)).toContain('glycine');
  });

  it('draws the proline set, which has no left-handed region', () => {
    const fig = buildFigure(args([pro()], { regionSet: 'proline' }));
    const labels = (fig.layout.annotations as { text: string }[]).map((a) => a.text);
    expect(labels).not.toContain('αL');
    expect(String((fig.layout.shapes as Record<string, unknown>[])[0].name)).toContain('proline');
  });

  it('draws nothing when the regions are off', () => {
    const fig = buildFigure(args(mixed(), { showRegions: false }));
    expect(fig.layout.shapes).toEqual([]);
    expect(fig.layout.annotations).toEqual([]);
  });
});

describe('hoverText', () => {
  const opts = { bfactorLabel: 'pLDDT' as const, plddtFractional: false };

  it('names the chain, position, residue, angles, class and pLDDT', () => {
    const text = hoverText(point({ chain: 'B', position: 45, resName: 'LEU', phi: -63.04, psi: -41.96, bfactor: 91.5 }), opts);
    expect(text).toContain('<b>LEU 45</b>');
    expect(text).toContain('Chain B');
    expect(text).toContain('φ -63.0°');
    expect(text).toContain('ψ -42.0°');
    expect(text).toContain('General');
    expect(text).toContain('pLDDT 91.5');
  });

  it('leaves out the lines the residue has nothing for', () => {
    const text = hoverText(point({ chain: '', bfactor: null }), opts);
    expect(text).not.toContain('Chain');
    expect(text).not.toContain('pLDDT');
    expect(text).not.toContain('Value');
    expect(text).not.toContain('Category');
  });

  it('writes an insertion code after the position', () => {
    expect(hoverText(point({ position: 45, insertionCode: 'A' }), opts)).toContain('<b>ALA 45A</b>');
  });

  it('shows a fractional pLDDT on the 0-100 scale and a B-factor as it is', () => {
    expect(hoverText(point({ bfactor: 0.915 }), { ...opts, plddtFractional: true })).toContain(
      'pLDDT 91.5',
    );
    expect(
      hoverText(point({ bfactor: 23.456 }), { bfactorLabel: 'B-factor', plddtFractional: false }),
    ).toContain('B-factor 23.5');
  });

  it('adds the bound value and category under their column names, escaped', () => {
    const text = hoverText(point({ value: 0.25, category: '<i>kinase</i>' }), {
      ...opts,
      valueLabel: 'conservation',
      categoryLabel: 'domain',
    });
    expect(text).toContain('conservation: 0.25');
    expect(text).toContain('domain: &lt;i&gt;kinase&lt;/i&gt;');
  });
});

describe('summaryLine', () => {
  it('counts the residues inside and outside the approximate regions', () => {
    const line = summaryLine({
      entity: 'P04637',
      plotted: 120,
      withoutTorsions: 2,
      favoured: { inside: 110, outside: 10 },
      selection: null,
    });
    expect(line).toBe(
      'P04637 · 120 residues · 2 without φ/ψ · 110 inside / 10 outside the approximate favoured regions',
    );
  });

  it('says nothing of the regions when they are not shown', () => {
    const line = summaryLine({
      entity: null,
      plotted: 5,
      withoutTorsions: 0,
      favoured: null,
      selection: { start: 3, end: 8 },
    });
    expect(line).toBe('5 residues · residues 3-8');
  });

  it('writes a single picked residue in the singular', () => {
    expect(
      summaryLine({ entity: 'X', plotted: 5, withoutTorsions: 0, favoured: null, selection: { start: 4, end: 4 } }),
    ).toContain('residue 4');
  });
});

describe('every mode builds', () => {
  const modes: ColourMode[] = ['plddt', 'residue_class', 'secondary_structure', 'value', 'category', 'chain'];
  it.each(modes)('%s on a small set', (mode) => {
    const fig = buildFigure(args(mixed(), { mode }));
    expect(fig.data.length).toBeGreaterThan(0);
    expect(fig.members.flat()).toHaveLength(5);
  });

  it('builds an empty plot for no points', () => {
    const fig = buildFigure(args([]));
    expect(fig.data).toEqual([]);
    expect(fig.highlighted).toBe(0);
  });
});

import { describe, expect, it } from 'vitest';

import {
  axisBreakShapes,
  barSlots,
  compositionColumns,
  DENSE_AXIS_BARS,
  formatAxisFloor,
  groupSamples,
  isDenseTaxonomyAxis,
  isSpacerSlot,
  meltWideRows,
  naturalCompare,
  niceStep,
  percentTickFormat,
  resolveSortCategory,
  SAMPLE_SORT_OPTIONS,
  sortSamples,
  taxonomyAxisTitle,
  taxonomyLegend,
  taxonomyLegendTopPx,
  valueAxisTitle,
  visibleTaxonomyControls,
  wideCategoryName,
  zoomedValueRange,
} from './stackedTaxonomyOptions';

describe('wide tables', () => {
  // orthofinder species stats: one row per species, one column per class.
  const rows = {
    species: ['human', 'mouse'],
    genes_in_orthogroups: [18000, 17500],
    genes_in_species_specific: [400, null],
    unassigned_genes: [600, 'n/a'],
    total: [19000, 18000],
  };
  const cols = ['genes_in_orthogroups', 'genes_in_species_specific', 'unassigned_genes'];

  it('melts row by row, then column by column, into the long form', () => {
    expect(meltWideRows(rows, 'species', cols, { unassigned_genes: 'Unassigned' })).toEqual({
      samples: ['human', 'human', 'human', 'mouse', 'mouse', 'mouse'],
      taxa: [
        'genes_in_orthogroups',
        'genes_in_species_specific',
        'Unassigned',
        'genes_in_orthogroups',
        'genes_in_species_specific',
        'Unassigned',
      ],
      // Empty and non-numeric cells count as 0.
      abundances: [18000, 400, 600, 17500, 0, 0],
    });
  });

  it('skips a value column the table lacks, and reads nothing it was not given', () => {
    const melted = meltWideRows(rows, 'species', ['unassigned_genes', 'missing']);
    expect(melted.taxa).toEqual(['unassigned_genes', 'unassigned_genes']);
    expect(melted.abundances).toEqual([600, 0]);
    expect(meltWideRows({}, 'species', cols)).toEqual({ samples: [], taxa: [], abundances: [] });
  });

  it('names a category by its label, else its column', () => {
    expect(wideCategoryName('a', { a: 'A' })).toBe('A');
    expect(wideCategoryName('b', { a: 'A' })).toBe('b');
    expect(wideCategoryName('b', null)).toBe('b');
  });

  it('fetches the sample id and value columns (plus annotations) for a wide table', () => {
    expect(
      compositionColumns({
        sampleCol: 'species',
        taxonCol: 'taxon',
        rankCol: null,
        abundanceCol: 'abundance',
        valueCols: cols,
        extra: ['clade', undefined, 'clade'],
      }),
    ).toEqual(['species', ...cols, 'clade']);
  });

  it('fetches the long-form bindings otherwise, as before', () => {
    expect(
      compositionColumns({
        sampleCol: 'sample_id',
        taxonCol: 'taxon',
        rankCol: 'rank',
        abundanceCol: 'abundance',
        valueCols: null,
        extra: ['habitat', 'habitat'],
      }),
    ).toEqual(['sample_id', 'taxon', 'rank', 'abundance', 'habitat']);
    // No rank column: three bindings.
    expect(
      compositionColumns({
        sampleCol: 'sample_id',
        taxonCol: 'taxon',
        rankCol: null,
        abundanceCol: 'abundance',
        valueCols: [],
        extra: [],
      }),
    ).toEqual(['sample_id', 'taxon', 'abundance']);
  });
});

describe('visibleTaxonomyControls', () => {
  it('offers every control when nothing is hidden, as the taxonomy tile always did', () => {
    const all = {
      rank: true,
      sample_sort: true,
      top_n: true,
      normalise: true,
      group: true,
      zoom: true,
    };
    expect(visibleTaxonomyControls(undefined)).toEqual(all);
    expect(visibleTaxonomyControls(null)).toEqual(all);
    expect(visibleTaxonomyControls([])).toEqual(all);
  });

  it('drops only the controls the config hides', () => {
    expect(visibleTaxonomyControls(['rank', 'top_n', 'sample_sort', 'zoom'])).toEqual({
      rank: false,
      sample_sort: false,
      top_n: false,
      normalise: true,
      group: true,
      zoom: false,
    });
  });
});

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

const CELLS: Record<string, Record<string, number>> = {
  S10: { A: 10, B: 30 },
  S2: { A: 50, B: 10 },
  s1: { A: 5, B: 5 },
};
const total = (s: string) => Object.values(CELLS[s]).reduce((a, b) => a + b, 0);
const scores = {
  total,
  firstTaxon: (s: string) => CELLS[s].A,
  category: (s: string) => CELLS[s].B / total(s),
};
const INPUT = ['S10', 'S2', 's1'];

describe('sortSamples', () => {
  it('keeps the input order for `input` and for an unknown mode', () => {
    expect(sortSamples(INPUT, 'input', scores)).toEqual(INPUT);
    expect(sortSamples(INPUT, undefined, scores)).toEqual(INPUT);
    expect(sortSamples(INPUT, 'nonsense', scores)).toEqual(INPUT);
  });

  it('sorts names naturally and case-insensitively', () => {
    expect(sortSamples(INPUT, 'name', scores)).toEqual(['s1', 'S2', 'S10']);
    expect(naturalCompare('a', 'A')).not.toBe(0);
  });

  it('puts the largest first for the value sorts', () => {
    expect(sortSamples(INPUT, 'total_abundance', scores)).toEqual(['S2', 'S10', 's1']);
    expect(sortSamples(INPUT, 'first_taxon', scores)).toEqual(['S2', 'S10', 's1']);
    // By the share of B: 0.75, 0.5, 0.167.
    expect(sortSamples(INPUT, 'category', scores)).toEqual(['S10', 's1', 'S2']);
  });

  it('is stable: ties keep the input order', () => {
    const flat = { total: () => 1, firstTaxon: () => 1, category: () => 1 };
    expect(sortSamples(INPUT, 'category', flat)).toEqual(INPUT);
  });

  it('offers every model value in the picker', () => {
    expect(SAMPLE_SORT_OPTIONS.map((o) => o.value)).toEqual([
      'input',
      'name',
      'total_abundance',
      'first_taxon',
      'category',
    ]);
  });
});

describe('resolveSortCategory', () => {
  it('uses the chosen category when shown, else the first (most abundant)', () => {
    expect(resolveSortCategory('B', ['A', 'B'])).toBe('B');
    expect(resolveSortCategory('Z', ['A', 'B'])).toBe('A');
    expect(resolveSortCategory(null, ['A', 'B'])).toBe('A');
    expect(resolveSortCategory(null, [])).toBeNull();
  });
});

describe('groupSamples / barSlots', () => {
  const groupOf = (s: string) => ({ a1: 'ctrl', a2: 'treat', a3: 'ctrl', a4: 'treat' })[s] ?? '—';

  it('keeps the sort inside each group, groups in order of first appearance', () => {
    const sorted = ['a4', 'a3', 'a2', 'a1'];
    expect(groupSamples(sorted, ['a1', 'a2', 'a3', 'a4'], groupOf, false)).toEqual([
      { name: 'ctrl', samples: ['a3', 'a1'] },
      { name: 'treat', samples: ['a4', 'a2'] },
    ]);
  });

  it('orders groups by name under a name sort', () => {
    const g = groupSamples(['a2', 'a1'], ['a2', 'a1'], groupOf, true);
    expect(g.map((x) => x.name)).toEqual(['ctrl', 'treat']);
  });

  it('sets groups apart by one blank slot each', () => {
    const groups = [
      { name: 'ctrl', samples: ['a1', 'a3'] },
      { name: 'treat', samples: ['a2'] },
    ];
    const v = barSlots(groups, false);
    expect(v.slots.length).toBe(4);
    expect(v.slots.filter(isSpacerSlot).length).toBe(1);
    expect(v.slots[2]).not.toBe('');
    expect(v.spans).toEqual([
      { name: 'ctrl', start: 0, end: 1, labelSlot: null },
      { name: 'treat', start: 3, end: 3, labelSlot: 2 },
    ]);
    // Horizontal bars head every group with a blank row for its name.
    const h = barSlots(groups, true);
    expect(h.slots.filter(isSpacerSlot).length).toBe(2);
    expect(h.spans.map((s) => s.labelSlot)).toEqual([0, 3]);
    // Every slot is a distinct category.
    expect(new Set(h.slots).size).toBe(h.slots.length);
    expect(isSpacerSlot('S1')).toBe(false);
    expect(isSpacerSlot('')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Zoom
// ---------------------------------------------------------------------------

describe('niceStep', () => {
  it('rounds up to 1, 2 or 5 times a power of ten', () => {
    expect(niceStep(0.011)).toBe(0.02);
    expect(niceStep(0.02)).toBe(0.02);
    expect(niceStep(0.3)).toBe(0.5);
    expect(niceStep(7)).toBe(10);
    expect(niceStep(0)).toBe(1);
  });
});

describe('zoomedValueRange', () => {
  it('crops a normalised axis to just under the smallest bottom segment', () => {
    // Every bar is 95–99 % one class.
    const zoom = zoomedValueRange([0.97, 0.95, 0.99], [1, 1, 1], true);
    expect(zoom).toEqual({ floor: 0.94, top: 1, step: 0.02 });
    expect(percentTickFormat(zoom!.step)).toBe('.0%');
    expect(formatAxisFloor(zoom!, true)).toBe('94%');
  });

  it('keeps enough tick precision for a very tight crop', () => {
    const zoom = zoomedValueRange([0.998, 0.996], [1, 1], true)!;
    expect(zoom.floor).toBeGreaterThan(0.99);
    expect(zoom.floor).toBeLessThan(0.996);
    expect(percentTickFormat(zoom.step)).toBe('.1%');
    expect(formatAxisFloor(zoom, true)).toMatch(/^99\.\d%$/);
  });

  it('crops raw values too, and pads the top', () => {
    const zoom = zoomedValueRange([900, 950], [1000, 1010], false)!;
    expect(zoom.floor).toBe(850);
    expect(zoom.top).toBeGreaterThan(1010);
    expect(formatAxisFloor(zoom, false)).toBe('850');
  });

  it('is a no-op when the floor would sit near zero', () => {
    expect(zoomedValueRange([0.1, 0.6], [1, 1], true)).toBeNull();
    expect(zoomedValueRange([0, 0.9], [1, 1], true)).toBeNull();
  });

  it('is a no-op when the bottom segment fills every bar', () => {
    expect(zoomedValueRange([1, 1], [1, 1], true)).toBeNull();
  });

  it('ignores the blank slots between groups', () => {
    expect(zoomedValueRange([0.97, null, 0.95], [1, 0, 1], true)).toEqual({
      floor: 0.94,
      top: 1,
      step: 0.02,
    });
    expect(zoomedValueRange([], [], true)).toBeNull();
  });
});

describe('valueAxisTitle', () => {
  it('reads the fallback unset, and says where a cropped axis starts', () => {
    expect(valueAxisTitle(undefined, 'Relative abundance', null)).toBe('Relative abundance');
    expect(valueAxisTitle('Share', 'Relative abundance', null)).toBe('Share');
    expect(valueAxisTitle('', 'Relative abundance', null)).toBeUndefined();
    expect(valueAxisTitle(undefined, 'Relative abundance', '94%')).toBe(
      'Relative abundance (axis from 94%)',
    );
    expect(valueAxisTitle('', 'x', '94%')).toBe('Axis from 94%');
  });
});

describe('axisBreakShapes', () => {
  const colors = { line: '#333', background: '#fff' };

  it('draws two parallel slashes across a vertical axis, cutting its line between them', () => {
    const shapes = axisBreakShapes('v', { x: 0, y: 0.2 }, colors);
    expect(shapes).toHaveLength(3);
    for (const s of shapes) {
      expect(s).toMatchObject({
        type: 'line',
        xref: 'paper',
        yref: 'paper',
        xsizemode: 'pixel',
        ysizemode: 'pixel',
        xanchor: 0,
        yanchor: 0.2,
      });
    }
    const [cut, a, b] = shapes as Record<string, number & { color?: string }>[];
    // The cut runs along the axis (x fixed), in the background colour.
    expect(cut.x0).toBe(0);
    expect(cut.x1).toBe(0);
    expect((cut as any).line.color).toBe('#fff');
    // The slashes cross the axis and lean the same way, the cut between them.
    for (const s of [a, b]) {
      expect(s.x0).toBeLessThan(0);
      expect(s.x1).toBeGreaterThan(0);
      expect(s.y1 - s.y0).toBeGreaterThan(0);
      expect((s as any).line.color).toBe('#333');
    }
    expect(b.y0 - a.y0).toBe(cut.y1 - cut.y0);
    expect(a.y0).toBeGreaterThan(0);
  });

  it('draws them across a horizontal axis for horizontal bars', () => {
    const shapes = axisBreakShapes('h', { x: 0.1, y: 0 }, colors) as Record<string, number>[];
    const [cut, a, b] = shapes;
    expect(shapes[0]).toMatchObject({ xanchor: 0.1, yanchor: 0 });
    expect(cut.y0).toBe(0);
    expect(cut.y1).toBe(0);
    for (const s of [a, b]) {
      expect(s.y0).toBeLessThan(0);
      expect(s.y1).toBeGreaterThan(0);
      expect(s.x1 - s.x0).toBeGreaterThan(0);
    }
    expect(b.x0 - a.x0).toBe(cut.x1 - cut.x0);
  });
});

describe('taxonomyAxisTitle', () => {
  it('reads "Sample" when unset, as the tile always did', () => {
    expect(taxonomyAxisTitle(undefined)).toBe('Sample');
    expect(taxonomyAxisTitle(null)).toBe('Sample');
  });

  it('uses the configured title, and none for an empty string', () => {
    expect(taxonomyAxisTitle('Library')).toBe('Library');
    expect(taxonomyAxisTitle('')).toBeUndefined();
  });
});

describe('dense axis', () => {
  it('starts past 40 bars', () => {
    expect(DENSE_AXIS_BARS).toBe(40);
    expect(isDenseTaxonomyAxis(40)).toBe(false);
    expect(isDenseTaxonomyAxis(41)).toBe(true);
  });
});

describe('taxonomyLegend', () => {
  it('keeps the titled column right of the bars by default, dense or not', () => {
    for (const pos of [undefined, null, 'right'] as const) {
      expect(taxonomyLegend(pos, false, 'Phylum')).toEqual({
        orientation: 'v',
        x: 1.02,
        xanchor: 'left',
        y: 1,
        yanchor: 'top',
        title: { text: 'Phylum ' },
        font: { size: 10 },
      });
    }
    expect(taxonomyLegend('right', true, 'Phylum')).toMatchObject({ orientation: 'v', x: 1.02 });
    expect(taxonomyLegendTopPx('right', true, true)).toBe(0);
  });

  it('draws rows under the whole figure on request', () => {
    expect(taxonomyLegend('bottom', false, 'Level')).toMatchObject({
      orientation: 'h',
      y: 0,
      yref: 'container',
      yanchor: 'bottom',
      title: { text: 'Level ' },
    });
    expect(taxonomyLegendTopPx('bottom', false, true)).toBe(0);
  });

  it('lifts a bottom legend above the bars once the sample labels are hidden', () => {
    expect(taxonomyLegend('bottom', true, 'Level')).toMatchObject({
      orientation: 'h',
      y: 1.02,
      yanchor: 'bottom',
    });
    expect(taxonomyLegendTopPx('bottom', true, true)).toBe(40);
    // No legend shown, no room kept for it.
    expect(taxonomyLegendTopPx('bottom', true, false)).toBe(0);
  });
});

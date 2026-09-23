import { describe, it, expect } from 'vitest';

import {
  CONTROLS_PLACEMENTS,
  formatRegion,
  genomeRegionEcho,
  inlineLayoutFor,
  isControlsPlacement,
  nextPlacement,
  resolveControlsPlacement,
  selectionEcho,
} from './controlsPlacement';
import type { InteractiveFilter } from '../../api';

describe('resolveControlsPlacement', () => {
  it('defaults to the popover, which is what every tile did before', () => {
    expect(resolveControlsPlacement(undefined)).toBe('popover');
    expect(resolveControlsPlacement({})).toBe('popover');
  });

  it('takes the dashboard default when the tile says nothing', () => {
    expect(resolveControlsPlacement({}, 'header')).toBe('header');
    expect(resolveControlsPlacement(undefined, 'rail')).toBe('rail');
  });

  it("lets the tile's own config win over the dashboard default", () => {
    expect(resolveControlsPlacement({ controls_placement: 'rail' }, 'header')).toBe('rail');
    expect(resolveControlsPlacement({ controls_placement: 'popover' }, 'rail')).toBe('popover');
  });

  it('ignores values that are not placements, on either level', () => {
    expect(resolveControlsPlacement({ controls_placement: 'sidebar' }, 'header')).toBe('header');
    expect(resolveControlsPlacement({}, 'sidebar')).toBe('popover');
    expect(resolveControlsPlacement({ controls_placement: 3 })).toBe('popover');
  });

  it('recognises exactly the three placements', () => {
    expect(CONTROLS_PLACEMENTS.every(isControlsPlacement)).toBe(true);
    expect(isControlsPlacement('drawer')).toBe(false);
    expect(isControlsPlacement(null)).toBe(false);
  });
});

describe('nextPlacement', () => {
  it('cycles popover -> header -> rail -> popover', () => {
    expect(nextPlacement('popover')).toBe('header');
    expect(nextPlacement('header')).toBe('rail');
    expect(nextPlacement('rail')).toBe('popover');
  });
});

describe('inlineLayoutFor', () => {
  it('draws nothing inline on the popover placement', () => {
    expect(inlineLayoutFor('popover', 900, true)).toBe('none');
  });

  it('draws nothing when the renderer published no controls', () => {
    expect(inlineLayoutFor('header', 900, false)).toBe('none');
    expect(inlineLayoutFor('rail', 900, false)).toBe('none');
  });

  it('puts the strip under the title at any width', () => {
    expect(inlineLayoutFor('header', 200, true)).toBe('header');
    expect(inlineLayoutFor('header', 1400, true)).toBe('header');
  });

  it('only puts the rail beside the plot on a wide enough tile', () => {
    expect(inlineLayoutFor('rail', 479, true)).toBe('rail-below');
    expect(inlineLayoutFor('rail', 480, true)).toBe('rail-side');
    expect(inlineLayoutFor('rail', 1200, true)).toBe('rail-side');
  });

  it('starts the rail below the plot while the width is unmeasured', () => {
    expect(inlineLayoutFor('rail', null, true)).toBe('rail-below');
  });
});

describe('genomeRegionEcho', () => {
  const region = (chroms: string[], range?: [number, number]): InteractiveFilter[] => [
    {
      index: 'a',
      value: chroms,
      source: 'genome_selection',
      column_name: 'chrom',
      interactive_component_type: 'MultiSelect',
    },
    {
      index: 'a::pos',
      value: range ?? [],
      source: 'genome_selection',
      column_name: 'pos',
      interactive_component_type: 'RangeSlider',
    },
  ];

  it('is null when no region filter reached the tile', () => {
    expect(genomeRegionEcho(undefined)).toBeNull();
    expect(genomeRegionEcho([])).toBeNull();
    expect(
      genomeRegionEcho([
        { index: 'b', value: ['SAMPLE_1'], source: 'table_selection', column_name: 'sample' },
      ]),
    ).toBeNull();
  });

  it('reads a single chromosome plus range as a locus', () => {
    expect(genomeRegionEcho(region(['chr7'], [55_000_000, 56_000_000]))).toBe(
      'chr7:55,000,000-56,000,000',
    );
  });

  it('falls back to the bare contig with no range', () => {
    expect(genomeRegionEcho(region(['chr7']))).toBe('chr7');
  });

  it('counts chromosomes rather than pretending several are one locus', () => {
    expect(genomeRegionEcho(region(['chr1', 'chr7'], [1, 2]))).toBe('2 chromosomes');
  });

  it('ignores an inverted or degenerate range', () => {
    expect(genomeRegionEcho(region(['chr7'], [900, 900]))).toBe('chr7');
  });
});

describe('formatRegion', () => {
  it('groups the digits so a locus can be read at a glance', () => {
    expect(formatRegion('chr1', 1000, 2_500_000)).toBe('chr1:1,000-2,500,000');
  });

  it('degrades to the contig when a bound is not finite', () => {
    expect(formatRegion('chr1', 0, Number.POSITIVE_INFINITY)).toBe('chr1');
  });
});

describe('selectionEcho', () => {
  it('says nothing when there is nothing to say', () => {
    expect(selectionEcho({})).toBeNull();
    expect(selectionEcho({ reduction: null, region: null })).toBeNull();
  });

  it('echoes the reduction as shown / total rows', () => {
    expect(selectionEcho({ reduction: { displayed: 412, total: 5000, full: false } })).toBe(
      '412 / 5,000 rows',
    );
  });

  it('drops the ratio once everything is on screen', () => {
    expect(selectionEcho({ reduction: { displayed: 343, total: 343, full: false } })).toBe(
      '343 rows',
    );
    expect(selectionEcho({ reduction: { displayed: 412, total: 5000, full: true } })).toBe(
      '5,000 rows',
    );
  });

  it('falls back to the rows in hand when nothing was sampled', () => {
    expect(selectionEcho({ rows: 1234 })).toBe('1,234 rows');
    expect(selectionEcho({ rows: 0 })).toBeNull();
    // A reduction is the better answer whenever there is one.
    expect(
      selectionEcho({ rows: 1000, reduction: { displayed: 412, total: 5000, full: false } }),
    ).toBe('412 / 5,000 rows');
  });

  it("lets a renderer's own summary replace the row count", () => {
    expect(
      selectionEcho({
        echo: 'A (412) vs B (388)',
        reduction: { displayed: 800, total: 800, full: false },
      }),
    ).toBe('A (412) vs B (388)');
  });

  it('appends the region a filter carried in', () => {
    expect(
      selectionEcho({
        reduction: { displayed: 412, total: 5000, full: false },
        region: 'chr7:55,000,000-56,000,000',
      }),
    ).toBe('412 / 5,000 rows · chr7:55,000,000-56,000,000');
    expect(selectionEcho({ region: 'chr7' })).toBe('chr7');
  });
});

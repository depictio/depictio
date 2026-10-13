import { describe, expect, it } from 'vitest';

import type { FilterSectionSpec, StoredMetadata } from '../../../api';
import {
  barSectionNames,
  hasSectionBar,
  isBarMember,
  isBarSection,
  isFullRange,
  isStripSection,
  partitionBarMembers,
  sectionBarNames,
  sectionRuns,
  stripControlKind,
  stripLabel,
  stripShowsIcon,
  visibleFilterCount,
} from './stripLayout';

const meta = (extra: Partial<StoredMetadata>): StoredMetadata =>
  ({ index: 'x', component_type: 'interactive', ...extra }) as StoredMetadata;

const SECTIONS: FilterSectionSpec[] = [
  { name: 'Filters', display: 'strip' },
  { name: 'Key figures', filter_bar: true },
  { name: 'Charts', display: 'grid' },
  // A strip asking for a bar of its own as well is still just a strip.
  { name: 'Both', display: 'strip', filter_bar: true },
];

describe('bar sections', () => {
  it('tells the two kinds of bar apart', () => {
    expect(isStripSection({ name: 'x', display: 'strip' })).toBe(true);
    expect(isStripSection({ name: 'x', filter_bar: true })).toBe(false);
    expect(hasSectionBar({ name: 'x', filter_bar: true })).toBe(true);
    expect(hasSectionBar({ name: 'x', display: 'strip', filter_bar: true })).toBe(false);
    expect(hasSectionBar({ name: 'x', filter_bar: false })).toBe(false);
    expect(isBarSection({ name: 'x' })).toBe(false);
    expect(isBarSection(null)).toBe(false);
  });

  it('names the sections whose filters render in a bar, and those with their own', () => {
    expect([...barSectionNames(SECTIONS)]).toEqual(['Filters', 'Key figures', 'Both']);
    expect([...sectionBarNames(SECTIONS)]).toEqual(['Key figures']);
  });

  it('copes with no sections at all', () => {
    expect(barSectionNames(undefined).size).toBe(0);
    expect(sectionBarNames(null).size).toBe(0);
  });
});

describe('isBarMember', () => {
  const names = barSectionNames(SECTIONS);

  it('takes an interactive component naming either kind of bar section', () => {
    expect(isBarMember(meta({ section: 'Filters' }), names)).toBe(true);
    expect(isBarMember(meta({ section: 'Key figures' }), names)).toBe(true);
  });

  it('leaves everything else where it was', () => {
    // Unsectioned, or in a section without a bar: the filter panel.
    expect(isBarMember(meta({}), names)).toBe(false);
    expect(isBarMember(meta({ section: 'Charts' }), names)).toBe(false);
    // Not interactive: a card in a bar section is still a grid tile.
    expect(isBarMember(meta({ component_type: 'card', section: 'Filters' }), names)).toBe(false);
    expect(isBarMember(meta({ component_type: 'card', section: 'Key figures' }), names)).toBe(false);
    // The footer wins: a Timeline lifted to the top has no compact form.
    expect(isBarMember(meta({ section: 'Filters', placement: 'top' }), names)).toBe(false);
  });

  it('partitions in order', () => {
    const a = meta({ index: 'a', section: 'Filters' });
    const b = meta({ index: 'b' });
    const c = meta({ index: 'c', section: 'Key figures' });
    const { bar, rest } = partitionBarMembers([a, b, c], names);
    expect(bar.map((m) => m.index)).toEqual(['a', 'c']);
    expect(rest.map((m) => m.index)).toEqual(['b']);
  });
});

describe('visibleFilterCount', () => {
  it('shows two filters on a section bar unless told otherwise', () => {
    expect(visibleFilterCount({ name: 'k', filter_bar: true }, 4)).toBe(2);
    expect(visibleFilterCount({ name: 'k', filter_bar: true, visible_filters: 3 }, 4)).toBe(3);
  });

  it('shows every filter on a strip unless told otherwise', () => {
    expect(visibleFilterCount({ name: 'f', display: 'strip' }, 4)).toBe(4);
    expect(visibleFilterCount({ name: 'f', display: 'strip', visible_filters: 1 }, 4)).toBe(1);
  });

  it('never asks for more than there is, and ignores nonsense', () => {
    expect(visibleFilterCount({ name: 'k', filter_bar: true }, 1)).toBe(1);
    expect(visibleFilterCount({ name: 'k', filter_bar: true, visible_filters: 9 }, 4)).toBe(4);
    expect(visibleFilterCount({ name: 'k', filter_bar: true, visible_filters: 0 }, 4)).toBe(2);
    expect(visibleFilterCount({ name: 'k', filter_bar: true, visible_filters: 2.7 }, 4)).toBe(2);
    expect(visibleFilterCount(null, 3)).toBe(3);
    expect(visibleFilterCount({ name: 'k', filter_bar: true }, 0)).toBe(0);
  });
});

describe('stripControlKind', () => {
  it('maps each interactive type to its compact control', () => {
    expect(stripControlKind('MultiSelect')).toBe('categorical');
    expect(stripControlKind('Select')).toBe('categorical');
    expect(stripControlKind('SegmentedControl')).toBe('categorical');
    expect(stripControlKind('RangeSlider')).toBe('range');
    expect(stripControlKind('Slider')).toBe('slider');
    expect(stripControlKind('Switch')).toBe('toggle');
    expect(stripControlKind('Checkbox')).toBe('toggle');
    expect(stripControlKind('DateRangePicker')).toBe('date');
    expect(stripControlKind('DatePicker')).toBe('date');
    expect(stripControlKind('Timeline')).toBe('unsupported');
    expect(stripControlKind(undefined)).toBe('unsupported');
  });
});

describe('stripLabel / stripShowsIcon', () => {
  it('prefers the short label, falling back to the title', () => {
    expect(stripLabel(meta({ strip_label: 'Habitat' }), 'Sampling habitat')).toBe('Habitat');
    expect(stripLabel(meta({ strip_label: '  ' }), 'Sampling habitat')).toBe('Sampling habitat');
    expect(stripLabel(meta({}), 'Sampling habitat')).toBe('Sampling habitat');
  });

  it('shows the icon unless switched off', () => {
    expect(stripShowsIcon(meta({}))).toBe(true);
    expect(stripShowsIcon(meta({ strip_icon: null }))).toBe(true);
    expect(stripShowsIcon(meta({ strip_icon: false }))).toBe(false);
  });
});

describe('isFullRange', () => {
  it('is true only when both ends reach the extent', () => {
    expect(isFullRange([0, 10], 0, 10)).toBe(true);
    expect(isFullRange([-1, 11], 0, 10)).toBe(true);
    expect(isFullRange([0.5, 10], 0, 10)).toBe(false);
    expect(isFullRange([0, 9.5], 0, 10)).toBe(false);
  });
});

describe('sectionRuns', () => {
  const isStrip = (s: string) => s.startsWith('strip');

  it('puts each strip alone and groups what lies between', () => {
    expect(sectionRuns(['a', 'b', 'strip1', 'c', 'strip2', 'strip3'], isStrip)).toEqual([
      { strip: false, sections: ['a', 'b'] },
      { strip: true, section: 'strip1' },
      { strip: false, sections: ['c'] },
      { strip: true, section: 'strip2' },
      { strip: true, section: 'strip3' },
    ]);
  });

  it('is one run for a dashboard without strips', () => {
    expect(sectionRuns(['a', 'b'], isStrip)).toEqual([{ strip: false, sections: ['a', 'b'] }]);
    expect(sectionRuns([], isStrip)).toEqual([]);
  });
});

import { describe, expect, it } from 'vitest';

import type { FilterSectionSpec, StoredMetadata } from '../../../api';
import {
  isFullRange,
  isStripMember,
  isStripSection,
  partitionStripMembers,
  sectionRuns,
  stripControlKind,
  stripLabel,
  stripSectionNames,
  stripShowsIcon,
} from './stripLayout';

const meta = (extra: Partial<StoredMetadata>): StoredMetadata =>
  ({ index: 'x', component_type: 'interactive', ...extra }) as StoredMetadata;

const SECTIONS: FilterSectionSpec[] = [
  { name: 'Filters', display: 'strip' },
  { name: 'Key figures' },
  { name: 'Charts', display: 'grid' },
];

describe('stripSectionNames / isStripSection', () => {
  it('names only the sections drawn as a strip', () => {
    expect([...stripSectionNames(SECTIONS)]).toEqual(['Filters']);
    expect(isStripSection({ name: 'x', display: 'strip' })).toBe(true);
    expect(isStripSection({ name: 'x' })).toBe(false);
    expect(isStripSection(null)).toBe(false);
  });

  it('copes with no sections at all', () => {
    expect(stripSectionNames(undefined).size).toBe(0);
  });
});

describe('isStripMember', () => {
  const names = stripSectionNames(SECTIONS);

  it('takes an interactive component naming a strip section', () => {
    expect(isStripMember(meta({ section: 'Filters' }), names)).toBe(true);
  });

  it('leaves everything else where it was', () => {
    // Unsectioned, or in a section that is not a strip: the filter panel.
    expect(isStripMember(meta({}), names)).toBe(false);
    expect(isStripMember(meta({ section: 'Charts' }), names)).toBe(false);
    // Not interactive: a card in a strip section is still a grid tile.
    expect(isStripMember(meta({ component_type: 'card', section: 'Filters' }), names)).toBe(false);
    // The footer wins: a Timeline lifted to the top has no compact form.
    expect(isStripMember(meta({ section: 'Filters', placement: 'top' }), names)).toBe(false);
  });

  it('partitions in order', () => {
    const a = meta({ index: 'a', section: 'Filters' });
    const b = meta({ index: 'b' });
    const c = meta({ index: 'c', section: 'Filters' });
    const { strip, rest } = partitionStripMembers([a, b, c], names);
    expect(strip.map((m) => m.index)).toEqual(['a', 'c']);
    expect(rest.map((m) => m.index)).toEqual(['b']);
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

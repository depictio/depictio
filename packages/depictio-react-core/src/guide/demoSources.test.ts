import { describe, expect, it } from 'vitest';

import type { FilterSectionSpec, StoredMetadata } from '../api';
import { foldableSectionsOf, pickFilterDemo } from './demoSources';

const meta = (m: Partial<StoredMetadata> & { index: string; component_type: string }) =>
  m as StoredMetadata;

describe('pickFilterDemo', () => {
  const card = meta({ index: 'k', component_type: 'card', dc_id: 'meta' });
  const otherCard = meta({ index: 'k2', component_type: 'card', dc_id: 'taxa' });
  const slider = meta({
    index: 's',
    component_type: 'interactive',
    interactive_component_type: 'RangeSlider',
    dc_id: 'meta',
    column_name: 'depth',
  });
  const city = meta({
    index: 'c',
    component_type: 'interactive',
    interactive_component_type: 'MultiSelect',
    dc_id: 'meta',
    column_name: 'city',
  });

  it('pairs the first card with a categorical filter on its data', () => {
    expect(pickFilterDemo([otherCard, slider, card, city])).toEqual({ card, control: city });
  });

  it('takes any filter on the same data before one elsewhere', () => {
    expect(pickFilterDemo([card, slider])).toEqual({ card, control: slider });
  });

  it('falls back to the first card and filter, or nothing', () => {
    expect(pickFilterDemo([otherCard, city])).toEqual({ card: otherCard, control: city });
    expect(pickFilterDemo([city])).toBeNull();
    expect(pickFilterDemo([card])).toBeNull();
  });
});

describe('foldableSectionsOf', () => {
  const specs: FilterSectionSpec[] = [
    { name: 'Heading', appearance: 'plain' },
    { name: 'Bar', display: 'strip' } as FilterSectionSpec,
    { name: 'Box', appearance: 'box', icon: 'mdi:gauge' },
    { name: 'Empty' },
  ];
  it('keeps the named sections that fold and hold something', () => {
    const tiles = [
      meta({ index: 'a', component_type: 'text', section: 'Heading' }),
      meta({ index: 'b', component_type: 'interactive', section: 'Bar' }),
      meta({ index: 'c', component_type: 'card', section: 'Box' }),
      meta({ index: 'd', component_type: 'figure' }),
    ];
    const out = foldableSectionsOf(tiles, specs);
    expect(out.map((s) => [s.spec.name, s.members.map((m) => m.index)])).toEqual([
      ['Box', ['c']],
    ]);
  });
});

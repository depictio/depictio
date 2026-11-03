import { describe, expect, it } from 'vitest';

import { legendColumnOf, legendEntries } from './textLegend';

describe('legendEntries', () => {
  const source = {
    category_colors: { genome: { 'Sp_10': '#222222', 'Sp_2': '#111111' } },
    inherited_category_colors: { genome: { 'Sp_1': '#000000' }, group: { x: '#333333' } },
  };

  it('lists every pinned value, own and inherited, in natural order', () => {
    expect(legendEntries(source, 'genome').map((e) => e.label)).toEqual(['Sp_1', 'Sp_2', 'Sp_10']);
  });

  it('carries the pinned colour of each value', () => {
    expect(legendEntries(source, 'group')).toEqual([{ label: 'x', color: '#333333' }]);
  });

  it('draws no key for a column without pinned colours or without a source', () => {
    expect(legendEntries(source, 'size')).toEqual([]);
    expect(legendEntries(null, 'genome')).toEqual([]);
    expect(legendEntries(source, null)).toEqual([]);
  });
});

describe('legendColumnOf', () => {
  it('reads the column of a legend placeholder', () => {
    expect(legendColumnOf('{{legend:genome}}')).toBe('genome');
    expect(legendColumnOf('  {{legend:busco_class}}  ')).toBe('busco_class');
  });

  it('leaves any other value alone', () => {
    expect(legendColumnOf('3 genomes')).toBeNull();
    expect(legendColumnOf('{{n_genomes}}')).toBeNull();
    expect(legendColumnOf('{{legend:}}')).toBeNull();
  });
});

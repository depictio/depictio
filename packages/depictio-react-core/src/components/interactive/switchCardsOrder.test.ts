import { describe, expect, it } from 'vitest';

import { orderByDeclared } from './switchCardsOrder';

describe('orderByDeclared', () => {
  it('follows the declared order, not the alphabetical one', () => {
    expect(orderByDeclared(['pr2', 'silva'], ['silva', 'pr2'])).toEqual(['silva', 'pr2']);
  });

  it('puts values the YAML does not name after the declared ones, in their own order', () => {
    expect(orderByDeclared(['gtdb', 'pr2', 'rdp', 'silva'], ['silva', 'pr2'])).toEqual([
      'silva',
      'pr2',
      'gtdb',
      'rdp',
    ]);
  });

  it('skips a declared value the column does not hold', () => {
    expect(orderByDeclared(['pr2'], ['silva', 'pr2'])).toEqual(['pr2']);
  });

  it('does not touch its input', () => {
    const values = ['pr2', 'silva'];
    orderByDeclared(values, ['silva', 'pr2']);
    expect(values).toEqual(['pr2', 'silva']);
  });
});

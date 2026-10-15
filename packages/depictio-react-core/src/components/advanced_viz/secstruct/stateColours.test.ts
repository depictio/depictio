import { describe, expect, it } from 'vitest';

import { pinnedStateColours } from './stateColours';

describe('pinnedStateColours', () => {
  it('reads words and codes as the same classes', () => {
    expect(pinnedStateColours({ Helix: '#111', Strand: '#222', Coil: '#333' })).toEqual({
      helix: '#111',
      strand: '#222',
      coil: '#333',
    });
    expect(pinnedStateColours({ H: '#111', E: '#222' })).toEqual({ helix: '#111', strand: '#222' });
  });

  it('lets a later layer win class by class', () => {
    expect(pinnedStateColours({ Helix: '#111', Coil: '#333' }, { H: '#999' })).toEqual({
      helix: '#999',
      coil: '#333',
    });
  });

  it('ignores missing layers and values that are not states', () => {
    expect(pinnedStateColours(null, undefined, { pfam: '#111', Helix: '' })).toEqual({});
  });
});

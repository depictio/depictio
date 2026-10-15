import { describe, expect, it } from 'vitest';

import { effectiveStateColours, pinnedStateColours, withStateColour } from './stateColours';

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

describe('effectiveStateColours', () => {
  it('ranks the tile colour over the config over the pinned colours', () => {
    const pinned = [{ Helix: '#111', Strand: '#222', Coil: '#333' }];
    expect(effectiveStateColours(pinned, null, null)).toEqual({
      helix: '#111',
      strand: '#222',
      coil: '#333',
    });
    expect(effectiveStateColours(pinned, { Helix: '#aaa', Turn: '#bbb' }, null)).toEqual({
      helix: '#aaa',
      strand: '#222',
      turn: '#bbb',
      coil: '#333',
    });
    expect(
      effectiveStateColours(pinned, { Helix: '#aaa' }, { H: '#ccc', Coil: '#ddd' }),
    ).toEqual({ helix: '#ccc', strand: '#222', coil: '#ddd' });
  });

  it('leaves a class nobody colours out, for the default to fill', () => {
    expect(effectiveStateColours([], {}, {})).toEqual({});
    expect(effectiveStateColours([null], undefined, { Strand: '' })).toEqual({});
  });
});

describe('withStateColour', () => {
  it('sets one class and replaces any alias of it', () => {
    expect(withStateColour({ H: '#111', Strand: '#222' }, 'helix', '#999')).toEqual({
      Strand: '#222',
      Helix: '#999',
    });
    expect(withStateColour(undefined, 'coil', '#444')).toEqual({ Coil: '#444' });
  });

  it('clears a class given an empty colour', () => {
    expect(withStateColour({ Helix: '#111', Coil: '#333' }, 'helix', '')).toEqual({ Coil: '#333' });
  });
});

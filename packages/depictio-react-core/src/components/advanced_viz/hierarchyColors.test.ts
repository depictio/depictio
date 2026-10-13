import { describe, expect, it } from 'vitest';

import { isUnassigned, lineageShade, mixHex } from './hierarchyColors';

describe('mixHex', () => {
  it('moves a colour toward another, and leaves a non-hex one alone', () => {
    expect(mixHex('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mixHex('#c2255c', '#ffffff', 0)).toBe('#c2255c');
    expect(mixHex('#abc', '#fff', 1)).toBe('#ffffff');
    expect(mixHex('teal', '#ffffff', 0.5)).toBe('teal');
  });
});

describe('lineageShade', () => {
  it('keeps the lineage colour at its own level and lightens below it', () => {
    expect(lineageShade('#1098ad', 0, 3, false)).toBe('#1098ad');
    const child = lineageShade('#1098ad', 1, 0, false);
    const grandchild = lineageShade('#1098ad', 2, 0, false);
    const brightness = (h: string) => parseInt(h.slice(1, 3), 16) + parseInt(h.slice(3, 5), 16);
    expect(brightness(child)).toBeGreaterThan(brightness('#1098ad'));
    expect(brightness(grandchild)).toBeGreaterThan(brightness(child));
  });

  it('parts neighbouring siblings', () => {
    expect(lineageShade('#1098ad', 1, 0, false)).not.toBe(lineageShade('#1098ad', 1, 1, false));
  });
});

describe('isUnassigned', () => {
  it('knows the remainders, not the taxa', () => {
    expect(['Unclassified', 'unclassified_Bacteria', 'Other (12)', '', 'NA'].map(isUnassigned)).toEqual([
      true, true, true, true, true,
    ]);
    expect(['Bacteria', 'Otherwise', 'uncultured'].map(isUnassigned)).toEqual([false, false, false]);
  });
});

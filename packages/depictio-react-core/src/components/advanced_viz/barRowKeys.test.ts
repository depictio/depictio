import { describe, expect, it } from 'vitest';

import { barRowKeys } from './barRowKeys';

describe('barRowKeys', () => {
  it('keeps unique features as they are', () => {
    expect(barRowKeys(['a', 'b'])).toEqual(['a', 'b']);
  });
  it('gives a repeated feature its own row', () => {
    const keys = barRowKeys(['LYZ', 'CST3', 'LYZ', 'LYZ']);
    expect(new Set(keys).size).toBe(4);
    expect(keys[0]).toBe('LYZ');
    expect(keys[2].startsWith('LYZ')).toBe(true);
  });
});

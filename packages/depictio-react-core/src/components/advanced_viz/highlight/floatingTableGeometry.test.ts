import { describe, expect, it } from 'vitest';

import {
  DEFAULT_TABLE_SIZE,
  defaultGeometry,
  fitSize,
  initialPosition,
  parseGeometry,
  serializeGeometry,
  storageKey,
} from './floatingTableGeometry';

describe('parseGeometry', () => {
  it('falls back to the default for nothing or garbage', () => {
    expect(parseGeometry(null)).toEqual(defaultGeometry());
    expect(parseGeometry('not json')).toEqual(defaultGeometry());
    expect(parseGeometry('42')).toEqual(defaultGeometry());
  });

  it('round-trips a saved geometry', () => {
    const g = { x: 40, y: 60, width: 700, height: 500 };
    expect(parseGeometry(serializeGeometry(g))).toEqual(g);
  });

  it('drops a half-saved position and raises a tiny size', () => {
    const g = parseGeometry(JSON.stringify({ x: 10, width: 50, height: 'tall' }));
    expect(g.x).toBeNull();
    expect(g.y).toBeNull();
    expect(g.width).toBe(280);
    expect(g.height).toBe(DEFAULT_TABLE_SIZE.height);
  });
});

describe('placement', () => {
  it('fits a saved size to a smaller window', () => {
    expect(fitSize({ width: 1200, height: 900 }, { width: 800, height: 600 })).toEqual({
      width: 768,
      height: 568,
    });
  });

  it('starts bottom-right, clear of the corner furniture', () => {
    expect(initialPosition({ width: 560, height: 420 }, { width: 1440, height: 900 })).toEqual({
      x: 864,
      y: 408,
    });
  });

  it('keys storage per tile', () => {
    expect(storageKey('abc')).toBe('depictio:viz-table-panel:abc');
  });
});

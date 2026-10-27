import { describe, expect, it } from 'vitest';

import { shouldClearOnEscape } from './escapeClear';

const key = (over: Partial<Pick<KeyboardEvent, 'key' | 'defaultPrevented' | 'target'>> = {}) => ({
  key: 'Escape',
  defaultPrevented: false,
  target: null,
  ...over,
});

describe('shouldClearOnEscape', () => {
  it('clears on Escape over the tile or with the focus in it', () => {
    expect(shouldClearOnEscape(key(), true, false)).toBe(true);
    expect(shouldClearOnEscape(key(), false, true)).toBe(true);
  });
  it('ignores Escape away from the tile, another key, or one a dialog took', () => {
    expect(shouldClearOnEscape(key(), false, false)).toBe(false);
    expect(shouldClearOnEscape(key({ key: 'Enter' }), true, false)).toBe(false);
    expect(shouldClearOnEscape(key({ defaultPrevented: true }), true, false)).toBe(false);
  });
  it('leaves Escape to a field', () => {
    const field = { closest: (sel: string) => (sel.includes('input') ? {} : null), isContentEditable: false };
    expect(shouldClearOnEscape(key({ target: field as unknown as EventTarget }), true, true)).toBe(false);
  });
});

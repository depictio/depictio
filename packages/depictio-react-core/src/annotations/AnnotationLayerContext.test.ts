import { describe, expect, it } from 'vitest';

import { withAnnotatable } from './AnnotationLayerContext';

describe('withAnnotatable', () => {
  it('sets and clears a component flag', () => {
    const a = withAnnotatable({}, '1', true);
    expect(a).toEqual({ '1': true });
    expect(withAnnotatable(a, '1', false)).toEqual({});
  });
  it('keeps the same object when nothing changes', () => {
    const a = { '1': true };
    expect(withAnnotatable(a, '1', true)).toBe(a);
    expect(withAnnotatable(a, '2', false)).toBe(a);
  });
});

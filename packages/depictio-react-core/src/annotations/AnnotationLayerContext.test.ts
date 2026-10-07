import { describe, expect, it } from 'vitest';

import { initialPendingDraft, withAnnotatable } from './AnnotationLayerContext';

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

describe('initialPendingDraft', () => {
  it('starts with an empty label, the kind colour and the captured geometry', () => {
    const geometry = { kind: 'ref_line', axis: 'x', value: 3 } as const;
    expect(initialPendingDraft({ componentIndex: 'c', kind: 'line', geometry })).toEqual({
      label: '',
      color: 'red',
      geometry,
    });
  });
});

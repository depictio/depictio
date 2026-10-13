import { describe, expect, it } from 'vitest';

import { acceptSelectionEvent, nextSelectionRevision } from './selectionGesture';

describe('acceptSelectionEvent', () => {
  it('keeps a selection that caught points, gesture or not', () => {
    expect(acceptSelectionEvent({ points: [{}, {}] }, true)).toBe(true);
    expect(acceptSelectionEvent({ points: [{}] }, false)).toBe(true);
  });

  it('keeps an empty selection the reader drew', () => {
    expect(acceptSelectionEvent({ points: [] }, true)).toBe(true);
    expect(acceptSelectionEvent(undefined, true)).toBe(true);
  });

  it('drops the empty re-selection a re-render emits', () => {
    expect(acceptSelectionEvent({ points: [] }, false)).toBe(false);
    expect(acceptSelectionEvent({}, false)).toBe(false);
    expect(acceptSelectionEvent(null, false)).toBe(false);
  });
});

describe('nextSelectionRevision', () => {
  it('moves only when a selection that was there is gone', () => {
    expect(nextSelectionRevision(3, true, false)).toBe(4);
  });

  it('holds while a selection is drawn, kept or never made', () => {
    expect(nextSelectionRevision(3, false, true)).toBe(3);
    expect(nextSelectionRevision(3, true, true)).toBe(3);
    expect(nextSelectionRevision(3, false, false)).toBe(3);
  });
});

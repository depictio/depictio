import { describe, expect, it, vi } from 'vitest';

import { createViewWindowStore, sameViewWindow, viewWindowFor } from './viewWindow';

const win = (over = {}) => ({ sourceIndex: 'jb', entity: 'chr1', start: 10, end: 20, ...over });

describe('createViewWindowStore', () => {
  it('holds the last window and notifies only on a change', () => {
    const store = createViewWindowStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.publish(win());
    store.publish(win());
    expect(listener).toHaveBeenCalledTimes(1);
    store.publish(win({ end: 30 }));
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.get()).toEqual(win({ end: 30 }));
  });

  it('a sourced clear only removes that source window', () => {
    const store = createViewWindowStore();
    store.publish(win({ sourceIndex: 'a' }));
    store.publish(null, 'b');
    expect(store.get()?.sourceIndex).toBe('a');
    store.publish(null, 'a');
    expect(store.get()).toBeNull();
  });

  it('dispose drops the window and the listeners', () => {
    const store = createViewWindowStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.dispose();
    store.publish(win());
    expect(listener).not.toHaveBeenCalled();
  });
});

describe('viewWindowFor / sameViewWindow', () => {
  it('ignores the tile own window', () => {
    expect(viewWindowFor(win(), 'jb')).toBeNull();
    expect(viewWindowFor(win(), 'cov')).toEqual(win());
    expect(viewWindowFor(null, 'cov')).toBeNull();
  });

  it('compares every field', () => {
    expect(sameViewWindow(win(), win())).toBe(true);
    expect(sameViewWindow(win(), win({ entity: 'chr2' }))).toBe(false);
    expect(sameViewWindow(null, win())).toBe(false);
    expect(sameViewWindow(win({ entityAliases: ['a'] }), win({ entityAliases: ['a'] }))).toBe(true);
    expect(sameViewWindow(win({ entityAliases: ['a'] }), win({ entityAliases: ['b'] }))).toBe(false);
    expect(sameViewWindow(win({ entityAliases: ['a'] }), win())).toBe(false);
  });
});

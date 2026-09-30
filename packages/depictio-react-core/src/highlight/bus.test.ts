import { describe, expect, it, vi } from 'vitest';

import { createHighlightBus, highlightFor, sameHighlight, type HighlightScheduler } from './bus';

/** A manual frame clock: `tick()` runs the queued frame. */
function manualFrames() {
  let queued: (() => void) | null = null;
  const scheduler: HighlightScheduler = {
    schedule: (cb) => {
      queued = cb;
      return 1;
    },
    cancel: () => {
      queued = null;
    },
  };
  const tick = () => {
    const cb = queued;
    queued = null;
    cb?.();
  };
  return { scheduler, tick, pending: () => queued !== null };
}

describe('createHighlightBus', () => {
  it('coalesces publishes to one notification per frame, last event wins', () => {
    const { scheduler, tick } = manualFrames();
    const bus = createHighlightBus(scheduler);
    const listener = vi.fn();
    bus.subscribe(listener);
    bus.publish({ sourceIndex: 'a', start: 1 });
    bus.publish({ sourceIndex: 'a', start: 2 });
    bus.publish({ sourceIndex: 'a', start: 3, end: 5 });
    expect(bus.get()).toBeNull();
    expect(listener).not.toHaveBeenCalled();
    tick();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(bus.get()).toEqual({ sourceIndex: 'a', start: 3, end: 5 });
  });

  it('defaults end to start and skips a frame that changes nothing', () => {
    const { scheduler, tick } = manualFrames();
    const bus = createHighlightBus(scheduler);
    const listener = vi.fn();
    bus.subscribe(listener);
    bus.publish({ sourceIndex: 'a', entity: 'P1', start: 4 });
    tick();
    expect(bus.get()).toEqual({ sourceIndex: 'a', entity: 'P1', start: 4, end: 4 });
    bus.publish({ sourceIndex: 'a', entity: 'P1', start: 4, end: 4 });
    tick();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('a sourced clear only removes that source', () => {
    const { scheduler, tick } = manualFrames();
    const bus = createHighlightBus(scheduler);
    bus.publish({ sourceIndex: 'a', start: 1 });
    tick();
    // Pointer moved from tile a to tile b: b's enter lands before a's leave.
    bus.publish({ sourceIndex: 'b', start: 9 });
    bus.publish(null, 'a');
    tick();
    expect(bus.get()?.sourceIndex).toBe('b');
    bus.publish(null, 'a');
    tick();
    expect(bus.get()?.sourceIndex).toBe('b');
    bus.publish(null, 'b');
    tick();
    expect(bus.get()).toBeNull();
  });

  it('an unsourced clear always clears', () => {
    const { scheduler, tick } = manualFrames();
    const bus = createHighlightBus(scheduler);
    bus.publish({ sourceIndex: 'a', start: 1 });
    tick();
    bus.publish(null);
    tick();
    expect(bus.get()).toBeNull();
  });

  it('unsubscribe and dispose stop notifications and cancel the pending frame', () => {
    const { scheduler, tick, pending } = manualFrames();
    const bus = createHighlightBus(scheduler);
    const listener = vi.fn();
    const off = bus.subscribe(listener);
    off();
    bus.publish({ sourceIndex: 'a', start: 1 });
    tick();
    expect(listener).not.toHaveBeenCalled();
    bus.subscribe(listener);
    bus.publish({ sourceIndex: 'a', start: 2 });
    bus.dispose();
    expect(pending()).toBe(false);
    expect(bus.get()).toBeNull();
    expect(listener).not.toHaveBeenCalled();
  });
});

describe('highlightFor / sameHighlight', () => {
  it('ignores the tile own events', () => {
    const ev = { sourceIndex: 'a', start: 1 };
    expect(highlightFor(ev, 'a')).toBeNull();
    expect(highlightFor(ev, 'b')).toBe(ev);
    expect(highlightFor(ev, undefined)).toBe(ev);
    expect(highlightFor(null, 'b')).toBeNull();
  });

  it('tells the chains of a complex apart', () => {
    expect(
      sameHighlight({ sourceIndex: 'a', start: 5, chain: 'A' }, { sourceIndex: 'a', start: 5, chain: 'B' }),
    ).toBe(false);
    expect(
      sameHighlight({ sourceIndex: 'a', start: 5, chain: 'A' }, { sourceIndex: 'a', start: 5, chain: 'A' }),
    ).toBe(true);
  });

  it('compares rows and the defaulted end', () => {
    expect(sameHighlight({ sourceIndex: 'a', start: 1 }, { sourceIndex: 'a', start: 1, end: 1 })).toBe(true);
    expect(
      sameHighlight(
        { sourceIndex: 'a', start: 1, rowKeys: ['x'] },
        { sourceIndex: 'a', start: 1, rowKeys: ['y'] },
      ),
    ).toBe(false);
    expect(sameHighlight(null, { sourceIndex: 'a', start: 1 })).toBe(false);
  });
});

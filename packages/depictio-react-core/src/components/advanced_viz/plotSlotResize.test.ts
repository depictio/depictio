import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLOT_RESIZE_DEBOUNCE_MS, observeResize } from './plotSlotResize';

/** A ResizeObserver the test drives by hand, and a node whose size it sets. */
function harness() {
  const size = { width: 400, height: 300 };
  const node = { getBoundingClientRect: () => ({ ...size }) } as unknown as Element;
  let fire: () => void = () => undefined;
  const disconnect = vi.fn();
  class MockObserver {
    constructor(cb: () => void) {
      fire = cb;
    }
    observe() {
      // A real observer reports once on observe, with the size at mount.
      fire();
    }
    disconnect = disconnect;
  }
  const resizeTo = (width: number, height: number) => {
    size.width = width;
    size.height = height;
    fire();
  };
  return { node, Observer: MockObserver, resizeTo, fire: () => fire(), disconnect };
}

describe('observeResize', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('treats the size at mount as the baseline, not a change', () => {
    const h = harness();
    const onResize = vi.fn();
    observeResize(h.node, onResize, { Observer: h.Observer });
    vi.advanceTimersByTime(PLOT_RESIZE_DEBOUNCE_MS * 2);
    expect(onResize).not.toHaveBeenCalled();
  });

  it('fires once, after the debounce, for a burst of changes', () => {
    const h = harness();
    const onResize = vi.fn();
    observeResize(h.node, onResize, { Observer: h.Observer });
    h.resizeTo(400, 260); // the header strip appears
    h.resizeTo(400, 240); // and wraps to a second line
    vi.advanceTimersByTime(PLOT_RESIZE_DEBOUNCE_MS - 1);
    expect(onResize).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onResize).toHaveBeenCalledTimes(1);
  });

  it('ignores sub-pixel jitter', () => {
    const h = harness();
    const onResize = vi.fn();
    observeResize(h.node, onResize, { Observer: h.Observer });
    h.resizeTo(400.4, 300.3);
    h.fire();
    vi.advanceTimersByTime(PLOT_RESIZE_DEBOUNCE_MS * 2);
    expect(onResize).not.toHaveBeenCalled();
  });

  it('reports a width change, which is what the side rail does', () => {
    const h = harness();
    const onResize = vi.fn();
    observeResize(h.node, onResize, { Observer: h.Observer });
    h.resizeTo(180, 300);
    vi.advanceTimersByTime(PLOT_RESIZE_DEBOUNCE_MS);
    expect(onResize).toHaveBeenCalledTimes(1);
  });

  it('disconnects and drops a pending resize on teardown', () => {
    const h = harness();
    const onResize = vi.fn();
    const stop = observeResize(h.node, onResize, { Observer: h.Observer });
    h.resizeTo(400, 200);
    stop();
    vi.advanceTimersByTime(PLOT_RESIZE_DEBOUNCE_MS * 2);
    expect(onResize).not.toHaveBeenCalled();
    expect(h.disconnect).toHaveBeenCalledTimes(1);
  });

  it('is a no-op where ResizeObserver does not exist', () => {
    const node = { getBoundingClientRect: () => ({ width: 1, height: 1 }) } as unknown as Element;
    const stop = observeResize(node, vi.fn());
    expect(() => stop()).not.toThrow();
  });
});

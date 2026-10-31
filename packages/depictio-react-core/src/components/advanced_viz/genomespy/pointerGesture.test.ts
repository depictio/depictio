import { describe, expect, it } from 'vitest';

import { attachDragTracker, brushToPublish, isDrag } from './pointerGesture';
import type { DragTarget } from './pointerGesture';

describe('isDrag', () => {
  it('is a drag from 3 px, a click below', () => {
    expect(isDrag({ x: 10, y: 10 }, { x: 10, y: 10 })).toBe(false);
    expect(isDrag({ x: 10, y: 10 }, { x: 12, y: 11 })).toBe(false);
    expect(isDrag({ x: 10, y: 10 }, { x: 13, y: 10 })).toBe(true);
    expect(isDrag(null, { x: 1, y: 1 })).toBe(false);
  });
});

describe('brushToPublish', () => {
  const domain: [number, number] = [0, 1000];

  it('passes a deliberate drag, ordered', () => {
    expect(brushToPublish([200, 400], domain)).toEqual([200, 400]);
    expect(brushToPublish([400, 200], domain)).toEqual([200, 400]);
  });

  it('drops an emptied brush: a click or a programmatic clear is not a region', () => {
    expect(brushToPublish(null, domain)).toBeNull();
    expect(brushToPublish([], domain)).toBeNull();
  });

  it('drops a zero-width or jittering brush', () => {
    expect(brushToPublish([300, 300], domain)).toBeNull();
    expect(brushToPublish([300, 302], domain)).toBeNull();
    expect(brushToPublish([300, 306], domain)).toEqual([300, 306]);
  });

  it('takes any positive width when the domain is unknown', () => {
    expect(brushToPublish([1, 2], null)).toEqual([1, 2]);
    expect(brushToPublish([Number.NaN, 2], null)).toBeNull();
  });
});

function fakeTarget() {
  const handlers = new Map<string, (e: MouseEvent) => void>();
  const docHandlers = new Map<string, (e: MouseEvent) => void>();
  const el: DragTarget = {
    ownerDocument: {
      addEventListener: (t, fn) => void docHandlers.set(t, fn),
      removeEventListener: (t) => void docHandlers.delete(t),
    },
    addEventListener: (t, fn) => void handlers.set(t, fn),
    removeEventListener: (t) => void handlers.delete(t),
  };
  const ev = (x: number, y: number, button = 0) => ({ clientX: x, clientY: y, button }) as MouseEvent;
  return { el, handlers, docHandlers, ev };
}

describe('attachDragTracker', () => {
  it('says a click that moved was a drag, and a still one was not', () => {
    const { el, handlers, docHandlers, ev } = fakeTarget();
    const t = attachDragTracker(el);
    handlers.get('mousedown')!(ev(50, 50));
    docHandlers.get('mouseup')!(ev(120, 52));
    expect(t.wasDrag()).toBe(true);
    handlers.get('mousedown')!(ev(50, 50));
    docHandlers.get('mouseup')!(ev(51, 50));
    expect(t.wasDrag()).toBe(false);
  });

  it('ignores other buttons and removes its listeners', () => {
    const { el, handlers, docHandlers, ev } = fakeTarget();
    const t = attachDragTracker(el);
    handlers.get('mousedown')!(ev(0, 0, 2));
    docHandlers.get('mouseup')!(ev(90, 0));
    expect(t.wasDrag()).toBe(false);
    t.detach();
    expect(handlers.size).toBe(0);
    expect(docHandlers.size).toBe(0);
  });
});

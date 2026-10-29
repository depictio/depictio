import { describe, expect, it } from 'vitest';

import {
  attachInteractionMode,
  brushTrigger,
  initialInteractionMode,
  isTypingTarget,
  laneCursor,
  modeForKey,
  modeHint,
  specInteractionMode,
  wheelZooms,
} from './interactionMode';

describe('initialInteractionMode', () => {
  it('opens as a plain pointer when the tile says nothing', () => {
    expect(initialInteractionMode({})).toBe('pointer');
    expect(initialInteractionMode({ interaction_mode: null, drag_mode: null })).toBe('pointer');
  });

  it('keeps the older drag_mode as the opening mode', () => {
    expect(initialInteractionMode({ drag_mode: 'pan' })).toBe('pan');
    expect(initialInteractionMode({ drag_mode: 'select' })).toBe('select');
  });

  it('lets interaction_mode win over drag_mode', () => {
    expect(initialInteractionMode({ interaction_mode: 'pointer', drag_mode: 'pan' })).toBe('pointer');
    expect(initialInteractionMode({ interaction_mode: 'select', drag_mode: 'pan' })).toBe('select');
  });
});

describe('specInteractionMode', () => {
  it('builds the brush spec a config that names no mode always had', () => {
    expect(specInteractionMode({})).toBe('select');
    expect(specInteractionMode({ drag_mode: 'pan' })).toBe('pan');
    expect(specInteractionMode({ interaction_mode: 'pointer' })).toBe('pointer');
  });
});

describe('what a mode means', () => {
  it('brushes on a plain drag only in select mode', () => {
    expect(brushTrigger('select')).toBe('mousedown');
    expect(brushTrigger('pan')).toEqual({ type: 'mousedown', filter: 'event.shiftKey' });
    expect(brushTrigger('pointer')).toEqual({ type: 'mousedown', filter: 'false' });
  });

  it('shows the arrow in pointer mode and a tool cursor in the others', () => {
    expect(laneCursor('pointer')).toBeUndefined();
    expect(laneCursor('pan')).toBe('grab');
    expect(laneCursor('select')).toBe('crosshair');
  });

  it('gives the wheel to the zoom in pan mode only', () => {
    expect(wheelZooms('pan')).toBe(true);
    expect(wheelZooms('pointer')).toBe(false);
    expect(wheelZooms('select')).toBe(false);
  });

  it('names what a drag does in the hint, and says when select is off', () => {
    expect(modeHint('select', true)).toMatch(/select/);
    expect(modeHint('select', false)).toMatch(/off/);
    expect(modeHint('pan', true)).toMatch(/pan/);
    expect(modeHint('pointer', true)).toMatch(/pan or select/);
    expect(modeHint('pointer', false)).not.toMatch(/select/);
  });
});

/** A document and a container that record their listeners and let a test fire
 *  events through them in the order the browser would: capture on the document,
 *  then the target's. */
function fakeDom() {
  type Fn = (e: any) => void;
  const docListeners: Record<string, Fn[]> = {};
  const elListeners: Record<string, Fn[]> = {};
  const doc = {
    addEventListener: (type: string, fn: Fn) => (docListeners[type] ??= []).push(fn),
    removeEventListener: (type: string, fn: Fn) => {
      docListeners[type] = (docListeners[type] ?? []).filter((f) => f !== fn);
    },
  };
  const el = {
    ownerDocument: doc,
    addEventListener: (type: string, fn: Fn) => (elListeners[type] ??= []).push(fn),
    removeEventListener: (type: string, fn: Fn) => {
      elListeners[type] = (elListeners[type] ?? []).filter((f) => f !== fn);
    },
  };
  /** Fire a mousemove; returns how many of GenomeSpy's own listeners saw it. */
  const move = (buttons: number) => {
    let stopped = false;
    const ev = { buttons, stopImmediatePropagation: () => (stopped = true) };
    let seen = 0;
    for (const fn of [...(docListeners.mousemove ?? [])]) {
      if (stopped) break;
      fn(ev);
    }
    // GenomeSpy's listener sits after ours, on the document.
    if (!stopped) seen += 1;
    return seen;
  };
  const down = (button = 0) => {
    for (const fn of elListeners.mousedown ?? []) fn({ button });
  };
  const up = () => {
    for (const fn of [...(docListeners.mouseup ?? [])]) fn({});
  };
  return { el, doc, docListeners, elListeners, move, down, up };
}

describe('attachInteractionMode', () => {
  it('keeps a drag from reaching the pan in pointer mode, until the button is up', () => {
    const dom = fakeDom();
    attachInteractionMode(dom.el, 'pointer');
    // A hover before any press passes.
    expect(dom.move(0)).toBe(1);
    dom.down();
    expect(dom.move(1)).toBe(0);
    expect(dom.move(1)).toBe(0);
    dom.up();
    expect(dom.move(0)).toBe(1);
    expect(dom.docListeners.mousemove ?? []).toHaveLength(0);
  });

  it('lets a press and release with no move between them be the click it is', () => {
    const dom = fakeDom();
    attachInteractionMode(dom.el, 'pointer');
    dom.down();
    dom.up();
    expect(dom.move(0)).toBe(1);
  });

  it('stops freezing when the release was missed (no button held)', () => {
    const dom = fakeDom();
    attachInteractionMode(dom.el, 'pointer');
    dom.down();
    expect(dom.move(0)).toBe(1);
    expect(dom.docListeners.mousemove ?? []).toHaveLength(0);
  });

  it('ignores any press but the primary button', () => {
    const dom = fakeDom();
    attachInteractionMode(dom.el, 'pointer');
    dom.down(2);
    expect(dom.move(2)).toBe(1);
  });

  it('adds nothing in pan or select mode, and removes itself when detached', () => {
    const pan = fakeDom();
    attachInteractionMode(pan.el, 'pan');
    expect(pan.elListeners.mousedown ?? []).toHaveLength(0);
    const select = fakeDom();
    attachInteractionMode(select.el, 'select')();
    expect(select.elListeners.mousedown ?? []).toHaveLength(0);

    const pointer = fakeDom();
    const detach = attachInteractionMode(pointer.el, 'pointer');
    pointer.down();
    detach();
    expect(pointer.elListeners.mousedown ?? []).toHaveLength(0);
    expect(pointer.docListeners.mousemove ?? []).toHaveLength(0);
    expect(pointer.docListeners.mouseup ?? []).toHaveLength(0);
  });
});

describe('modeForKey', () => {
  it('maps V, H and M to the three modes, in either case', () => {
    expect(modeForKey({ key: 'v' }, true)).toBe('pointer');
    expect(modeForKey({ key: 'H' }, true)).toBe('pan');
    expect(modeForKey({ key: 'm' }, true)).toBe('select');
  });

  it('ignores other keys and keys with a modifier', () => {
    expect(modeForKey({ key: 'x' }, true)).toBeNull();
    expect(modeForKey({ key: 'v', metaKey: true }, true)).toBeNull();
    expect(modeForKey({ key: 'h', ctrlKey: true }, true)).toBeNull();
  });

  it('offers no Select on a tile that cannot take a region', () => {
    expect(modeForKey({ key: 'm' }, false)).toBeNull();
  });
});

describe('isTypingTarget', () => {
  it('is true for fields and false for plain elements', () => {
    expect(isTypingTarget({ tagName: 'INPUT', isContentEditable: false } as unknown as EventTarget)).toBe(true);
    expect(isTypingTarget({ tagName: 'DIV', isContentEditable: false } as unknown as EventTarget)).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

import { describe, expect, it } from 'vitest';

import {
  CONTROLS_VIEWS,
  currentView,
  isControlsPlacement,
  parseChoice,
  pickEssentials,
  placementForView,
  resolveControls,
  resolveDock,
  serializeChoice,
  type ControlsChoice,
} from './controlsDock';

const full = { rowShare: 1, width: 1100, showcase: false };
const half = { rowShare: 0.5, width: 540, showcase: false };

describe('resolveDock', () => {
  it('docks beside a full-width tile and above a narrower one', () => {
    expect(resolveDock(null, full)).toBe('right');
    expect(resolveDock('auto', half)).toBe('top');
  });

  it('keeps a full-width tile on a phone-width grid on top', () => {
    expect(resolveDock(null, { rowShare: 1, width: 380, showcase: false })).toBe('top');
  });

  it('leaves the controls behind the icon where docking does not fit or is not wanted', () => {
    expect(resolveDock(null, { rowShare: 0.25, width: 260, showcase: false })).toBeNull();
    expect(resolveDock(null, { ...full, showcase: true })).toBeNull();
    expect(resolveDock(null, { rowShare: null, width: 900, showcase: false })).toBeNull();
    expect(resolveDock('popover', full)).toBeNull();
  });

  it('floats an overlay instead of docking it, whatever the tile', () => {
    expect(resolveDock('overlay', full)).toBeNull();
    expect(resolveDock('overlay', half)).toBeNull();
    expect(resolveDock('overlay', { rowShare: null, width: 0, showcase: true })).toBeNull();
  });

  it('follows an explicit side whatever the width', () => {
    expect(resolveDock('right', half)).toBe('right');
    expect(resolveDock('top', full)).toBe('top');
    expect(resolveDock('top', { rowShare: null, width: 0, showcase: true })).toBe('top');
  });
});

describe('pickEssentials', () => {
  it('keeps the first live controls, skipping what is off or disabled', () => {
    expect(pickEssentials([true, false, true, true, true])).toEqual([true, false, true, true, false]);
    expect(pickEssentials([false, false], 3)).toEqual([false, false]);
    expect(pickEssentials([true, true], 3)).toEqual([true, true]);
  });
});

describe('isControlsPlacement', () => {
  it('knows every placement the component accepts, overlay included', () => {
    for (const p of ['auto', 'right', 'top', 'popover', 'overlay']) {
      expect(isControlsPlacement(p), p).toBe(true);
    }
  });

  it('refuses anything else, including the config-level values', () => {
    for (const p of ['rail', 'header', 'left', '', null, undefined, 3]) {
      expect(isControlsPlacement(p), String(p)).toBe(false);
    }
  });
});

describe('the stored choice of view', () => {
  it('reads the old fold values as before', () => {
    expect(parseChoice('1')).toBe('hidden');
    expect(parseChoice('0')).toBe('open');
  });

  it('reads the views the menu adds, and nothing it does not know', () => {
    expect(parseChoice('overlay')).toBe('overlay');
    expect(parseChoice('top')).toBe('top');
    expect(parseChoice('right')).toBe('right');
    for (const raw of [null, undefined, '', 'popover', 'auto', 'hidden', 'open', '2']) {
      expect(parseChoice(raw), String(raw)).toBeNull();
    }
  });

  it('writes the old values for the old choices, so an older reader still reads them', () => {
    expect(serializeChoice('hidden')).toBe('1');
    expect(serializeChoice('open')).toBe('0');
  });

  it('round-trips every choice', () => {
    const all: ControlsChoice[] = ['hidden', 'open', 'overlay', 'top', 'right'];
    for (const c of all) expect(parseChoice(serializeChoice(c)), c).toBe(c);
  });
});

describe('resolveControls', () => {
  it('folds a workbench cell the author left unsaid, and opens everything else', () => {
    expect(resolveControls(null, null, true)).toEqual({ placement: null, collapsed: true });
    expect(resolveControls(null, null, false)).toEqual({ placement: null, collapsed: false });
  });

  it('starts a stated placement open, overlay included', () => {
    for (const p of ['auto', 'right', 'top', 'popover', 'overlay'] as const) {
      expect(resolveControls(null, p, true), p).toEqual({ placement: p, collapsed: false });
    }
  });

  it('lets a picked view win over the component, at any density', () => {
    expect(resolveControls('right', 'popover', true)).toEqual({
      placement: 'right',
      collapsed: false,
    });
    expect(resolveControls('overlay', 'top', false)).toEqual({
      placement: 'overlay',
      collapsed: false,
    });
  });

  it('folds on hidden but keeps the component placement for when it opens again', () => {
    expect(resolveControls('hidden', 'right', false)).toEqual({
      placement: 'right',
      collapsed: true,
    });
    expect(resolveControls('open', 'right', true)).toEqual({
      placement: 'right',
      collapsed: false,
    });
  });
});

describe('the menu views', () => {
  it('lists hidden, overlay, top, right in that order', () => {
    expect([...CONTROLS_VIEWS]).toEqual(['hidden', 'overlay', 'top', 'right']);
  });

  it('saves a view as the placement it stands for, which the component accepts', () => {
    expect(placementForView('hidden')).toBe('popover');
    for (const v of CONTROLS_VIEWS) expect(isControlsPlacement(placementForView(v)), v).toBe(true);
  });

  it('checks what is on screen: folded or undockable is hidden', () => {
    expect(currentView(false, 'right', false)).toBe('right');
    expect(currentView(false, 'top', false)).toBe('top');
    expect(currentView(true, null, false)).toBe('overlay');
    expect(currentView(false, null, false)).toBe('hidden');
    expect(currentView(true, null, true)).toBe('hidden');
    expect(currentView(false, 'right', true)).toBe('hidden');
  });
});

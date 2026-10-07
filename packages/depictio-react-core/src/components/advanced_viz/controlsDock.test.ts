import { describe, expect, it } from 'vitest';

import { pickEssentials, resolveDock } from './controlsDock';

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

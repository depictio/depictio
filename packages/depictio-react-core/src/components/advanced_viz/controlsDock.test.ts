import { describe, expect, it } from 'vitest';

import {
  DOCK_ESSENTIALS,
  DOCK_TOP_MAX,
  fitInline,
  pickEssentials,
  planGroup,
  resolveDock,
  rowControlWidth,
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

describe('fitInline', () => {
  const live4 = [true, true, true, true];

  it('keeps every control when the line holds them all, reserving nothing', () => {
    // 100 + 12 + 100 + 12 + 100 = 324: fits 324 exactly without a More button.
    expect(fitInline([100, 100, 100], [true, true, true], 324, { gap: 12, reserve: 90 })).toEqual([
      true,
      true,
      true,
    ]);
  });

  it('reserves room for "More options" once anything is folded', () => {
    // Without the reserve three would fit (324 <= 330); with it only two do.
    expect(fitInline([100, 100, 100, 100], live4, 330, { gap: 12, reserve: 90 })).toEqual([
      true,
      true,
      false,
      false,
    ]);
  });

  it('reserves for a control that is off, which folds whatever the width', () => {
    expect(fitInline([100, 100, 100], [true, true, false], 400, { gap: 12, reserve: 200 })).toEqual(
      [true, false, false],
    );
  });

  it('stops at the first control that does not fit instead of skipping ahead', () => {
    // The wide second control does not fit; the narrow third must not jump it.
    expect(fitInline([80, 300, 40], [true, true, true], 200, { gap: 10 })).toEqual([
      true,
      false,
      false,
    ]);
  });

  it('skips controls that are off without spending width on them', () => {
    expect(fitInline([100, 500, 100], [true, false, true], 260, { gap: 10, reserve: 40 })).toEqual(
      [true, false, true],
    );
  });

  it('always keeps the first live control, even alone too wide for the line', () => {
    const lone = fitInline([400, 50], [true, true], 120, { gap: 10, reserve: 60 });
    expect(lone).toEqual([true, false]);
    expect(fitInline([400, 50], [false, true], 0)).toEqual([false, true]);
  });

  it('caps the count whatever the width', () => {
    expect(fitInline([10, 10, 10, 10], live4, 10_000, { max: 2 })).toEqual([
      true,
      true,
      false,
      false,
    ]);
    expect(DOCK_TOP_MAX).toBeGreaterThanOrEqual(DOCK_ESSENTIALS);
  });

  it('treats an unmeasured width as zero and an empty panel as empty', () => {
    expect(fitInline([Number.NaN, 50], [true, true], 60, { gap: 10 })).toEqual([true, true]);
    expect(fitInline([], [], 500)).toEqual([]);
  });
});

describe('rowControlWidth', () => {
  it('narrows a column width to about two thirds, never under 56 px', () => {
    expect(rowControlWidth(110)).toBe(72);
    expect(rowControlWidth(140)).toBe(91);
    expect(rowControlWidth(40)).toBe(56);
  });

  it('leaves content-sized controls content-sized', () => {
    expect(rowControlWidth('auto')).toBe('auto');
    expect(rowControlWidth('fill')).toBe('auto');
  });
});

describe('planGroup', () => {
  it('draws no caption on the line, so groups never stack the line', () => {
    expect(planGroup('Lines', ['Line width', 'Band opacity'], 'row')).toEqual({
      caption: null,
      adoptTitle: false,
    });
  });

  it("hands a lone unlabelled control the group's title on the line", () => {
    expect(planGroup('View', [null], 'row')).toEqual({ caption: null, adoptTitle: true });
    expect(planGroup('View', ['  '], 'row').adoptTitle).toBe(true);
    expect(planGroup('View', [null, null], 'row').adoptTitle).toBe(false);
    expect(planGroup('Legend', ['Legend'], 'row').adoptTitle).toBe(false);
  });

  it('drops a stacked caption that only repeats its one control', () => {
    expect(planGroup('Legend', ['Legend'], 'stack').caption).toBeNull();
    expect(planGroup('Legend', [' legend '], 'stack').caption).toBeNull();
  });

  it('keeps a stacked caption that says something its controls do not', () => {
    expect(planGroup('Legend', ['Position'], 'stack').caption).toBe('Legend');
    expect(planGroup('Legend', ['Legend', 'Size'], 'stack').caption).toBe('Legend');
    expect(planGroup('Axes', [null], 'stack')).toEqual({ caption: 'Axes', adoptTitle: false });
  });
});

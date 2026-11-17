import { describe, expect, it, vi } from 'vitest';

import {
  DISPLAY_SETTINGS,
  applyAll,
  applySetting,
  clampValue,
  displayKeys,
  displaysOf,
  entryFor,
  groupsFor,
  openDisplayTypes,
  resolveAll,
  resolveValue,
  restoreBaseline,
  sanitizeValue,
  type Baselines,
  type DisplaySettingEntry,
  type Model,
} from './displaySettings';

const entry = (key: Parameters<typeof entryFor>[0]): DisplaySettingEntry => {
  const found = entryFor(key);
  if (!found) throw new Error(`no entry ${key}`);
  return found;
};

/** A pileup panel whose toggles flip a stored override, like the real ones. */
function fakePileup(over: Model = {}) {
  const pileup: Model = {
    type: 'LinearPileupDisplay',
    id: 'p1',
    showSoftClipping: false,
    mismatchAlphaSetting: false,
    featureHeightSetting: 7,
    noSpacingSetting: false,
    setColorScheme: vi.fn(),
    setFeatureHeight: vi.fn(),
    setNoSpacing: vi.fn(),
    setHideSmallIndels: vi.fn(),
    ...over,
  };
  pileup.toggleSoftClipping = vi.fn(() => {
    pileup.showSoftClipping = !pileup.showSoftClipping;
  });
  pileup.toggleMismatchAlpha = vi.fn(() => {
    pileup.mismatchAlphaSetting = !pileup.mismatchAlphaSetting;
  });
  return pileup;
}

function fakeAlignments(pileup: Model = fakePileup(), over: Model = {}): Model {
  return {
    type: 'LinearAlignmentsDisplay',
    id: 'a1',
    PileupDisplay: pileup,
    SNPCoverageDisplay: {
      type: 'LinearSNPCoverageDisplay',
      id: 'c1',
      setShowArcs: vi.fn(),
      setHeight: vi.fn(),
    },
    setSNPCoverageHeight: vi.fn(),
    setLowerPanelType: vi.fn(),
    ...over,
  };
}

const fakeView = (displays: Model[]): Model => ({
  tracks: displays.map((d) => ({ displays: [d] })),
  setShowCenterLine: vi.fn(),
  setShowGridlines: vi.fn(),
  setShowCytobands: vi.fn(),
  setShowTrackOutlines: vi.fn(),
  setColorByCDS: vi.fn(),
  setTrackLabels: vi.fn(),
});

describe('resolveValue', () => {
  it('prefers this tile\'s choice over the YAML', () => {
    expect(resolveValue('scale', { scale: 'log' }, { scale: 'linear' })).toBe('log');
  });

  it('falls back to the YAML, then to nothing (JBrowse\'s default)', () => {
    expect(resolveValue('scale', {}, { scale: 'log' })).toBe('log');
    expect(resolveValue('scale', {}, {})).toBeUndefined();
    expect(resolveValue('scale', null, undefined)).toBeUndefined();
  });

  it('keeps a false from the tile over a true from the YAML', () => {
    expect(resolveValue('soft_clipping', { soft_clipping: false }, { soft_clipping: true })).toBe(
      false,
    );
  });
});

describe('resolveAll', () => {
  it('gives every view setting its built-in default, nothing else', () => {
    const all = resolveAll({}, {});
    expect(all).toEqual({
      center_line: false,
      gridlines: true,
      cytobands: true,
      track_outlines: true,
      color_by_cds: false,
      track_labels: 'overlapping',
    });
  });

  it('lets local and YAML override the built-ins, and clamps numbers', () => {
    const all = resolveAll({ coverage_height: 9000, center_line: true }, { gridlines: false });
    expect(all.center_line).toBe(true);
    expect(all.gridlines).toBe(false);
    expect(all.coverage_height).toBe(2000);
  });
});

describe('sanitizeValue and clampValue', () => {
  it('accepts only what the control could produce', () => {
    expect(sanitizeValue(entry('scale'), 'log')).toBe('log');
    expect(sanitizeValue(entry('scale'), 'sqrt')).toBeUndefined();
    expect(sanitizeValue(entry('soft_clipping'), 'yes')).toBeUndefined();
    expect(sanitizeValue(entry('variant_row_height'), 80)).toBe(50);
    expect(sanitizeValue(entry('variant_row_height'), Number.NaN)).toBeUndefined();
    expect(clampValue(entry('scale'), 'log')).toBe('log');
  });
});

describe('toggle settings', () => {
  it('flips soft clipping only when the read differs', () => {
    const pileup = fakePileup();
    const view = fakeView([fakeAlignments(pileup)]);
    applySetting(view, entry('soft_clipping'), true, {});
    expect(pileup.toggleSoftClipping).toHaveBeenCalledTimes(1);
    applySetting(view, entry('soft_clipping'), true, {});
    expect(pileup.toggleSoftClipping).toHaveBeenCalledTimes(1);
    applySetting(view, entry('soft_clipping'), false, {});
    expect(pileup.toggleSoftClipping).toHaveBeenCalledTimes(2);
  });

  it('does not touch mismatch alpha that already matches', () => {
    const pileup = fakePileup({ mismatchAlphaSetting: true });
    const view = fakeView([fakeAlignments(pileup)]);
    applySetting(view, entry('mismatch_alpha'), true, {});
    expect(pileup.toggleMismatchAlpha).not.toHaveBeenCalled();
  });

  it('flips twice when one flip leaves a config-default setting where it was', () => {
    const pileup = fakePileup({ mismatchAlphaSetting: true });
    // The stored override starts unset: the first flip sets it to true again.
    let override: boolean | undefined;
    pileup.toggleMismatchAlpha = vi.fn(() => {
      override = !override;
      pileup.mismatchAlphaSetting = override;
    });
    const view = fakeView([fakeAlignments(pileup)]);
    applySetting(view, entry('mismatch_alpha'), false, {});
    expect(pileup.toggleMismatchAlpha).toHaveBeenCalledTimes(2);
    expect(pileup.mismatchAlphaSetting).toBe(false);
  });

  it('compares feature labels with the read before toggling', () => {
    const display: Model = {
      type: 'LinearBasicDisplay',
      id: 'f1',
      showLabels: true,
      toggleShowLabels: vi.fn(() => {
        display.showLabels = !display.showLabels;
      }),
    };
    const view = fakeView([display]);
    applySetting(view, entry('feature_labels'), true, {});
    expect(display.toggleShowLabels).not.toHaveBeenCalled();
    applySetting(view, entry('feature_labels'), false, {});
    expect(display.toggleShowLabels).toHaveBeenCalledTimes(1);
  });
});

describe('apply mappings', () => {
  it('maps read height to both the feature height and the spacing', () => {
    const pileup = fakePileup();
    const view = fakeView([fakeAlignments(pileup)]);
    applySetting(view, entry('read_height'), 'compact', {});
    expect(pileup.setFeatureHeight).toHaveBeenLastCalledWith(2);
    expect(pileup.setNoSpacing).toHaveBeenLastCalledWith(true);
    applySetting(view, entry('read_height'), 'super_compact', {});
    expect(pileup.setFeatureHeight).toHaveBeenLastCalledWith(1);
    expect(pileup.setNoSpacing).toHaveBeenLastCalledWith(true);
    applySetting(view, entry('read_height'), 'normal', {});
    expect(pileup.setFeatureHeight).toHaveBeenLastCalledWith(7);
    expect(pileup.setNoSpacing).toHaveBeenLastCalledWith(false);
  });

  it('colours by a tag only with the tag, and by a plain scheme otherwise', () => {
    const pileup = fakePileup();
    const view = fakeView([fakeAlignments(pileup)]);
    applySetting(view, entry('color_scheme'), 'tag', {});
    expect(pileup.setColorScheme).not.toHaveBeenCalled();
    applySetting(view, entry('color_scheme'), 'tag', { color_tag: 'HP' });
    expect(pileup.setColorScheme).toHaveBeenLastCalledWith({ type: 'tag', tag: 'HP' });
    applySetting(view, entry('color_scheme'), 'strand', { color_tag: 'HP' });
    expect(pileup.setColorScheme).toHaveBeenLastCalledWith({ type: 'strand' });
    // The tag box re-applies the scheme, but only while the tag scheme is on.
    applySetting(view, entry('color_tag'), 'RG', { color_scheme: 'strand' });
    expect(pileup.setColorScheme).toHaveBeenCalledTimes(2);
    applySetting(view, entry('color_tag'), 'RG', { color_scheme: 'tag' });
    expect(pileup.setColorScheme).toHaveBeenLastCalledWith({ type: 'tag', tag: 'RG' });
  });

  it('maps the lower panel to the display type name', () => {
    const wrapper = fakeAlignments();
    const view = fakeView([wrapper]);
    applySetting(view, entry('lower_panel'), 'arcs', {});
    expect(wrapper.setLowerPanelType).toHaveBeenLastCalledWith('LinearReadArcsDisplay');
  });

  it('moves the coverage panel with the wrapper height', () => {
    const wrapper = fakeAlignments();
    const view = fakeView([wrapper]);
    applySetting(view, entry('coverage_height'), 80, {});
    expect(wrapper.setSNPCoverageHeight).toHaveBeenCalledWith(80);
    expect((wrapper.SNPCoverageDisplay as Model).setHeight).toHaveBeenCalledWith(80);
  });

  it('applies fill only where the renderer has one, summary only with a resolution', () => {
    const wiggle = (over: Model): Model => ({
      type: 'LinearWiggleDisplay',
      id: 'w',
      setFill: vi.fn(),
      setSummaryScoreMode: vi.fn(),
      ...over,
    });
    const line = wiggle({ canHaveFill: false, hasResolution: false });
    const xy = wiggle({ canHaveFill: true, hasResolution: true });
    const view = fakeView([line, xy]);
    applySetting(view, entry('fill'), 'emphasis', {});
    applySetting(view, entry('summary'), 'max', {});
    expect(line.setFill).not.toHaveBeenCalled();
    expect(line.setSummaryScoreMode).not.toHaveBeenCalled();
    expect(xy.setFill).toHaveBeenCalledWith(2);
    expect(xy.setSummaryScoreMode).toHaveBeenCalledWith('max');
  });

  it('reaches the SNP coverage panel inside an alignments display for coverage settings', () => {
    const wrapper = fakeAlignments();
    const cov = wrapper.SNPCoverageDisplay as Model;
    cov.setScaleType = vi.fn();
    cov.setRendererType = vi.fn();
    const view = fakeView([wrapper]);
    applySetting(view, entry('scale'), 'log', {});
    applySetting(view, entry('renderer'), 'line', {});
    expect(cov.setScaleType).toHaveBeenCalledWith('log');
    expect(cov.setRendererType).not.toHaveBeenCalled();
  });

  it('sets the phased mode from a boolean', () => {
    const display: Model = {
      type: 'MultiLinearVariantDisplay',
      id: 'v',
      setPhasedMode: vi.fn(),
    };
    const view = fakeView([display]);
    applySetting(view, entry('phased'), true, {});
    expect(display.setPhasedMode).toHaveBeenLastCalledWith('phased');
    applySetting(view, entry('phased'), false, {});
    expect(display.setPhasedMode).toHaveBeenLastCalledWith('alleleCount');
  });
});

describe('guards', () => {
  it('skips a display that lacks the action, and swallows a throwing one', () => {
    const bare: Model = { type: 'LinearVariantDisplay', id: 'v1' };
    const throwing: Model = {
      type: 'MultiLinearVariantDisplay',
      id: 'v2',
      setRowHeight: vi.fn(() => {
        throw new Error('detached');
      }),
    };
    const view = fakeView([bare, throwing]);
    expect(() => applySetting(view, entry('variant_row_height'), 12, {})).not.toThrow();
    expect(throwing.setRowHeight).toHaveBeenCalledWith(12);
  });

  it('applies nothing to a view that is not a node', () => {
    expect(() => applyAll(null, resolveAll({}, {}))).not.toThrow();
    expect(() => applyAll(undefined, resolveAll({}, {}))).not.toThrow();
    expect(displaysOf(null, entry('scale'))).toEqual([]);
  });

  it('applyAll writes every view setting, built-ins included', () => {
    const view = fakeView([]);
    applyAll(view, resolveAll({}, { center_line: true }));
    expect(view.setShowCenterLine).toHaveBeenCalledWith(true);
    expect(view.setShowGridlines).toHaveBeenCalledWith(true);
    expect(view.setShowCytobands).toHaveBeenCalledWith(true);
    expect(view.setShowTrackOutlines).toHaveBeenCalledWith(true);
    expect(view.setColorByCDS).toHaveBeenCalledWith(false);
    expect(view.setTrackLabels).toHaveBeenCalledWith('overlapping');
  });
});

describe('open displays and groups', () => {
  it('lists the types of every open display, wrapper panels included', () => {
    const view = fakeView([fakeAlignments(), { type: 'LinearBasicDisplay', id: 'f' }]);
    expect(openDisplayTypes(view).sort()).toEqual([
      'LinearAlignmentsDisplay',
      'LinearBasicDisplay',
      'LinearPileupDisplay',
      'LinearSNPCoverageDisplay',
    ]);
  });

  it('shows only the view group with nothing open', () => {
    expect(groupsFor([])).toEqual(['view']);
  });

  it('adds a group per matching open display', () => {
    expect(groupsFor(['LinearBasicDisplay'])).toEqual(['view', 'features']);
    expect(groupsFor(['LinearAlignmentsDisplay', 'LinearSNPCoverageDisplay'])).toEqual([
      'view',
      'alignments',
      'coverage',
    ]);
    expect(groupsFor(new Set(['MultiLinearVariantDisplay']))).toEqual(['view', 'variants']);
    expect(groupsFor(['LinearPileupDisplay'])).toEqual(['view']);
  });

  it('finds the nodes of an entry by display type', () => {
    const view = fakeView([fakeAlignments(), { type: 'LinearBasicDisplay', id: 'f' }]);
    expect(displaysOf(view, entry('feature_mode')).map((d) => d.type)).toEqual([
      'LinearBasicDisplay',
    ]);
    expect(displaysOf(view, entry('scale')).map((d) => d.type)).toEqual([
      'LinearSNPCoverageDisplay',
    ]);
    expect(displaysOf(view, entry('center_line'))).toEqual([view]);
  });

  it('changes a display key when its lower panel is replaced', () => {
    const wrapper = fakeAlignments();
    const view = fakeView([wrapper]);
    const before = displayKeys(view);
    wrapper.PileupDisplay = { type: 'LinearReadArcsDisplay', id: 'p2' };
    expect(displayKeys(view)).not.toEqual(before);
  });

  it('applies only to displays whose key is new', () => {
    const first = fakePileup();
    const second = fakePileup({ id: 'p2' });
    const view = fakeView([fakeAlignments(first), fakeAlignments(second, { id: 'a2' })]);
    const fresh = new Set(displayKeys(view).filter((k) => k.startsWith('LinearAlignmentsDisplay:a2')));
    applySetting(view, entry('soft_clipping'), true, {}, { only: fresh });
    expect(first.toggleSoftClipping).not.toHaveBeenCalled();
    expect(second.toggleSoftClipping).toHaveBeenCalledTimes(1);
  });
});

describe('baselines', () => {
  it('restores what a display read before the first apply', () => {
    const pileup = fakePileup();
    const view = fakeView([fakeAlignments(pileup)]);
    const baselines: Baselines = new WeakMap();
    applySetting(view, entry('read_height'), 'compact', {}, { baselines });
    pileup.featureHeightSetting = 2;
    pileup.noSpacingSetting = true;
    restoreBaseline(view, entry('read_height'), baselines, {});
    expect(pileup.setFeatureHeight).toHaveBeenLastCalledWith(7);
    expect(pileup.setNoSpacing).toHaveBeenLastCalledWith(false);
  });
});

describe('registry', () => {
  it('has one entry per YAML key, each with a unique key', () => {
    const keys = DISPLAY_SETTINGS.map((e) => e.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toHaveLength(29);
  });

  it('gives every choice control its options and every number its bounds', () => {
    for (const e of DISPLAY_SETTINGS) {
      if (e.control === 'segmented' || e.control === 'select') {
        expect(e.options?.length, e.key).toBeGreaterThan(1);
        if (e.control === 'segmented') expect(e.options!.length, e.key).toBeLessThanOrEqual(4);
      }
      if (e.control === 'number') {
        expect(e.min, e.key).toBeDefined();
        expect(e.max, e.key).toBeDefined();
      }
    }
  });
});

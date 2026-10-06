import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../api';
import {
  FIGURE_STYLES,
  figurePlotConfig,
  figureStyleForPick,
  normalizeFigureStyle,
  resolveFigureStyle,
  withSectionFigureStyle,
  withSectionStyles,
} from './figureStyle';

const figure = (extra: Partial<StoredMetadata> = {}): StoredMetadata =>
  ({ index: 'f1', component_type: 'figure', ...extra }) as StoredMetadata;

describe('normalizeFigureStyle', () => {
  it('keeps the known styles', () => {
    expect(FIGURE_STYLES).toEqual(['default', 'minimal']);
    for (const v of FIGURE_STYLES) expect(normalizeFigureStyle(v)).toBe(v);
  });

  it('reads anything else as unset', () => {
    for (const v of [undefined, null, '', 'showcase', 3]) {
      expect(normalizeFigureStyle(v)).toBeNull();
    }
  });
});

describe('resolveFigureStyle', () => {
  it('takes the figure’s own, else the section’s, else default', () => {
    expect(resolveFigureStyle('default', 'minimal')).toBe('default');
    expect(resolveFigureStyle(undefined, 'minimal')).toBe('minimal');
    expect(resolveFigureStyle('odd', 'minimal')).toBe('minimal');
    expect(resolveFigureStyle(undefined, undefined)).toBe('default');
  });
});

describe('withSectionFigureStyle', () => {
  it('fills in the section’s style when the figure sets none', () => {
    expect(withSectionFigureStyle(figure(), { figure_style: 'minimal' }).figure_style).toBe(
      'minimal',
    );
  });

  it('keeps the same object when nothing changes', () => {
    const own = figure({ figure_style: 'default' });
    expect(withSectionFigureStyle(own, { figure_style: 'minimal' })).toBe(own);
    const plain = figure();
    expect(withSectionFigureStyle(plain, {})).toBe(plain);
    expect(withSectionFigureStyle(plain, null)).toBe(plain);
  });

  it('leaves other component types alone', () => {
    const card = { index: 'c', component_type: 'card' } as StoredMetadata;
    expect(withSectionFigureStyle(card, { figure_style: 'minimal' })).toBe(card);
  });
});

describe('withSectionStyles', () => {
  it('applies the card style to cards and the figure style to figures', () => {
    const spec = { card_variant: 'headline' as const, figure_style: 'minimal' as const };
    const card = { index: 'c', component_type: 'card' } as StoredMetadata;
    expect(withSectionStyles(card, spec).variant).toBe('headline');
    expect(withSectionStyles(card, spec).figure_style).toBeUndefined();
    expect(withSectionStyles(figure(), spec).figure_style).toBe('minimal');
    expect(withSectionStyles(figure(), spec).variant).toBeUndefined();
  });
});

describe('figureStyleForPick', () => {
  it('stores nothing when the pick is what the figure gets anyway', () => {
    expect(figureStyleForPick('default', null)).toBeNull();
    expect(figureStyleForPick('minimal', 'minimal')).toBeNull();
  });

  it('stores any other pick, default included to opt out of a section', () => {
    expect(figureStyleForPick('minimal', null)).toBe('minimal');
    expect(figureStyleForPick('default', 'minimal')).toBe('default');
  });
});

describe('figurePlotConfig', () => {
  it('shows a minimal tile’s toolbar on hover only', () => {
    const minimal = figurePlotConfig('minimal');
    expect(minimal.displayModeBar).toBe('hover');
    expect(minimal.modeBarButtonsToRemove).toContain('toggleSpikelines');
    expect(minimal.displaylogo).toBe(false);
  });

  it('leaves the default toolbar alone', () => {
    expect(figurePlotConfig('default')).toEqual({ displaylogo: false, responsive: true });
  });
});

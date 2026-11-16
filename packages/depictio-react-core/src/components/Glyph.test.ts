/**
 * Every MultiQC logo the viewer draws resolves through one table, so a static
 * bundle (file://, no `/dashboard/logos/` mount) can swap in inlined copies
 * once and have the tab icons, tab links, the MultiQC tile's corner mark, the
 * search palette and the data-collection type icon all follow.
 */
import { afterEach, describe, expect, it } from 'vitest';

import {
  multiqcLogoOverride,
  multiqcLogoSrc,
  setMultiqcLogoSources,
  themedIconSrc,
} from './Glyph';

const SERVED = {
  dark: '/dashboard/logos/multiqc_icon_dark.svg',
  white: '/dashboard/logos/multiqc_icon_white.svg',
  color: '/dashboard/logos/multiqc_icon_color.svg',
};

describe('MultiQC logo sources', () => {
  afterEach(() => setMultiqcLogoSources({ dark: SERVED.dark, white: SERVED.white, color: SERVED.color }));

  it('draws the served SVGs by default', () => {
    expect(multiqcLogoSrc('dark')).toBe(SERVED.dark);
    expect(multiqcLogoSrc('white')).toBe(SERVED.white);
    expect(multiqcLogoSrc('color')).toBe(SERVED.color);
    expect(themedIconSrc('/assets/images/logos/multiqc.png', false)).toBe(SERVED.dark);
    expect(themedIconSrc('/assets/images/logos/multiqc_icon_color.svg', true)).toBe(SERVED.white);
  });

  it('follows inlined copies everywhere once installed', () => {
    setMultiqcLogoSources({ dark: 'data:dark', white: 'data:white', color: 'data:color' });
    expect(themedIconSrc('/assets/images/logos/multiqc_icon_color.svg', false)).toBe('data:dark');
    expect(themedIconSrc('/assets/images/logos/multiqc_icon_dark.svg', false, true)).toBe(
      'data:white',
    );
    expect(multiqcLogoSrc('color')).toBe('data:color');
    expect(multiqcLogoOverride('white')).toBe('data:white');
  });

  it('keeps the served colour logo when only the themed pair is replaced', () => {
    setMultiqcLogoSources({ dark: 'data:dark', white: 'data:white' });
    expect(multiqcLogoSrc('color')).toBe(SERVED.color);
    expect(multiqcLogoOverride('color')).toBeNull();
  });

  it('leaves other images alone', () => {
    expect(themedIconSrc('/assets/images/workflows/nf-core.png', true)).toBe(
      '/assets/images/workflows/nf-core.png',
    );
  });
});

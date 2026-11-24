import { DEFAULT_THEME, mergeMantineTheme } from '@mantine/core';
import { describe, expect, it } from 'vitest';

import { brandCssVariablesResolver, buildDepictioTheme } from './brandTheme';
import { paletteHex, paletteVar } from './paletteColor';
import { DEFAULT_PALETTE_ID, PALETTE_IDS, UI_HUES, UI_HUE_TUPLES } from './palettes.generated';
import { tabHueHex } from './tabColor';

/** The theme a component sees: the overrides laid over Mantine's defaults. */
const full = (options?: Parameters<typeof buildDepictioTheme>[0]) =>
  mergeMantineTheme(DEFAULT_THEME, buildDepictioTheme(options));

/** What a dashboard's nested provider sees: its theme merged over the app's. */
const nested = (options: Parameters<typeof buildDepictioTheme>[0]) =>
  mergeMantineTheme(full(), buildDepictioTheme(options));

const stock = full();
const scoped = full({ uiPalette: DEFAULT_PALETTE_ID });
const marque = UI_HUE_TUPLES[DEFAULT_PALETTE_ID];

describe('dashboard hue remap (uiPalette)', () => {
  it('registers every remapped hue as the palette tuple, anchored on shade 6', () => {
    for (const hue of UI_HUES) {
      expect(scoped.colors[hue]).toEqual(marque[hue].light);
      expect(scoped.colors[hue]).toHaveLength(10);
    }
    // The slot colour itself when it already reads at 3:1 on white (violet, red);
    // otherwise deepened in its own hue until it does (yellow).
    expect(scoped.colors.violet[6]).toBe('#925FC4');
    expect(scoped.colors.red[6]).toBe('#E53935');
    expect(scoped.colors.yellow[6]).not.toBe('#EBD244');
  });

  it('paletteHex reads the light tuple on a light scheme, the dark one on a dark scheme', () => {
    expect(paletteHex(scoped, 'teal')).toBe(marque.teal.light[6]);
    expect(paletteHex(scoped, 'teal', 6, true)).toBe(marque.teal.dark[6]);
    expect(paletteHex(scoped, 'grape.4', 6, true)).toBe(marque.grape.dark[4]);
    expect(paletteHex(scoped, 'orange.2')).toBe(marque.orange.light[2]);
  });

  it('tabHueHex picks shade 6 light and shade 4 dark from the palette', () => {
    expect(tabHueHex(scoped, 'teal', false)).toBe(marque.teal.light[6]);
    expect(tabHueHex(scoped, 'teal', true)).toBe(marque.teal.dark[4]);
    expect(tabHueHex(scoped, 'brandPrimary', true)).toBe(DEFAULT_THEME.colors.blue[4]);
  });

  it('paletteVar still names the CSS variable, which the scope now defines per scheme', () => {
    expect(paletteVar('teal')).toBe('var(--mantine-color-teal-6)');
    const resolved = brandCssVariablesResolver(null)(scoped);
    expect(resolved.dark['--mantine-color-teal-4']).toBe(marque.teal.dark[4]);
    expect(resolved.dark['--mantine-color-teal-6']).toBe(marque.teal.dark[6]);
    expect(resolved.dark['--mantine-color-teal-filled']).toBe('var(--mantine-color-teal-8)');
    expect(resolved.dark['--mantine-color-teal-text']).toBe('var(--mantine-color-teal-4)');
    expect(resolved.dark['--mantine-color-teal-light']).toMatch(/^rgba\(/);
    // the light half is Mantine's own, computed from theme.colors
    expect(resolved.light['--mantine-color-teal-6']).toBeUndefined();
  });

  it('keeps gray, dark and brandPrimary untouched', () => {
    expect(scoped.colors.gray).toEqual(stock.colors.gray);
    expect(scoped.colors.dark).toEqual(stock.colors.dark);
    expect(scoped.colors.brandPrimary).toEqual(stock.colors.brandPrimary);
    expect(paletteHex(scoped, 'gray.4', 6, true)).toBe(DEFAULT_THEME.colors.gray[4]);
    const dark = brandCssVariablesResolver(null)(scoped).dark;
    expect(Object.keys(dark).some((k) => /--mantine-color-(gray|dark|brandPrimary)-/.test(k))).toBe(false);
  });

  it('keeps buttons stock: the primary is the stock blue under its own name', () => {
    expect(scoped.primaryColor).toBe('brandPrimary');
    expect(scoped.colors.brandPrimary).toEqual(DEFAULT_THEME.colors.blue);
    expect(scoped.colors.blue).toEqual(marque.blue.light);
  });

  it('leaves the theme alone outside the scope', () => {
    expect(stock.primaryColor).toBe('blue');
    expect(stock.colors.teal).toEqual(DEFAULT_THEME.colors.teal);
    expect(paletteHex(stock, 'teal', 6, true)).toBe(DEFAULT_THEME.colors.teal[6]);
    expect(brandCssVariablesResolver(null)(stock).dark['--mantine-color-teal-4']).toBeUndefined();
    expect(full({ uiPalette: 'no-such-palette' }).colors.teal).toEqual(
      DEFAULT_THEME.colors.teal,
    );
  });

  it('survives the nested provider merging it over the app theme', () => {
    const theme = nested({ uiPalette: DEFAULT_PALETTE_ID });
    expect(theme.colors.teal).toEqual(marque.teal.light);
    expect(theme.primaryColor).toBe('brandPrimary');
    expect(paletteHex(theme, 'teal', 6, true)).toBe(marque.teal.dark[6]);
    expect(brandCssVariablesResolver(null)(theme).dark['--mantine-color-teal-4']).toBe(
      marque.teal.dark[4],
    );
  });

  it('follows the active palette', () => {
    for (const id of PALETTE_IDS) {
      const theme = full({ uiPalette: id });
      expect(theme.colors.teal).toEqual(UI_HUE_TUPLES[id].teal.light);
      expect(paletteHex(theme, 'violet', 6, true)).toBe(UI_HUE_TUPLES[id].violet.dark[6]);
    }
    expect(UI_HUE_TUPLES.signature.orange.light[6]).not.toBe(marque.orange.light[6]);
  });

  it('leaves a hue the brand overrides to the brand', () => {
    const brand = { tint_mode: 'full' as const, secondary: '#112233', tertiary: '#445566' };
    const theme = full({ brand, uiPalette: DEFAULT_PALETTE_ID });
    expect(theme.colors.teal[6]).not.toBe(marque.teal.light[6]);
    expect(theme.colors.orange[6]).not.toBe(marque.orange.light[6]);
    expect(theme.colors.grape).toEqual(marque.grape.light);
    expect(paletteHex(theme, 'teal', 6, true)).toBe(theme.colors.teal[6]);
  });
});

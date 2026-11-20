import React from 'react';
import { Icon } from '@iconify/react';
import { useMantineColorScheme } from '@mantine/core';
import { paletteVar } from '../paletteColor';

/**
 * One icon value, drawn the way a tab draws it.
 *
 * An icon in dashboard YAML is either an Iconify name (`mdi:dna`) or a path to
 * an image — the workflow logos, MultiQC's above all. The sidebar, the tab
 * header, section headers and tab links all have to accept both, and before
 * this each spot carried its own copy of the path test and of the MultiQC logo
 * swap, so a section could not wear the logo its own tab wore.
 */

/** True for path-like icon values (PNG/SVG file URLs) rather than Iconify names. */
export function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/** True when the value points at a MultiQC logo (legacy PNG or an SVG variant). */
export function isMultiqcIcon(path: string | null | undefined): boolean {
  if (!path) return false;
  return /\/assets\/images\/logos\/multiqc(\.png|_icon_(dark|white|color)\.svg)$/i.test(path);
}

/**
 * Legacy YAML points at `/assets/images/logos/multiqc.png`, which the SPA does
 * not serve. Swap it for the official SVG under `/dashboard/logos/`: white on a
 * filled (active) background or in dark mode, dark otherwise.
 */
export function themedIconSrc(path: string, isDark: boolean, onFilled = false): string {
  if (!isMultiqcIcon(path)) return path;
  return multiqcLogoSrc(onFilled || isDark ? 'white' : 'dark');
}

/** Where the MultiQC logo is drawn from, per variant. */
export interface MultiqcLogoSources {
  /** Dark ink, for a light page. */
  dark: string;
  /** White, for a dark page or a filled (active) background. */
  white: string;
  /** The brand-coloured logo (the data-collection type icon). */
  color?: string;
}

export type MultiqcLogoVariant = keyof MultiqcLogoSources;

const SERVED_MULTIQC_LOGOS: Required<MultiqcLogoSources> = {
  dark: '/dashboard/logos/multiqc_icon_dark.svg',
  white: '/dashboard/logos/multiqc_icon_white.svg',
  color: '/dashboard/logos/multiqc_icon_color.svg',
};

let multiqcLogoSources: Required<MultiqcLogoSources> = { ...SERVED_MULTIQC_LOGOS };
let multiqcLogosReplaced: Partial<MultiqcLogoSources> = {};

/**
 * Replace the URLs the MultiQC logo is drawn from — every place that draws it:
 * `themedIconSrc` (tab icons, tab links, section headers), the MultiQC tile's
 * corner mark, the search palette's row icon and the data-collection type icon.
 *
 * A serverless static bundle opens from file://, where `/dashboard/logos/...`
 * resolves outside the bundle and draws a broken-image glyph; its entry hands
 * in inlined (data: URI) copies once, before the first render. Server builds
 * never call it and keep the SPA-served, separately cacheable SVGs.
 */
export function setMultiqcLogoSources(sources: MultiqcLogoSources): void {
  multiqcLogosReplaced = { ...sources };
  multiqcLogoSources = { ...SERVED_MULTIQC_LOGOS, ...sources };
}

/** The MultiQC logo's URL for one variant (the served SVG unless replaced). */
export function multiqcLogoSrc(variant: MultiqcLogoVariant): string {
  return multiqcLogoSources[variant];
}

/** The replaced URL for a variant, or null when the build draws the served
 *  one — for callers that resolve the served path against their own base. */
export function multiqcLogoOverride(variant: MultiqcLogoVariant): string | null {
  return multiqcLogosReplaced[variant] ?? null;
}

/**
 * A colour as YAML states it — a Mantine palette name (`teal`) or a literal
 * CSS colour (`#12b886`, `var(...)`) — as something CSS accepts.
 */
export function glyphColorVar(color?: string | null): string {
  if (!color) return 'var(--mantine-color-dimmed)';
  // "Dark" is ink, not a hue (the MultiQC tabs are forced to it): its shade 6
  // is near-black in both schemes and vanished on a dark page. `paletteVar`
  // handles that, and the `blue.4` / `blue-4` shade spellings.
  return paletteVar(color) ?? 'var(--mantine-color-dimmed)';
}

export const Glyph: React.FC<{
  icon: string;
  color?: string | null;
  size?: number;
  /** Sits on a filled background, e.g. the active sidebar pill. */
  onFilled?: boolean;
  style?: React.CSSProperties;
}> = ({ icon, color, size = 18, onFilled = false, style }) => {
  const { colorScheme } = useMantineColorScheme();
  if (isImagePath(icon)) {
    return (
      <img
        src={themedIconSrc(icon, colorScheme === 'dark', onFilled)}
        alt=""
        width={size}
        height={size}
        style={{ flexShrink: 0, objectFit: 'contain', ...style }}
      />
    );
  }
  return (
    <Icon
      icon={icon}
      width={size}
      height={size}
      style={{ color: glyphColorVar(color), flexShrink: 0, ...style }}
    />
  );
};

export default Glyph;

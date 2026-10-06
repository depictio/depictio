import React from 'react';
import { Icon } from '@iconify/react';
import { useMantineColorScheme } from '@mantine/core';

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
  return onFilled || isDark
    ? '/dashboard/logos/multiqc_icon_white.svg'
    : '/dashboard/logos/multiqc_icon_dark.svg';
}

/**
 * A colour as YAML states it — a Mantine palette name (`teal`) or a literal
 * CSS colour (`#12b886`, `var(...)`) — as something CSS accepts.
 */
export function glyphColorVar(color?: string | null): string {
  if (!color) return 'var(--mantine-color-dimmed)';
  if (/^(#|rgb|hsl|var\()/.test(color)) return color;
  // "Dark" is ink, not a hue (the MultiQC tabs are forced to it): its shade 6
  // is near-black in both schemes and vanished on a dark page.
  if (color === 'dark' || color === 'black') return 'var(--mantine-color-text)';
  return `var(--mantine-color-${color}-6)`;
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

import React from 'react';
import { useComputedColorScheme } from '@mantine/core';

import { resolveBrandLogo, type BrandTheme } from 'depictio-react-core';

import { useBranding } from '../branding';

interface BrandLogoProps {
  /** A dashboard's own brand theme, tried before the instance one. Omit for
   *  the plain instance logo (app sidebar, login card). */
  theme?: BrandTheme | null;
  /** What to render when no layer supplies a custom logo. `'wordmark'` (the
   *  default) shows the depictio logo; `'none'` renders nothing, which is what
   *  an optional decorative slot wants. */
  fallback?: 'wordmark' | 'none';
  width?: number | string;
  height?: number | string;
  style?: React.CSSProperties;
  /** Forwarded to the rendered `<img>` so tests can target a specific slot. */
  testId?: string;
}

/**
 * The brand logo (issue #397), resolved across the layers that can supply one:
 * the dashboard's own theme, then the instance's, then the depictio wordmark.
 *
 * `logo_mode` is what makes each layer's intent explicit — `'inherit'` falls
 * through to the next layer, `'none'` stops here and shows nothing, `'custom'`
 * uses that layer's URL. That's the ask behind "keep the instance logo at the
 * dashboard level": a dashboard says nothing and gets its instance's logo.
 *
 * Dark-mode handling lives here so it's decided once:
 * - Custom logos pick `logo_url_dark` in dark mode (falling back to the light
 *   one untouched — never CSS-inverted, the operator knows their own brand).
 * - The default depictio logo ships as one raster for both themes
 *   (`logo_black.svg` and `logo_white.svg` are byte-identical), so dark mode
 *   applies the established `invert(1) hue-rotate(180deg)` filter instead of
 *   swapping `src` — same trick as `PoweredBy.tsx`.
 */
export default function BrandLogo({
  theme,
  fallback = 'wordmark',
  width,
  height,
  style,
  testId,
}: BrandLogoProps) {
  const instance = useBranding();
  const colorScheme = useComputedColorScheme('light');
  const isDark = colorScheme === 'dark';

  let src: string | null = null;
  let stopped = false;
  for (const layer of theme ? [theme, instance] : [instance]) {
    const resolved = resolveBrandLogo(layer, isDark);
    if (resolved.mode === 'none') {
      stopped = true;
      break;
    }
    if (resolved.src) {
      src = resolved.src;
      break;
    }
  }

  if (stopped) return null;
  if (!src && fallback === 'none') return null;

  return (
    <img
      src={src ?? '/dashboard/logos/logo_black.svg'}
      alt={instance?.app_name ?? 'depictio'}
      data-testid={testId}
      style={{
        width,
        height,
        maxWidth: '100%',
        objectFit: 'contain',
        display: 'block',
        filter: !src && isDark ? 'invert(1) hue-rotate(180deg)' : undefined,
        ...style,
      }}
    />
  );
}

import React from 'react';
import { useComputedColorScheme } from '@mantine/core';

import { useBranding } from '../branding';

interface BrandLogoProps {
  width?: number | string;
  height?: number | string;
  style?: React.CSSProperties;
}

/**
 * The instance logo (issue #397): the deployment's custom logo when branding
 * is configured (`DEPICTIO_BRANDING_LOGO_URL`), the depictio wordmark
 * otherwise. Single source for the sidebar and the login card so the
 * dark-mode handling lives in one place:
 *
 * - Custom logos pick `logo_url_dark` in dark mode (falling back to the light
 *   one untouched — never CSS-inverted, the operator knows their own brand).
 * - The default depictio logo ships as one raster for both themes
 *   (`logo_black.svg` and `logo_white.svg` are byte-identical), so dark mode
 *   applies the established `invert(1) hue-rotate(180deg)` filter instead of
 *   swapping `src` — same trick as `PoweredBy.tsx`.
 */
export default function BrandLogo({ width, height, style }: BrandLogoProps) {
  const branding = useBranding();
  const colorScheme = useComputedColorScheme('light');
  const isDark = colorScheme === 'dark';

  const customSrc = branding?.logo_url
    ? (isDark && branding.logo_url_dark) || branding.logo_url
    : null;

  return (
    <img
      src={customSrc ?? '/dashboard/logos/logo_black.svg'}
      alt={branding?.app_name ?? 'depictio'}
      style={{
        width,
        height,
        maxWidth: '100%',
        objectFit: 'contain',
        display: 'block',
        filter:
          !customSrc && isDark ? 'invert(1) hue-rotate(180deg)' : undefined,
        ...style,
      }}
    />
  );
}

import { useComputedColorScheme } from '@mantine/core';

import { resolveBrandLogo, type LogoMode } from 'depictio-react-core';

import { useBranding } from '../branding';

/**
 * Which logo the brand in scope actually resolves to, for the surfaces that
 * need to react to it rather than just render it:
 *
 * - `'custom'` — the operator's (or the dashboard's) own mark is on screen.
 * - `'none'`   — the brand asks for no logo at all.
 * - `'inherit'` — nothing was supplied, so `BrandLogo` falls back to the
 *   depictio wordmark. Also what a `logo_mode: 'custom'` with an empty URL
 *   collapses to, which is why callers must read the resolved mode rather
 *   than `theme.logo_mode`.
 */
export function useBrandLogoMode(): LogoMode {
  const brand = useBranding();
  const isDark = useComputedColorScheme('light') === 'dark';
  return resolveBrandLogo(brand, isDark).mode;
}

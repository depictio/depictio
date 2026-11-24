import React from 'react';
import { MantineProvider, useMantineColorScheme } from '@mantine/core';

import {
  BrandingContext,
  brandCssVariablesResolver,
  buildDepictioTheme,
  isEmptyBrandTheme,
  mergeBrandThemes,
  useBranding,
  type BrandTheme,
} from '../../brandTheme';
import { useResolvedBrandTheme } from './useResolvedBrandTheme';
import { useChromeStyle } from '../../chrome/chromeStyle';
import { DEFAULT_PALETTE_ID } from '../../palettes.generated';
import { createSchemeBridge } from './schemeBridge';

/**
 * Scopes a dashboard's colours to its own subtree: its brand override (#397) and
 * the plot palette's hues.
 *
 * Inside the scope the Mantine hue names a dashboard uses (`teal`, `grape`,
 * `orange`...) are re-drawn in the active plot palette (`uiPalette`, see
 * `buildDepictioTheme`), so KPI cards, sections, tab icons, steps and filter
 * accents follow the figures' colours. That is why every dashboard gets the scoped
 * provider, override or not.
 *
 * A dashboard states only what differs from the instance, so the override is
 * laid over the instance theme first. The result is scoped rather than global:
 * `cssVariablesSelector` emits the variables on the wrapper class instead of
 * `:root`, and `getRootElement` returns undefined so the nested provider never
 * touches `<html>` — the app shell around the dashboard keeps the instance
 * look.
 *
 * The wrapper repeats the current `data-mantine-color-scheme` because Mantine
 * emits its per-scheme block as `.selector[data-mantine-color-scheme="dark"]`,
 * a compound selector rather than a descendant one: on an ancestor those rules
 * never match, and every variable defined only there — the brand palette
 * included — quietly falls back to the outer theme.
 *
 * A dashboard with no override — nearly all of them — takes the cheap path: the
 * instance theme plus the palette, built once and memoised, no resolve request.
 */
const SCOPE_CLASS = 'depictio-dashboard-brand';

/** What an element needs to pick up the scope's CSS variables. */
export interface BrandScopeAttributes {
  className: string;
  'data-mantine-color-scheme': 'light' | 'dark';
}

const BrandScopeAttributesContext = React.createContext<BrandScopeAttributes | null>(null);

/**
 * The attributes that put an element inside the enclosing `BrandScope`, or
 * null outside one (or when the dashboard has no override).
 *
 * The scope's variables are emitted on a wrapper class, so they reach only
 * DOM descendants of that wrapper. A Mantine Drawer, Modal or Popover is
 * portaled to `<body>`: it still sees the scoped theme through React context,
 * but none of the CSS variables, so its primary colour falls back to the
 * instance one. Spreading these on the portaled root (`className` /
 * `data-mantine-color-scheme`) brings it back into the scope.
 */
export function useBrandScopeAttributes(): BrandScopeAttributes | null {
  return React.useContext(BrandScopeAttributesContext);
}

/** The palette the scope draws its hues in: the brand's preset, else the default. */
function activePalette(brand: BrandTheme | null | undefined): string {
  return brand?.plots?.palette || DEFAULT_PALETTE_ID;
}

/** The wrapper element and the scoped provider, whichever way the theme was built. */
const ScopeShell: React.FC<{
  brand: BrandTheme | null;
  theme: ReturnType<typeof buildDepictioTheme>;
  cssVariablesResolver: ReturnType<typeof brandCssVariablesResolver>;
  children: React.ReactNode;
}> = ({ brand, theme, cssVariablesResolver, children }) => {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const scheme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const attributes = React.useMemo<BrandScopeAttributes>(
    () => ({ className: SCOPE_CLASS, 'data-mantine-color-scheme': scheme }),
    [scheme],
  );
  // The app provider owns the scheme. A nested provider left to itself reads its
  // own stored one, which drifts from the app's (a borrowed `?theme=`, an embed,
  // a toggle that only reached one of them), and every dashboard runs inside one.
  // The bridge reads and writes the app's scheme, so a toggle inside the scope
  // reaches the app too (forceColorScheme would swallow it).
  const current = React.useRef({ scheme, setColorScheme });
  current.current = { scheme, setColorScheme };
  const bridge = React.useMemo(
    () =>
      createSchemeBridge(
        () => current.current.scheme,
        (next) => current.current.setColorScheme(next),
      ),
    [],
  );
  React.useEffect(() => bridge.follow(scheme), [bridge, scheme]);

  return (
    <BrandingContext.Provider value={brand}>
      <BrandScopeAttributesContext.Provider value={attributes}>
        <div
          className={SCOPE_CLASS}
          data-mantine-color-scheme={scheme}
          style={{ display: 'contents' }}
        >
          <MantineProvider
            theme={theme}
            cssVariablesResolver={cssVariablesResolver}
            cssVariablesSelector={`.${SCOPE_CLASS}`}
            getRootElement={() => undefined}
            colorSchemeManager={bridge}
          >
            {children}
          </MantineProvider>
        </div>
      </BrandScopeAttributesContext.Provider>
    </BrandingContext.Provider>
  );
};

/** No override: the instance brand as it is, with the palette's hues. No request. */
const PaletteScope: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const instance = useBranding();
  const chrome = useChromeStyle().themeOverrides;
  const uiPalette = activePalette(instance);
  const mantineTheme = React.useMemo(
    () => buildDepictioTheme({ brand: instance, chrome, uiPalette }),
    [instance, chrome, uiPalette],
  );
  const cssVariablesResolver = React.useMemo(() => brandCssVariablesResolver(instance), [instance]);
  return (
    <ScopeShell brand={instance} theme={mantineTheme} cssVariablesResolver={cssVariablesResolver}>
      {children}
    </ScopeShell>
  );
};

const ScopedProvider: React.FC<{ theme: BrandTheme; children: React.ReactNode }> = ({
  theme,
  children,
}) => {
  const instance = useBranding();
  const merged = React.useMemo(() => mergeBrandThemes(instance, theme), [instance, theme]);
  // Derived values (figure colorway, continuous scale) are computed server
  // side so the render path and the SPA can't disagree; until the request
  // lands the hook hands back the unresolved merge, which already carries
  // every colour the chrome needs.
  const resolved = useResolvedBrandTheme(merged);
  const chrome = useChromeStyle().themeOverrides;
  const uiPalette = activePalette(resolved);
  const mantineTheme = React.useMemo(
    () => buildDepictioTheme({ brand: resolved, chrome, uiPalette }),
    [resolved, chrome, uiPalette],
  );
  const cssVariablesResolver = React.useMemo(
    () => brandCssVariablesResolver(resolved),
    [resolved],
  );
  return (
    <ScopeShell brand={resolved} theme={mantineTheme} cssVariablesResolver={cssVariablesResolver}>
      {children}
    </ScopeShell>
  );
};

export const BrandScope: React.FC<{
  theme?: BrandTheme | null;
  children: React.ReactNode;
}> = ({ theme, children }) => {
  if (!theme || isEmptyBrandTheme(theme)) return <PaletteScope>{children}</PaletteScope>;
  return <ScopedProvider theme={theme}>{children}</ScopedProvider>;
};

export default BrandScope;

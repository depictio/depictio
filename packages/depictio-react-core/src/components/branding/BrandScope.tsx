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

/**
 * Applies a dashboard's brand override to its own subtree (#397).
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
 * Dashboards with no override — nearly all of them — render their children
 * untouched: no second provider, no extra element, no resolve request.
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

const ScopedProvider: React.FC<{ theme: BrandTheme; children: React.ReactNode }> = ({
  theme,
  children,
}) => {
  const instance = useBranding();
  const { colorScheme } = useMantineColorScheme();
  const merged = React.useMemo(() => mergeBrandThemes(instance, theme), [instance, theme]);
  // Derived values (figure colorway, continuous scale) are computed server
  // side so the render path and the SPA can't disagree; until the request
  // lands the hook hands back the unresolved merge, which already carries
  // every colour the chrome needs.
  const resolved = useResolvedBrandTheme(merged);
  const chrome = useChromeStyle().themeOverrides;
  const mantineTheme = React.useMemo(
    () => buildDepictioTheme({ brand: resolved, chrome }),
    [resolved, chrome],
  );
  const cssVariablesResolver = React.useMemo(
    () => brandCssVariablesResolver(resolved),
    [resolved],
  );

  const scheme = colorScheme === 'dark' ? 'dark' : 'light';
  const attributes = React.useMemo<BrandScopeAttributes>(
    () => ({ className: SCOPE_CLASS, 'data-mantine-color-scheme': scheme }),
    [scheme],
  );

  return (
    <BrandingContext.Provider value={resolved}>
      <BrandScopeAttributesContext.Provider value={attributes}>
        <div
          className={SCOPE_CLASS}
          data-mantine-color-scheme={scheme}
          style={{ display: 'contents' }}
        >
          <MantineProvider
            theme={mantineTheme}
            cssVariablesResolver={cssVariablesResolver}
            cssVariablesSelector={`.${SCOPE_CLASS}`}
            getRootElement={() => undefined}
          >
            {children}
          </MantineProvider>
        </div>
      </BrandScopeAttributesContext.Provider>
    </BrandingContext.Provider>
  );
};

export const BrandScope: React.FC<{
  theme?: BrandTheme | null;
  children: React.ReactNode;
}> = ({ theme, children }) => {
  if (!theme || isEmptyBrandTheme(theme)) return <>{children}</>;
  return <ScopedProvider theme={theme}>{children}</ScopedProvider>;
};

export default BrandScope;

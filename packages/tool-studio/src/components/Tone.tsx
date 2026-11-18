/**
 * The Studio's section tone, applied the way depictio applies one.
 *
 * `useStudioTone` is `useSectionTone` of chrome/variants/glass/pages/GlassPage.tsx
 * (which is not exported, and whose module reads the server): the section's
 * palette becomes the primary colour of everything the page renders, through a
 * theme for the controls that resolve `theme.primaryColor` and the root
 * `--mantine-primary-color-*` variables for those that read them (portals
 * included, which is why they go on <html>). The Paper accent tokens (--gl-*)
 * are declared from those variables, so the chrome follows.
 *
 * `InstancePrimary` undoes it for a subtree: what the Studio previews is a
 * dashboard component, and a dashboard draws in the instance primary. The
 * wrapper carries the class glass.css re-declares the accent tokens under for a
 * dashboard's own brand scope, so the Paper accents follow it back too.
 */
import React from 'react';
import { MantineThemeContext, useMantineTheme, type MantineTheme } from '@mantine/core';

const PRIMARY_VARS = [
  ...Array.from({ length: 10 }, (_, i) => String(i)),
  'filled',
  'filled-hover',
  'light',
  'light-hover',
  'light-color',
] as const;

function primaryVars(palette: string): React.CSSProperties {
  const vars: Record<string, string> = {};
  for (const v of PRIMARY_VARS) vars[`--mantine-primary-color-${v}`] = `var(--mantine-color-${palette}-${v})`;
  return vars as React.CSSProperties;
}

/** Makes `palette` the page's primary; returns the theme to provide. */
export function useStudioTone(palette: string): MantineTheme {
  const theme = useMantineTheme();
  React.useEffect(() => {
    const root = document.documentElement.style;
    for (const v of PRIMARY_VARS) {
      root.setProperty(`--mantine-primary-color-${v}`, `var(--mantine-color-${palette}-${v})`);
    }
    return () => {
      for (const v of PRIMARY_VARS) root.removeProperty(`--mantine-primary-color-${v}`);
    };
  }, [palette]);
  return React.useMemo(() => ({ ...theme, primaryColor: palette }), [palette, theme]);
}

/** A subtree in the instance's own primary (the theme's), not the section's. */
export function InstancePrimary({
  children,
  className,
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  const sectionTheme = useMantineTheme();
  // The theme as built (theme.ts), before the section changed its primary.
  const base = React.useContext(BaseThemeContext) ?? sectionTheme;
  return (
    <MantineThemeContext.Provider value={base}>
      <div
        className={`depictio-dashboard-brand${className ? ` ${className}` : ''}`}
        style={{ ...primaryVars(base.primaryColor), ...style }}
      >
        {children}
      </div>
    </MantineThemeContext.Provider>
  );
}

/** The theme before the section tone; provided by the App around the page. */
export const BaseThemeContext = React.createContext<MantineTheme | null>(null);

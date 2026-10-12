/**
 * The Glass shell of the component builder (add and edit pages).
 *
 *  ┌──────────────────────────────────────────────────────────────┐
 *  │ ✿ depictio │ ▣ Dashboards › TREC 2024 › New component  [Cancel] ☾ │ top bar
 *  ├──────────────────────────────────────────────────────────────┤
 *  │  ▣  New component                              [← Methods]   │ page head
 *  │     Pick a type, connect the data, design it.                 │
 *  │  ┌ stepper ───────────────────────────────────────────────┐  │
 *  │  │ ...                                                    │  │
 *  ├──────────────────────────────────────────────────────────────┤
 *  │ Step 1 of 3                                  [Back] [Next]   │ step bar
 *  └──────────────────────────────────────────────────────────────┘
 *
 * It is the management pages' shell (`GlassPage`) without the sidebar: the same
 * top bar, trail, page head and canvas, all from `pages.css` through its `gp-*`
 * classes, so the builder reads as one of those pages. Only the layout that has
 * no counterpart there (one column, the step bar, the filling catalog browser)
 * and the builder's own surfaces live in `builder-glass.css`.
 */
import React from 'react';
import { Button } from '@mantine/core';
import { ChevronRight, LayoutDashboard, Moon, Sun, X } from 'lucide-react';

import { GlassKey, HomeMark, ProfileKey, usePageMark } from '../../chrome/variants/glass/pages';
import type { Crumb } from '../../chrome/variants/glass/pages';
import PoweredBy from '../../chrome/PoweredBy';
import { useColorScheme } from '../../hooks/useColorScheme';
import './builder-glass.css';

const DASHBOARDS_TINT = { ['--gp-tint' as string]: 'var(--depictio-brand-tertiary)' } as React.CSSProperties;

const ThemeKey: React.FC = () => {
  const { colorScheme, toggle } = useColorScheme();
  const dark = colorScheme === 'dark';
  return (
    <GlassKey
      label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      icon={dark ? Sun : Moon}
      onClick={toggle}
      data-testid="theme-toggle"
    />
  );
};

export interface GlassBuilderShellProps {
  /** The trail after "Dashboards": the dashboard (linked) and the page. */
  crumbs: Crumb[];
  onCancel: () => void;
  /** The page head: a tile glyph, a title and what it is for. Omitted on the
   *  start screen, which carries its own heading. */
  head?: {
    icon: React.ReactNode;
    /** Any CSS colour: the tile's hue. Defaults to the dashboards' tint. */
    tint?: string;
    title: React.ReactNode;
    description?: React.ReactNode;
    actions?: React.ReactNode;
  };
  /** The step bar docked under the canvas. */
  footer?: React.ReactNode;
  /** The page fills the window instead of scrolling (the catalog browser). */
  fill?: boolean;
  children: React.ReactNode;
}

const GlassBuilderShell: React.FC<GlassBuilderShellProps> = ({
  crumbs,
  onCancel,
  head,
  footer,
  fill = false,
  children,
}) => {
  usePageMark('builder');
  const trail: Crumb[] = [{ label: 'Dashboards', href: '/dashboards' }, ...crumbs];

  return (
    <div
      className="gp-shell bgl-shell"
      data-testid="app-shell"
      data-foot={footer ? '' : undefined}
      data-fill={fill ? '' : undefined}
    >
      <header className="gp-top">
        <HomeMark height={44} />
        <span className="gp-top-rule" aria-hidden />
        <nav className="gp-trail" aria-label="You are here">
          <span className="gp-trail-icon" style={DASHBOARDS_TINT} aria-hidden>
            <LayoutDashboard size={16} strokeWidth={1.8} />
          </span>
          {trail.map((c, i) => {
            const last = i === trail.length - 1;
            return (
              <React.Fragment key={`${c.label}-${i}`}>
                {i > 0 && <ChevronRight className="gp-trail-chev" size={14} strokeWidth={2} aria-hidden />}
                {last || !c.href ? (
                  <span className="gp-trail-here" aria-current={last ? 'page' : undefined} title={c.label}>
                    {c.label}
                  </span>
                ) : (
                  <a className="gp-trail-link" href={c.href} title={c.label}>
                    {c.label}
                  </a>
                )}
              </React.Fragment>
            );
          })}
        </nav>
        <span className="gp-flex" />
        <span className="gp-top-powered">
          <PoweredBy />
        </span>
        <Button
          variant="default"
          size="sm"
          leftSection={<X size={16} strokeWidth={1.9} aria-hidden />}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <div className="gp-top-keys">
          <ThemeKey />
          <ProfileKey />
        </div>
      </header>

      <main className="gp-main bgl-main">
        <div className="gp-page bgl-page">
          {head && (
            <div className="gp-head bgl-head">
              <span
                className="gp-head-icon bgl-head-icon"
                style={head.tint ? ({ ['--bgl-head-tint' as string]: head.tint } as React.CSSProperties) : undefined}
                aria-hidden
              >
                {head.icon}
              </span>
              <div className="gp-head-text">
                <h1 className="gp-title bgl-title">{head.title}</h1>
                {head.description && <p className="gp-desc">{head.description}</p>}
              </div>
              {head.actions && <div className="gp-head-actions">{head.actions}</div>}
            </div>
          )}
          {children}
        </div>
      </main>

      {footer && <footer className="bgl-foot">{footer}</footer>}
    </div>
  );
};

export default GlassBuilderShell;

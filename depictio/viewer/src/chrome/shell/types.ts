import type React from 'react';
import type { AppShellProps } from '@mantine/core';
import type { InteractiveFilter, StoredMetadata } from 'depictio-react-core';

import type { HeaderModel } from '../Header';
import type { TabNavModel } from '../Sidebar';

export interface FilterPanelOptions {
  /** The docked column: draws the panel's own collapse control and the
   *  docked map at its foot. Off for a drawer, a popover or an inspector,
   *  where the surrounding surface has its own close. */
  docked?: boolean;
}

/**
 * Everything a dashboard page lays out, handed to the active chrome style's
 * Shell. The viewer and the editor build it; a Shell only places it.
 *
 * Regions come pre-rendered (`node`) with the state behind them, so a Shell
 * can either drop the default piece in place or draw its own from the model
 * (`header.model`, `nav.model`, `filters.members`).
 *
 * Contract a Shell keeps:
 * - render `canvas` exactly once (it carries `data-testid="dashboard-content"`,
 *   the grid and the Guide's measuring point);
 * - keep `data-tour-id="header-title"` on the header region, `"sidebar"` on
 *   the tab list region (the walkthrough anchors there);
 * - render `overlays` inside the page and `outside` once, anywhere;
 * - render `boot` above the canvas, ready or not (loading, errors, the
 *   version-preview and ingestion banners);
 * - without Mantine `AppShell`, set `--app-shell-header-offset`,
 *   `--app-shell-navbar-offset` and `--app-shell-aside-offset` on the page
 *   root yourself: the Guide layer and some drawers position from them.
 */
export interface DashboardShellProps {
  mode: 'view' | 'edit';
  /** Below `sm` (48em). */
  isNarrow: boolean;
  /** The dashboard is loaded and drawable. */
  ready: boolean;
  header: {
    model: HeaderModel;
    /** The default header content (title left, action groups right). */
    node: React.ReactNode;
  };
  nav: {
    model: TabNavModel;
    /** The default tab sidebar. In edit mode it carries the tab and group
     *  menus (rename, move, delete, add), so an editing layout should keep it
     *  reachable. */
    node: React.ReactNode;
    mobileOpened: boolean;
    desktopOpened: boolean;
    toggleMobile: () => void;
    toggleDesktop: () => void;
  };
  /** The version-preview and ingestion banners, the boot splash and load
   *  errors. Drawn above the canvas whether or not the page is ready. */
  boot: React.ReactNode;
  /** The tab's content: intro, grid, bottom-pinned sections. */
  canvas: React.ReactNode;
  /** The full-width strip of `placement: top` controls (Timeline), or null. */
  topStrip: React.ReactNode | null;
  filters: {
    /** The panel's filter components (the docked column's members). */
    members: StoredMetadata[];
    values: InteractiveFilter[];
    onChange: (filter: InteractiveFilter) => void;
    reset: () => void;
    /** Active filters, plus group rows: what the badge on a Filters button shows. */
    count: number;
    /** A FilterPanel with this page's state; call once per place it shows. */
    panel: (opts?: FilterPanelOptions) => React.ReactNode;
    /** The docked column's state (default layout). */
    docked: {
      opened: boolean;
      toggle: () => void;
      /** Resizable width, px, and the CSS variable the grid track reads. */
      width: number;
      widthVar: string;
      layoutRef: React.MutableRefObject<HTMLDivElement | null>;
      resizing: boolean;
      beginResize: (e: React.PointerEvent<HTMLElement>) => void;
      nudge: (deltaPx: number) => void;
    };
    /** The phone drawer (the header's Filters button opens it). */
    drawer: { opened: boolean; open: () => void; close: () => void };
  };
  /** Fixed furniture of the page (notes, floating maps, funnel view, the
   *  Guide): render inside the page area. */
  overlays: React.ReactNode;
  /** Drawers and modals (settings, search, run parameters, editor dialogs). */
  outside: React.ReactNode;
  inspector: {
    enabled: boolean;
    node: React.ReactNode;
    /** AppShell `aside` config for the default layout. */
    aside: AppShellProps['aside'];
  };
  /** The Analysis panel: a right drawer the page pads for on wide screens. */
  analysis: { open: boolean; widthPx: number };
  guideOpen: boolean;
}

export type DashboardShell = React.ComponentType<DashboardShellProps>;

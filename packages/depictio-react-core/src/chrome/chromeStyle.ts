import { useSyncExternalStore } from 'react';
import type React from 'react';
import type { MantineRadius, MantineThemeOverride } from '@mantine/core';

import { useBrandAccents } from '../brandTheme';

/**
 * Chrome style: one description of how the dashboard chrome (header, tab
 * sidebar, filter controls) draws its buttons, so every action picks its look
 * from a *role* rather than from a variant and a colour chosen on the spot.
 *
 * - `primary`   the one action that moves the page forward (Edit, Save, Add)
 * - `secondary` labelled actions next to it (Settings, Comments, Exit edit)
 * - `quiet`     icon-only utilities (burger, search, feedback, panel options)
 * - `toggle`    a mode that stays on until turned off (Analysis, funnel)
 * - `danger`    clearing state (Reset filters)
 *
 * A style is swappable at runtime (`setChromeStyle`): the viewer registers a
 * few and picks one per page. The DOM mirrors the active one as `data-chrome*`
 * attributes on `<html>`, which is what each style's own CSS keys on.
 */
export type ChromeRole = 'primary' | 'secondary' | 'quiet' | 'toggle' | 'danger';

/** Where a role's colour comes from. Brand roles follow the instance brand and
 *  fall back to the historical literals (blue / teal / orange). */
export type ChromeTone = 'primary' | 'secondary' | 'tertiary' | 'neutral' | 'danger';

export type ChromeVariantName = 'filled' | 'light' | 'outline' | 'subtle' | 'default' | 'transparent';

export interface ChromeRoleStyle {
  variant: ChromeVariantName;
  tone: ChromeTone;
  /** `toggle` only: the look while the mode is on. */
  activeVariant?: ChromeVariantName;
  activeTone?: ChromeTone;
}

/** Semantic icon slots, so a style can swap the whole icon family at once. */
export type ChromeIconName =
  | 'menu'
  | 'search'
  | 'add'
  | 'save'
  | 'edit'
  | 'view'
  | 'settings'
  | 'feedback'
  | 'comments'
  | 'analysis'
  | 'filters'
  | 'reset'
  | 'more'
  | 'moreFilters'
  | 'lessFilters'
  | 'hide'
  | 'chevronDown'
  | 'funnel'
  | 'funnelView'
  | 'back';

export interface ChromeLayout {
  /** AppShell header height, px. */
  headerHeight: number;
  /** Header height below `sm`, px (defaults to `headerHeight`). */
  headerHeightMobile?: number;
  /** The active tab pill is a solid fill (icon drawn white on it). Set false
   *  for styles whose active pill is neutral, so icons keep their colour. */
  activeTabFilled?: boolean;
  /** Tab sidebar width, px. */
  navbarWidth: number;
}

/**
 * What a style's own button component receives. Everything is resolved: the
 * icon ids come from the style's icon set, the tones are Mantine colour names
 * that already follow the instance brand.
 *
 * Contract for a custom button (so the shared behaviour keeps working):
 * - forward the ref to the root `<button>` / `<a>` (menus anchor on it);
 * - keep `className` (it carries `dc-action`) and spread `rest` (data-*,
 *   aria-*, handlers) on the root;
 * - render the visible label inside `<span class="dc-action-label">`, which
 *   the shared CSS hides below `sm` when `collapse` is set;
 * - honour `disabled`, and `href` (render an anchor).
 */
export interface ChromeButtonRenderProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'color' | 'children' | 'role'> {
  /** The chrome role (not the ARIA `role` attribute). */
  chromeRole: ChromeRole;
  roleStyle: ChromeRoleStyle;
  /** Mantine colour name per tone, brand-aware (e.g. `tones.primary`). */
  tones: Record<ChromeTone, string>;
  /** The tone this control resolves to right now (toggle-aware). */
  tone: ChromeTone;
  label: string;
  /** Resolved Iconify id, and the semantic slot it came from (if any). */
  icon: string;
  iconSlot: ChromeIconName | null;
  rightIcon?: string;
  rightIconSlot?: ChromeIconName | null;
  badge: number;
  active: boolean;
  iconOnly: boolean;
  collapse: boolean;
  /** A tooltip wraps this control (it names an icon-only action), so the
   *  button need not draw a hover label of its own. */
  hasTooltip: boolean;
  /** The action group this control sits in (`ChromeButtonGroup`), if any. */
  group: string | null;
  href?: string;
  target?: string;
  rel?: string;
  /** Visible label content (the label, or the caller's override). */
  children: React.ReactNode;
  /** Caller-provided right section (replaces badge / right icon). */
  rightSection?: React.ReactNode;
  className: string;
  [dataAttr: `data-${string}`]: string | number | boolean | undefined;
}

export interface ChromeStyleComponents {
  /** Replaces the Mantine Button/ActionIcon behind every ChromeButton. */
  Button?: React.ForwardRefExoticComponent<
    ChromeButtonRenderProps & React.RefAttributes<HTMLButtonElement>
  >;
  /** Replaces the wrapper of a run of related actions (`ChromeButtonGroup`). */
  ButtonGroup?: React.ComponentType<ChromeButtonGroupRenderProps>;
}

export interface ChromeButtonGroupRenderProps {
  /** What the actions have in common, e.g. `find`, `read`, `mode`. */
  group: string;
  className: string;
  children: React.ReactNode;
}

/** Layout patch merged into every Plotly figure while the style is active
 *  (fonts, backgrounds, grid colours, colorway). Applied after the server
 *  template and before the figure's own layout. */
export type ChromePlotlyLayout = (
  scheme: 'light' | 'dark',
  /** The figure's own layout, so a style can skip what the figure already sets. */
  layout?: Record<string, unknown>,
) => Record<string, unknown>;

export interface ChromeStyle {
  id: string;
  name: string;
  tagline: string;
  roles: Record<ChromeRole, ChromeRoleStyle>;
  /** Button size of every chrome control; icon-only controls match its height. */
  controlSize: 'xs' | 'sm' | 'md';
  /** Icon size inside chrome controls, px. */
  iconSize: number;
  radius: MantineRadius;
  icons: Record<ChromeIconName, string>;
  layout: ChromeLayout;
  /** Which collapsible actions keep a visible label: `all` (default), only
   *  the `primary` one, or `none` (every action an icon with a tooltip). */
  actionLabels?: 'all' | 'primary' | 'none';
  /** Per-style Plotly layout patch (see `ChromePlotlyLayout`). */
  plotly?: ChromePlotlyLayout;
  /** Per-style Plotly defaults, merged UNDER the figure layout: they fill
   *  what a figure leaves unset (margins, legend placement, colorway) and
   *  never override a value the figure sets. */
  plotlyDefaults?: ChromePlotlyLayout;
  /** Merged into the Mantine theme while this style is active. */
  themeOverrides?: MantineThemeOverride;
  /** React slots a style may fill with its own components. */
  components?: ChromeStyleComponents;
}

export const BASE_CHROME_ICONS: Record<ChromeIconName, string> = {
  menu: 'mdi:menu',
  search: 'mdi:magnify',
  add: 'mdi:plus',
  save: 'mdi:content-save-outline',
  edit: 'mdi:pencil-outline',
  view: 'mdi:eye-outline',
  settings: 'mdi:cog-outline',
  feedback: 'mdi:comment-quote-outline',
  comments: 'mdi:comment-text-multiple-outline',
  analysis: 'mdi:select-group',
  filters: 'mdi:filter-variant',
  reset: 'mdi:filter-remove-outline',
  more: 'mdi:dots-vertical',
  moreFilters: 'mdi:tune-variant',
  lessFilters: 'mdi:chevron-up',
  hide: 'mdi:chevron-left',
  chevronDown: 'mdi:chevron-down',
  funnel: 'mdi:filter-check-outline',
  funnelView: 'mdi:chart-timeline-variant',
  back: 'mdi:arrow-left',
};

/** The normalised default: one filled primary, light secondaries, subtle
 *  icon buttons, every control at the same height. */
export const BASE_CHROME_STYLE: ChromeStyle = {
  id: 'base',
  name: 'Classic',
  tagline: 'The original look: a header bar and a tab sidebar',
  roles: {
    primary: { variant: 'filled', tone: 'primary' },
    secondary: { variant: 'light', tone: 'neutral' },
    quiet: { variant: 'subtle', tone: 'neutral' },
    toggle: { variant: 'light', tone: 'tertiary', activeVariant: 'filled' },
    danger: { variant: 'light', tone: 'tertiary' },
  },
  controlSize: 'xs',
  iconSize: 16,
  radius: 'md',
  icons: BASE_CHROME_ICONS,
  layout: {
    headerHeight: 50,
    navbarWidth: 250,
  },
};

let current: ChromeStyle = BASE_CHROME_STYLE;
const listeners = new Set<() => void>();

function applyToDocument(style: ChromeStyle) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.dataset.chrome = style.id;
  root.style.setProperty('--dc-header-h', `${style.layout.headerHeight}px`);
  root.style.setProperty(
    '--dc-header-h-mobile',
    `${style.layout.headerHeightMobile ?? style.layout.headerHeight}px`,
  );
}

applyToDocument(current);

export function getChromeStyle(): ChromeStyle {
  return current;
}

export function setChromeStyle(style: ChromeStyle): void {
  if (style === current) return;
  current = style;
  applyToDocument(style);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The active chrome style; re-renders when it changes. */
export function useChromeStyle(): ChromeStyle {
  return useSyncExternalStore(subscribe, getChromeStyle, getChromeStyle);
}

/** Mantine colour name for a tone, following the instance brand. */
export function useChromeTones(): Record<ChromeTone, string> {
  const accents = useBrandAccents();
  return { ...accents, neutral: 'gray', danger: 'red' };
}

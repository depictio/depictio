/**
 * Glass: the page layout of the default chrome (a sidebar and a dock).
 *
 *  ┌────────────────────────────────────────────────────────────┐
 *  │ ✿ depictio │ Dashboard › ▣ Tab                    ⚙ ☾ (TW) │ top bar
 *  ├─────────────┬──────────────────────────────────────────────┤
 *  │ TABS        │                                              │
 *  │ ▣ Overview  │   tiles, scrolling under the dock            │
 *  │ GROUP       │                                              │
 *  │ ▣ Petals    │                                              │
 *  │ ─────────── │                                              │
 *  │ ⚲ Filters 2 │        ┌──────────────────────────────┐      │
 *  │ ? Guide     │        │ ⌕ │ 💬 ⊙ ● │ [✎ Edit]         │ dock │
 *  │ « Collapse  │        └──────────────────────────────┘      │
 *  └─────────────┴──────────────────────────────────────────────┘
 *
 * The sidebar navigates (the tabs by name, Filters, the Guide) and folds to
 * an icon rail; the top bar says whose and where; the dock acts (search,
 * reading modes, the page's mode). A dock key that opens something stays
 * lit, with its name out, while that thing is open, and the panels it opens
 * float in beside it. Filters opens a drawer beside the sidebar that pushes
 * the canvas over.
 *
 * Below `sm` the sidebar becomes one bottom bar (Tabs, Filters, Search, More),
 * the dock's actions move into More, the top bar turns compact and the
 * drawers become bottom sheets.
 */
import React from 'react';
import { Drawer, MantineThemeContext, Tooltip, useMantineTheme } from '@mantine/core';
import type { MantineTheme } from '@mantine/core';
import { useReducedMotion } from 'motion/react';
import { ArrowLeft, BookOpenText, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import {
  ChromeButton,
  ChromeButtonGroup,
  useChromeStyle,
  Z_LAYERS,
} from 'depictio-react-core';

import { CONTENT_WIDTHS, useContentWidthPref } from '../../../hooks/useContentWidthPref';
import type { HeaderAction } from '../../Header';
import type { DashboardShellProps } from '../../shell/types';
import { STROKE } from './icons';
import {
  DrawerHead,
  ProfileRows,
  ProfileTile,
  RailTabs,
  SideRow,
  TabList,
  ThemeTile,
  TopBar,
} from './parts';
import './layout.css';

/** The sidebar, open (names) and folded (the icon rail), and the top bar's
 *  height. Both float off the page edge. */
const SIDE_W = { open: 244, folded: 76 };
const TOP_H = 66;
/** The reader's Compact page width also tightens the chrome around it
 *  (the open sidebar keeps its width: tab names must stay whole). */
const DENSE = { top: 8, folded: 8 };
const FILTERS_W = 328;
const SIDE_KEY = 'depictio-glass-sidebar';

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = sessionStorage.getItem(key) ?? localStorage.getItem(key);
    if (v === '1') return true;
    if (v === '0') return false;
  } catch {
    // Storage blocked: the default.
  }
  return fallback;
}
function writeFlag(key: string, value: boolean, persist: 'session' | 'local'): void {
  try {
    (persist === 'local' ? localStorage : sessionStorage).setItem(key, value ? '1' : '0');
  } catch {
    // The choice lasts for this page only.
  }
}

/** Mantine's defaults turned to face away from the surface they open from:
 *  right of the sidebar, below the top bar, above the dock. */
function useFacing(tooltip: string, menu: string): MantineTheme {
  const theme = useMantineTheme();
  return React.useMemo(() => {
    const c = theme.components;
    const face = (name: string, position: string) => ({
      ...c[name],
      defaultProps: { ...(c[name]?.defaultProps as object), position },
    });
    return {
      ...theme,
      components: {
        ...c,
        Tooltip: face('Tooltip', tooltip),
        Menu: face('Menu', menu),
        Popover: face('Popover', menu),
      },
    };
  }, [theme, tooltip, menu]);
}

/**
 * Which of the page's panels are open right now. Search, Comments, Settings
 * and the notes are opened by shared pieces that keep their state to
 * themselves; they announce it only by being in the document, so the shell
 * watches for them and lights the key that opened each.
 */
const SURFACES: [string, string][] = [
  ['comments', '[data-testid="comments-drawer"]'],
  ['analysis', '.dc-analysis-panel'],
  ['search', '[data-testid="dashboard-spotlight"]'],
  ['settings', '[data-testid="settings-modal"]'],
  [
    'notes',
    '.mantine-Drawer-root:has([aria-label="Expand notes to fullscreen"], [aria-label="Restore notes drawer"])',
  ],
];
function useOpenSurfaces(): string {
  const [open, setOpen] = React.useState('');
  React.useEffect(() => {
    let frame = 0;
    // A Mantine root stays in the document while closed; open means its
    // content is drawn.
    const CONTENT = '.mantine-Drawer-content, .mantine-Modal-content';
    const shown = (q: string) =>
      Array.from(document.querySelectorAll(q)).some((el) => {
        const box = el.matches(CONTENT) ? el : el.querySelector(CONTENT);
        return Boolean(box && box.getClientRects().length > 0);
      });
    const check = () => {
      frame = 0;
      const next = SURFACES.filter(([, q]) => shown(q))
        .map(([name]) => name)
        .join(' ');
      setOpen((prev) => (prev === next ? prev : next));
    };
    const watcher = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(check);
    });
    watcher.observe(document.body, { childList: true, subtree: true });
    check();
    return () => {
      watcher.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return open;
}

/**
 * Menus opened from the filter panel's own toolbar (map panel, sort, more)
 * drop below their button by default, straight over the first filter
 * section. Here they open beside the panel instead, level with the button
 * that opened them, so the filters stay readable while the menu is up.
 * Mantine positions the dropdown inline; the attribute lets layout.css
 * override that with the coordinates set here.
 */
function useMenusBeside(card: React.RefObject<HTMLElement | null>): void {
  React.useEffect(() => {
    const host = card.current;
    if (!host) return;
    const DROPDOWN = '.mantine-Menu-dropdown, .mantine-Popover-dropdown';
    let watcher: MutationObserver | null = null;
    let stop = 0;
    const release = () => {
      watcher?.disconnect();
      watcher = null;
      window.clearTimeout(stop);
    };
    const arm = (event: Event) => {
      const trigger = (event.target as Element | null)?.closest?.(
        '.dc-filter-panel-header button',
      );
      if (!trigger) return;
      release();
      const seen = new Set(document.querySelectorAll(DROPDOWN));
      const place = () => {
        const fresh = Array.from(document.querySelectorAll<HTMLElement>(DROPDOWN)).find(
          (el) => !seen.has(el),
        );
        if (!fresh) return;
        const edge = host.getBoundingClientRect().right;
        fresh.style.setProperty('--gl-beside-x', `${Math.round(edge + 10)}px`);
        fresh.style.setProperty(
          '--gl-beside-y',
          `${Math.round(trigger.getBoundingClientRect().top - 6)}px`,
        );
        fresh.setAttribute('data-hy-beside', '');
        release();
      };
      watcher = new MutationObserver(place);
      watcher.observe(document.body, { childList: true, subtree: true });
      stop = window.setTimeout(release, 1000);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') arm(event);
    };
    host.addEventListener('click', arm, true);
    host.addEventListener('keydown', onKey, true);
    return () => {
      release();
      host.removeEventListener('click', arm, true);
      host.removeEventListener('keydown', onKey, true);
    };
  }, [card]);
}

/**
 * Width of a thin scrollbar here (0 where scrollbars overlay the content).
 * The filter panel's list reserves a gutter for one; layout.css slides that
 * gutter into the panel's own padding by this much, so the list's cards end
 * on the same edge as the search field above them.
 */
function useScrollbarWidth(): void {
  React.useEffect(() => {
    const probe = document.createElement('div');
    probe.style.cssText =
      'position:absolute;top:-200px;left:-200px;width:100px;height:100px;overflow:auto;scrollbar-gutter:stable;scrollbar-width:thin;visibility:hidden';
    document.body.appendChild(probe);
    const width = probe.offsetWidth - probe.clientWidth;
    probe.remove();
    document.documentElement.style.setProperty('--gl-sbw', `${width}px`);
    return () => {
      document.documentElement.style.removeProperty('--gl-sbw');
    };
  }, []);
}

/** Offsets the portalled panels (outside the shell) position from. */
function useRootOffsets(vars: Record<string, string>): void {
  const key = JSON.stringify(vars);
  React.useEffect(() => {
    const root = document.documentElement;
    const entries = Object.entries(JSON.parse(key) as Record<string, string>);
    for (const [k, v] of entries) root.style.setProperty(k, v);
    return () => {
      for (const [k] of entries) root.style.removeProperty(k);
    };
  }, [key]);
}

/** Wraps an action so CSS can find the key that opened a panel. */
const Slot: React.FC<{ action: HeaderAction }> = ({ action }) => (
  <span className="hy-slot" data-hy-slot={action.id}>
    {action.node}
  </span>
);

/** The dock's clusters: find | read | author + mode (the primary last). */
const OFF_DOCK = new Set(['filters', 'settings', 'feedback']);
function dockClusters(actions: HeaderAction[]) {
  const rank = (a: HeaderAction) =>
    a.group === 'find' ? 0 : a.group === 'author' || a.group === 'mode' ? 2 : 1;
  const names = ['dock-find', 'dock-read', 'dock-mode'];
  const out: { key: string; actions: HeaderAction[] }[] = [];
  for (let r = 0; r < 3; r++) {
    const run = actions.filter((a) => !OFF_DOCK.has(a.id) && rank(a) === r);
    if (run.length) out.push({ key: names[r], actions: run });
  }
  return out;
}

const GlassShell: React.FC<DashboardShellProps> = (props) =>
  props.isNarrow ? <PhoneLayout {...props} /> : <DeskLayout {...props} />;

export default GlassShell;

/* ================================================================ desktop */

const DeskLayout: React.FC<DashboardShellProps> = ({
  mode,
  ready,
  header,
  nav,
  boot,
  canvas,
  topStrip,
  filters,
  overlays,
  outside,
  inspector,
  analysis,
}) => {
  const reduce = useReducedMotion();
  const sideTheme = useFacing('right', 'right-start');
  const topTheme = useFacing('bottom', 'bottom-end');
  const dockTheme = useFacing('top', 'top');
  const showing = useOpenSurfaces();
  const drawerCard = React.useRef<HTMLDivElement>(null);
  useMenusBeside(drawerCard);
  useScrollbarWidth();
  const hasFilters = filters.members.length > 0 || mode === 'edit';
  // The reader's page width: the canvas centres in it (as in the default
  // layout), and Compact tightens the bar, the sidebar and the dock as well.
  const { width: pageWidth } = useContentWidthPref();
  const contentMax = CONTENT_WIDTHS.find((w) => w.value === pageWidth)?.maxPx ?? null;
  const dense = pageWidth === 'compact';

  // The Filters drawer, beside the sidebar. Its open state is the page's own
  // (`filters.docked`): each tab opens with its configured default
  // (`filter_panel_default`), a toggle is remembered per dashboard family, and
  // the panel's own requests to show a filter (search, summary chips) expand
  // it through the same toggle.
  const filtersOpen = filters.docked.opened && (hasFilters || !ready);
  const dockedRef = React.useRef(filters.docked);
  dockedRef.current = filters.docked;
  const setFilters = React.useCallback((next: boolean) => {
    if (dockedRef.current.opened !== next) dockedRef.current.toggle();
  }, []);

  // The sidebar: open by default, folded to the rail on request (remembered).
  // Glass's floating cards take more width than Brand's, so while the Filters
  // drawer is open its sidebar folds to the rail by itself and opens again
  // when the drawer closes. The reader's own choice wins: unfolding it while
  // the drawer is open keeps it open, folding it by hand keeps it folded.
  const [sideChoice, setSideChoice] = React.useState(() => readFlag(SIDE_KEY, true));
  const [keepSide, setKeepSide] = React.useState(false);
  React.useEffect(() => {
    if (!filtersOpen) setKeepSide(false);
  }, [filtersOpen]);
  const autoFold = filtersOpen && !keepSide;
  const sideOpen = sideChoice && !autoFold;
  const toggleSide = () => {
    const next = !sideOpen;
    if (next && filtersOpen) setKeepSide(true);
    setSideChoice(next);
    writeFlag(SIDE_KEY, next, 'local');
  };

  // Esc folds the drawer, unless a field or a menu has a use for the key.
  React.useEffect(() => {
    if (!filtersOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest('input, textarea, select, [role="listbox"], [role="dialog"], [role="menu"]')) return;
      setFilters(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [filtersOpen, setFilters]);

  // The canvas changes width when the drawer or the sidebar opens or folds;
  // charts size themselves on a window resize, so they get one once the
  // grid has settled.
  React.useEffect(() => {
    const id = window.setTimeout(() => window.dispatchEvent(new Event('resize')), reduce ? 0 : 320);
    return () => window.clearTimeout(id);
  }, [filtersOpen, sideOpen, reduce]);

  // Glass lifts Plotly's toolbar into a figure tile's header row, and the
  // title shortens to give it room while it shows. The toolbar's width
  // depends on the figure's buttons, so the tile learns it on the way in.
  React.useEffect(() => {
    const onOver = (e: PointerEvent) => {
      const tile = e.target instanceof Element ? e.target.closest('.dc-tile--figure') : null;
      if (!(tile instanceof HTMLElement)) return;
      const bar = tile.querySelector<HTMLElement>('.js-plotly-plot .modebar');
      if (bar) tile.style.setProperty('--gl-modebar-w', `${bar.offsetWidth}px`);
    };
    document.addEventListener('pointerover', onOver);
    return () => document.removeEventListener('pointerover', onOver);
  }, []);

  const sideW = sideOpen ? SIDE_W.open : SIDE_W.folded - (dense ? DENSE.folded : 0);
  const drawerW = mode === 'edit' ? FILTERS_W + 16 : FILTERS_W;
  const drawerCol = filtersOpen ? `calc(${drawerW}px + var(--gl-drawer-gap))` : '0px';
  const topH = TOP_H - (dense ? DENSE.top : 0);

  const byId = (id: string) => header.model.actions.find((a) => a.id === id);
  const topKeys = ['feedback', 'settings'].map(byId).filter(Boolean) as HeaderAction[];
  const clusters = dockClusters(header.model.actions);

  const aside = inspector.aside as { width?: unknown } | undefined;
  const inspectorW = inspector.enabled ? (typeof aside?.width === 'number' ? aside.width : 360) : 0;
  // The Analysis panel floats as a card off the right edge: room for it and
  // its margin.
  const padR = analysis.open ? analysis.widthPx + 12 : 0;
  const navOffset = `calc(${sideW}px + ${drawerCol})`;

  useRootOffsets({ '--gl-top-offset': `${topH}px`, '--gl-nav-offset': navOffset });

  const shellStyle = {
    '--gl-pad-r': `${padR}px`,
    '--gl-top-h': `${topH}px`,
    '--gl-content-max': contentMax ? `${contentMax}px` : '100%',
    '--app-shell-header-offset': `${topH}px`,
    '--app-shell-navbar-offset': navOffset,
    '--app-shell-aside-offset': `${inspectorW}px`,
    gridTemplateRows: `${topH}px minmax(0, 1fr)`,
    gridTemplateColumns: `${sideW}px ${drawerCol} minmax(0, 1fr)${inspectorW ? ` ${inspectorW}px` : ''}`,
    transition: reduce ? 'none' : 'grid-template-columns 280ms cubic-bezier(0.2, 0.8, 0.2, 1)',
  } as React.CSSProperties;

  const ICON = 19;
  const stroke = STROKE;

  return (
    <div
      className="hy-shell"
      data-testid="app-shell"
      data-mode={mode}
      data-side={sideOpen ? 'open' : 'folded'}
      data-density={dense ? 'compact' : undefined}
      data-panel={filtersOpen ? 'filters' : undefined}
      data-hy-showing={showing || undefined}
      style={shellStyle}
    >
      <MantineThemeContext.Provider value={topTheme}>
        <TopBar
          model={header.model}
          home={nav.model.backHref}
          dense={dense}
          editing={mode === 'edit'}
          after={
            <div className="hy-top-keys">
              <ChromeButtonGroup group="top">
                {topKeys.map((a) => (
                  <Slot key={a.id} action={a} />
                ))}
              </ChromeButtonGroup>
              <ThemeTile place="top" />
              <ProfileTile />
            </div>
          }
        />
      </MantineThemeContext.Provider>

      <MantineThemeContext.Provider value={sideTheme}>
        <nav className="hy-side" aria-label="Dashboard" data-tour-id="sidebar">
          {/* The sidebar's own fold switch, at its head: the logo up in the
              top bar only ever goes home. */}
          <div className="hy-side-head">
            {sideOpen && mode !== 'edit' && <span className="hy-eyebrow hy-side-heading">Tabs</span>}
            <span className="hy-flex" />
            <Tooltip
              label={sideOpen ? 'Collapse sidebar' : 'Expand sidebar'}
              withArrow
              openDelay={200}
            >
              <button
                type="button"
                className="hy-fold"
                aria-label={sideOpen ? 'Collapse sidebar' : 'Expand sidebar'}
                aria-expanded={sideOpen}
                data-testid="glass-side-toggle"
                onClick={toggleSide}
              >
                {sideOpen ? (
                  <PanelLeftClose size={18} strokeWidth={stroke} aria-hidden />
                ) : (
                  <PanelLeftOpen size={18} strokeWidth={stroke} aria-hidden />
                )}
              </button>
            </Tooltip>
          </div>
          <div className="hy-side-scroll">
            {sideOpen ? (
              mode === 'edit' ? (
                // The editor's own tab list: rename, move, add, the group menus.
                <div className="hy-side-editor">{nav.node}</div>
              ) : (
                <TabList nav={nav.model} tools={false} />
              )
            ) : (
              <div className="hy-rail-tabs">
                <RailTabs nav={nav.model} />
              </div>
            )}
          </div>
          <div className="hy-rule" role="separator" />
          <div className="hy-side-tools">
            {hasFilters && (
              <ChromeButtonGroup group="rail">
                <ChromeButton
                  role="quiet"
                  iconOnly
                  icon="filters"
                  label={filtersOpen ? 'Hide filters' : 'Filters'}
                  badge={filters.count}
                  tooltip={sideOpen || filtersOpen ? null : undefined}
                  aria-expanded={filtersOpen}
                  data-hy-open={filtersOpen || undefined}
                  data-testid="glass-filters"
                  onClick={() => setFilters(!filtersOpen)}
                >
                  Filters
                </ChromeButton>
              </ChromeButtonGroup>
            )}
            {nav.model.guide && (
              <SideRow
                open={sideOpen}
                icon={<BookOpenText size={ICON} strokeWidth={stroke} aria-hidden />}
                label="Guide"
                tooltip={nav.model.guide.open ? 'Close the guide' : 'Guide'}
                href={nav.model.guide.href}
                onClick={nav.model.guide.onClick}
                active={nav.model.guide.open}
              />
            )}
          </div>
          <div className="hy-side-spacer" />
          <div className="hy-side-foot">
            <SideRow
              open={sideOpen}
              icon={<ArrowLeft size={ICON - 1} strokeWidth={stroke} aria-hidden />}
              label="All dashboards"
              href={nav.model.backHref}
            />
          </div>
        </nav>
      </MantineThemeContext.Provider>

      <aside
        className="hy-drawer"
        aria-label="Filters"
        aria-hidden={!filtersOpen || undefined}
        {...({ inert: filtersOpen ? undefined : '' } as Record<string, string | undefined>)}
      >
        <div ref={drawerCard} className="hy-drawer-card" style={{ width: drawerW }}>
          <DrawerHead
            title="Filters"
            meta={
              filters.count > 0 ? (
                <span className="hy-meta" aria-label={`${filters.count} active`}>
                  {filters.count}
                </span>
              ) : null
            }
            onClose={() => setFilters(false)}
          />
          <div className="hy-drawer-body hy-drawer-body--filters">
            {/* Always the docked form: the docked map draws at its foot,
                and it expands itself when asked to reveal a filter. Its own
                hide button is dropped (layout.css); the head closes it. */}
            {ready && filters.panel({ docked: true })}
          </div>
        </div>
      </aside>

      <main className="hy-main">
        <div
          className="hy-stage"
          style={{
            paddingRight: padR,
            transition: reduce ? 'none' : 'padding-right 250ms ease',
          }}
        >
          {boot}
          {ready && topStrip && <div className="hy-strip">{topStrip}</div>}
          {ready && canvas}
        </div>

        {ready && clusters.length > 0 && (
          <MantineThemeContext.Provider value={dockTheme}>
            <nav className="hy-dock" aria-label="Dashboard actions">
              {clusters.map((c, i) => (
                <React.Fragment key={c.key}>
                  {i > 0 && <span className="hy-dock-sep" aria-hidden />}
                  <ChromeButtonGroup group={c.key}>
                    {c.actions.map((a) => (
                      <Slot key={a.id} action={a} />
                    ))}
                  </ChromeButtonGroup>
                </React.Fragment>
              ))}
            </nav>
          </MantineThemeContext.Provider>
        )}
        {overlays}
      </main>

      {inspectorW > 0 && <aside className="hy-inspector">{inspector.node}</aside>}

      {outside}
    </div>
  );
};

/* ================================================================== phone */

const BAR_H = 'calc(80px + env(safe-area-inset-bottom, 0px))';

const PhoneLayout: React.FC<DashboardShellProps> = ({
  mode,
  ready,
  header,
  nav,
  boot,
  canvas,
  topStrip,
  filters,
  overlays,
  outside,
}) => {
  const showing = useOpenSurfaces();
  const [sheet, setSheet] = React.useState<'tabs' | 'more' | null>(null);
  const hasFilters = filters.members.length > 0;

  // The bar takes the page's foot: what reads the offset (the notes button,
  // the default main height) moves up by it.
  useRootOffsets({ '--dc-bottom-offset': BAR_H, '--gl-top-offset': '60px' });

  const byIds = (ids: string[]) => header.model.actions.filter((a) => ids.includes(a.id));
  const topActions = byIds(['edit', 'exit-edit', 'save']);
  const search = byIds(['search']);
  const more = header.model.actions.filter(
    (a) => !['edit', 'exit-edit', 'save', 'search', 'filters'].includes(a.id),
  );

  // A More row that opens a panel of its own closes the sheet, so the two
  // never stack. A menu trigger (Add) keeps it open.
  const closeOnAction = (e: React.MouseEvent) => {
    const hit = (e.target as HTMLElement).closest('.dc-action');
    if (hit && !hit.getAttribute('aria-haspopup')) setSheet(null);
  };

  return (
    <div
      className="hy-shell hy-shell--phone"
      data-testid="app-shell"
      data-mode={mode}
      data-hy-showing={showing || undefined}
      style={
        {
          '--app-shell-header-offset': '60px',
          '--app-shell-navbar-offset': '0px',
          '--app-shell-aside-offset': '0px',
        } as React.CSSProperties
      }
    >
      <TopBar
        model={header.model}
        home={nav.model.backHref}
        compact
        after={
          topActions.length > 0 ? (
            <ChromeButtonGroup group="topbar">
              {topActions.map((a) => (
                <React.Fragment key={a.id}>{a.node}</React.Fragment>
              ))}
            </ChromeButtonGroup>
          ) : null
        }
      />
      <main className="hy-main">
        <div className="hy-stage">
          {boot}
          {ready && topStrip && <div className="hy-strip">{topStrip}</div>}
          {ready && canvas}
        </div>
        {overlays}
      </main>

      <nav className="hy-tabbar" aria-label="Dashboard" data-tour-id="sidebar">
        <ChromeButtonGroup group="tabbar">
          <ChromeButton
            role="quiet"
            iconOnly
            icon="menu"
            label="Tabs"
            tooltip={null}
            aria-expanded={sheet === 'tabs'}
            data-hy-open={sheet === 'tabs' || undefined}
            onClick={() => setSheet(sheet === 'tabs' ? null : 'tabs')}
          />
          {hasFilters && (
            <ChromeButton
              role="quiet"
              iconOnly
              icon="filters"
              label="Filters"
              tooltip={null}
              badge={filters.count}
              aria-expanded={filters.drawer.opened}
              data-hy-open={filters.drawer.opened || undefined}
              onClick={filters.drawer.open}
            />
          )}
          {search.map((a) => (
            <Slot key={a.id} action={a} />
          ))}
          <ChromeButton
            role="quiet"
            iconOnly
            icon="more"
            label="More"
            tooltip={null}
            aria-expanded={sheet === 'more'}
            data-hy-open={sheet === 'more' || undefined}
            onClick={() => setSheet(sheet === 'more' ? null : 'more')}
          />
        </ChromeButtonGroup>
      </nav>

      <Sheet
        opened={sheet === 'tabs'}
        onClose={() => setSheet(null)}
        title={mode === 'edit' ? 'Tabs and groups' : 'Tabs'}
      >
        {mode === 'edit' ? (
          <div className="hy-side-editor hy-side-editor--sheet">{nav.node}</div>
        ) : (
          <TabList nav={nav.model} onNavigate={() => setSheet(null)} />
        )}
      </Sheet>

      {ready && (
        <Sheet
          opened={filters.drawer.opened}
          onClose={filters.drawer.close}
          title="Filters"
          meta={filters.count > 0 ? <span className="hy-meta">{filters.count} active</span> : null}
          tall
        >
          <div className="hy-sheet-filters">{filters.panel()}</div>
        </Sheet>
      )}

      <Sheet opened={sheet === 'more'} onClose={() => setSheet(null)} title="More">
        <div className="hy-sheet-list" onClick={closeOnAction}>
          <ChromeButtonGroup group="sheet">
            {more.map((a) => (
              <React.Fragment key={a.id}>{a.node}</React.Fragment>
            ))}
          </ChromeButtonGroup>
          <div className="hy-sheet-rule" role="separator" />
          <ThemeTile place="sheet" />
          <ProfileRows />
        </div>
      </Sheet>

      {outside}
    </div>
  );
};

/** A bottom sheet: a grab bar, the panel title, then the content. */
const Sheet: React.FC<{
  opened: boolean;
  onClose: () => void;
  title: string;
  meta?: React.ReactNode;
  tall?: boolean;
  children: React.ReactNode;
}> = ({ opened, onClose, title, meta, tall, children }) => (
  <Drawer
    opened={opened}
    onClose={onClose}
    position="bottom"
    size={tall ? '88dvh' : 'auto'}
    offset={8}
    zIndex={Z_LAYERS.overlay}
    withCloseButton={false}
    classNames={{ content: tall ? 'hy-sheet hy-sheet--tall' : 'hy-sheet', body: 'hy-sheet-body' }}
    overlayProps={{ backgroundOpacity: 0.32, blur: 3 }}
    aria-label={title}
  >
    <div className="hy-sheet-grab" aria-hidden />
    <DrawerHead title={title} meta={meta} onClose={onClose} />
    <div className="hy-sheet-content">{children}</div>
  </Drawer>
);

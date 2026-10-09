import React from 'react';
import { AppShell, Box, Drawer } from '@mantine/core';
import { FILTER_PANEL_RAIL_WIDTH, useChromeStyle, Z_LAYERS } from 'depictio-react-core';

import FilterPanelResizer, { FILTER_PANEL_RESIZER_WIDTH } from '../../components/FilterPanelResizer';
import type { DashboardShellProps } from './types';

/**
 * The page height left under the header (and above a bottom action bar).
 * Every Shell that keeps the AppShell header uses it for its main area.
 */
export const SHELL_MAIN_HEIGHT =
  'calc(100dvh - var(--dc-header-h-current, 50px) - var(--dc-bottom-offset, 0px))';

/**
 * The default layout: header across the top, the tab sidebar on the left,
 * then the docked filter column (resizable, collapsible to a rail) beside the
 * canvas, the inspector as the AppShell aside. Below `sm` the filters move to
 * a drawer opened from the header.
 */
const DefaultShell: React.FC<DashboardShellProps> = ({
  isNarrow,
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
  const chrome = useChromeStyle();
  const { docked } = filters;
  return (
    <AppShell
      header={{
        height: {
          base: chrome.layout.headerHeightMobile ?? chrome.layout.headerHeight,
          sm: chrome.layout.headerHeight,
        },
      }}
      navbar={{
        width: chrome.layout.navbarWidth,
        breakpoint: 'sm',
        collapsed: { mobile: !nav.mobileOpened, desktop: !nav.desktopOpened },
      }}
      aside={inspector.aside}
      padding={0}
      transitionDuration={300}
      transitionTimingFunction="ease"
    >
      <AppShell.Header data-tour-id="header-title" className="dc-header">
        {header.node}
      </AppShell.Header>

      <AppShell.Navbar p="md" data-tour-id="sidebar" className="dc-sidebar">
        {nav.node}
      </AppShell.Navbar>

      <AppShell.Main
        style={{
          height: SHELL_MAIN_HEIGHT,
          // The Analysis panel is a Drawer, not an AppShell slot (the single
          // `aside` belongs to the inspector), so nothing offsets the content
          // for it and it would sit on top of the rightmost tiles — the ones
          // a user opens it to lasso a group out of. Pad by exactly its width
          // and let the grid re-measure (see ANALYSIS_PANEL_TOGGLE_EVENT).
          // Not on a narrow viewport, where the panel is ~92vw and padding
          // would leave no dashboard at all: there it overlays, as a drawer.
          paddingRight: analysis.open && !isNarrow ? analysis.widthPx : 0,
          transition: 'padding-right 250ms ease',
        }}
      >
        {boot}
        {ready && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              height: '100%',
              width: '100%',
              overflow: 'hidden',
            }}
          >
            <div
              ref={docked.layoutRef}
              // Cast because `CSSProperties` has no index signature for custom
              // properties, and the name is a constant rather than a literal.
              style={
                {
                  // The panel track comes from a variable so a drag can move it
                  // without a React render — see `useFilterPanelWidth`. React
                  // owns the value everywhere else, including here on every
                  // commit.
                  [docked.widthVar]: `${docked.opened ? docked.width : FILTER_PANEL_RAIL_WIDTH}px`,
                  display: 'grid',
                  // Panel | drag handle | content. The handle gets a real
                  // column rather than floating over the panel edge, so it
                  // can't overlap the controls underneath. The track count
                  // stays at three whatever the panel's state, because
                  // `grid-template-columns` only animates between templates
                  // with matching track counts.
                  gridTemplateColumns: isNarrow
                    ? '1fr'
                    : `var(${docked.widthVar}) ` +
                      `${docked.opened ? FILTER_PANEL_RESIZER_WIDTH : 0}px 1fr`,
                  // Matches the panel's own toggle duration so the grid items,
                  // which animate on `body.panel-transitioning`, stay in
                  // lockstep. Dropped while dragging: the transition is for the
                  // collapse toggle, and easing every pointermove over 300ms is
                  // what makes the handle feel towed rather than moved.
                  transition: docked.resizing ? 'none' : 'grid-template-columns 300ms ease',
                  flex: 1,
                  minHeight: 0,
                  width: '100%',
                  gap: 4,
                  overflow: 'hidden',
                } as React.CSSProperties
              }
            >
              {!isNarrow && (
                <Box
                  px={4}
                  py={4}
                  style={{
                    // The panel scrolls its own filter list, so this wrapper
                    // must not scroll too — that is what keeps the docked map
                    // pinned to the bottom while a long list scrolls past it.
                    height: '100%',
                    minWidth: 0,
                    overflow: 'hidden',
                  }}
                >
                  {filters.panel({ docked: true })}
                </Box>
              )}
              {!isNarrow && (
                <FilterPanelResizer
                  onPointerDown={docked.beginResize}
                  onNudge={docked.nudge}
                  collapsed={!docked.opened}
                />
              )}
              {canvas}
            </div>
            {topStrip}
          </div>
        )}
        {/* Narrow screens: the panel the grid no longer has room for. No
            collapse control inside — the drawer's own close is the way out. */}
        {ready && isNarrow && (
          <Drawer
            opened={filters.drawer.opened}
            onClose={filters.drawer.close}
            position="left"
            size="min(320px, 85vw)"
            zIndex={Z_LAYERS.overlay}
            title="Filters"
          >
            {filters.panel()}
          </Drawer>
        )}
        {overlays}
      </AppShell.Main>

      {inspector.enabled && <AppShell.Aside p={0}>{inspector.node}</AppShell.Aside>}

      {outside}
    </AppShell>
  );
};

export default DefaultShell;

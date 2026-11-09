import React from 'react';
import { Badge, Drawer, Group, SegmentedControl, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  ANALYSIS_PANEL_TOGGLE_EVENT,
  ChromeButton,
  getChromeStyle,
  dispatchPanelToggle,
  useGroupingColor,
  Z_LAYERS,
} from 'depictio-react-core';
import type { ColorByState } from 'depictio-react-core';

/**
 * Width of the docked panel, in pixels so the apps can pad their content
 * column by exactly this much (see `ANALYSIS_PANEL_TOGGLE_EVENT`).
 *
 * 360 was too tight: a group card carrying its column, its dataset and a
 * sample of its values wrapped into a stack of fragments, and dropping to the
 * theme's smallest font to compensate made the panel hard to read rather than
 * compact. This fits a sentence and a row of value chips at normal size.
 */
export const ANALYSIS_PANEL_WIDTH_PX = 440;

/** The Labels tab holds a grid, so the panel widens while it is shown. */
export const LABELS_PANEL_WIDTH_PX = 760;

export type AnalysisTab = 'groups' | 'labels';

/** The panel's width for a tab, in pixels (what the apps pad by). */
export const analysisPanelWidthPx = (tab: AnalysisTab) =>
  tab === 'labels' ? LABELS_PANEL_WIDTH_PX : ANALYSIS_PANEL_WIDTH_PX;

/** Capped in vw like the filter drawer, so a phone keeps a strip of dashboard
 *  in view. Below that cap the apps stop padding and the panel overlays. */
const panelWidth = (tab: AnalysisTab) => `min(${analysisPanelWidthPx(tab)}px, 92vw)`;

/** The panel's slide, which the content column's padding transition matches.
 *  Mantine's Drawer default. */
const PANEL_TRANSITION_MS = 250;

/** The AppShell header height of the active chrome style. The panel starts
 *  below it so the header — including this button, the only way out of the
 *  mode — stays visible and clickable while the panel is docked. */
const dashboardHeaderHeight = () => getChromeStyle().layout.headerHeight;

/**
 * Header home of the Grouping panel (select & compare, issue #89).
 *
 * Grouping is dashboard-family state: groups and the Color-by mode are shared
 * across a multi-tab dashboard's tabs, and Color-by recolors every figure on
 * screen. A mode with dashboard-wide effect must stay visible even when the
 * (per-tab) filter panel is collapsed, so it lives in the header — next to the
 * other global controls — as a button that always shows whether the mode is
 * active, with the full panel docked beside the dashboard.
 *
 * **Why a non-modal Drawer and not a Popover.** The panel used to hang in a
 * Popover, and Mantine dismisses a Popover on mousedown outside it — which is
 * exactly the mousedown that starts a lasso on a figure. Making a group meant
 * watching the panel vanish the instant you acted on what it told you to do.
 * So the panel docks instead: no overlay, no focus trap, no scroll lock, and
 * `closeOnClickOutside` off, which leaves the dashboard fully live underneath
 * (Mantine's drawer viewport is `pointer-events: none`; only the panel itself
 * takes clicks). Lasso a cohort, save it, lasso the next — the panel stays put
 * the whole way through.
 *
 * `opened` is still controlled by the app, and analysis mode (`armed`) is
 * still tracked separately from it: closing the panel with its × keeps the
 * mode on, so the capability markers survive a user who wants the room back,
 * and this button remains the explicit way out of the mode.
 */
const GroupingHeaderControl: React.FC<{
  groupCount: number;
  colorBy: ColorByState;
  opened: boolean;
  onOpenedChange: (opened: boolean) => void;
  /** Whether analysis mode is on (see the note above — not the same as
   *  `opened`). Drives the button's active styling. */
  armed: boolean;
  /** Button press: toggles the panel AND the mode together. */
  onToggle: () => void;
  /** Whether the app pads its content column for this panel. False on a narrow
   *  viewport, where the panel is ~92vw and padding would leave no dashboard
   *  at all — there it overlays, and there is no swing to announce. */
  pushesContent: boolean;
  /** The SelectionGroupsPanel node, owned by the app (state is the app's). */
  children: React.ReactNode;
  /** The Labels tab (session annotations), when the app offers it. */
  labels?: React.ReactNode;
  tab?: AnalysisTab;
  onTabChange?: (tab: AnalysisTab) => void;
}> = ({
  groupCount,
  colorBy,
  opened,
  onOpenedChange,
  armed,
  onToggle,
  pushesContent,
  children,
  labels,
  tab = 'groups',
  onTabChange,
}) => {
  const shown: AnalysisTab = labels ? tab : 'groups';
  const shownRef = React.useRef(shown);
  // Tertiary under a brand, violet otherwise — either way distinct from the
  // Edit and Save buttons beside it (see `useGroupingColor`).
  const groupingColor = useGroupingColor();

  // Tell the dashboard grid the content column is about to lose (or regain)
  // this much width, so it re-lays out and pumps resize events for the length
  // of the slide — the same contract the sidebar and the filter panel use.
  // Without it the rightmost tiles stay under the panel, which is where the
  // user was trying to lasso.
  //
  // Only on an actual toggle. The grid applies the swing as a delta on the
  // width it measures at that moment, so announcing the mount state would tell
  // it the column had just *gained* 440px it never lost, and it would lay out
  // wider than its container until the observer caught up.
  const announced = React.useRef(false);
  React.useEffect(() => {
    if (!announced.current) {
      announced.current = true;
      return;
    }
    if (!pushesContent) return;
    dispatchPanelToggle(ANALYSIS_PANEL_TOGGLE_EVENT, {
      willBeOpen: opened,
      swingPx: analysisPanelWidthPx(shownRef.current),
      durationMs: PANEL_TRANSITION_MS,
    });
  }, [opened, pushesContent]);

  // Switching tab while open changes the panel's width by the difference: the
  // same announcement, with the grid told it loses (or regains) only that much.
  React.useEffect(() => {
    const before = shownRef.current;
    shownRef.current = shown;
    if (before === shown || !opened || !pushesContent) return;
    const delta = analysisPanelWidthPx(shown) - analysisPanelWidthPx(before);
    dispatchPanelToggle(ANALYSIS_PANEL_TOGGLE_EVENT, {
      willBeOpen: delta > 0,
      swingPx: Math.abs(delta),
      durationMs: PANEL_TRANSITION_MS,
    });
  }, [shown, opened, pushesContent]);
  // Base name "Analysis": the panel spans visual encoding (color/split by a
  // column), group annotation and group comparison — broader than any one of
  // those. When a Color-by mode is on the label names its target ("Analysis:
  // by groups" / "Analysis: by species") so the active dashboard-wide
  // override is always spelled out.
  const modeLabel = (() => {
    switch (colorBy.kind) {
      case 'groups':
        return 'by groups';
      case 'column':
        return `by ${colorBy.columnName}`;
      default:
        return null;
    }
  })();

  return (
    <>
      <ChromeButton
        role="toggle"
        collapse
        active={Boolean(modeLabel) || armed}
        icon="analysis"
        label={modeLabel ? `Analysis: ${modeLabel}` : 'Analysis'}
        tooltip="Save selections as groups, color or split every figure, compare groups"
        badge={groupCount}
        aria-pressed={Boolean(modeLabel) || armed}
        onClick={onToggle}
        data-testid="analysis-button"
      />
      <Drawer
        opened={opened}
        // The × closes the panel only; the mode (and with it every capability
        // marker) is the header button's business — see the note above.
        onClose={() => onOpenedChange(false)}
        position="right"
        size={panelWidth(shown)}
        // A layout may float or re-anchor the panel through this class.
        classNames={{ content: 'dc-analysis-panel', inner: 'dc-analysis-panel-inner' }}
        padding="md"
        // Above the floating map card, like the other dashboard drawers.
        zIndex={Z_LAYERS.overlay}
        // The four props that make it a dock rather than a modal. Without the
        // first, the dashboard would be dimmed and unclickable; without the
        // last, the mousedown that starts a lasso would close the panel —
        // which is the whole bug this replaces.
        withOverlay={false}
        trapFocus={false}
        lockScroll={false}
        closeOnClickOutside={false}
        shadow="xl"
        // Docked below the app header, so the header stays reachable — the
        // Analysis button in it is the way out of the mode.
        styles={{ inner: { top: dashboardHeaderHeight() } }}
        title={
          <Group gap="xs">
            <Icon icon="mdi:select-group" width={20} height={20} className="dc-ap-title-icon" />
            <Text fw={600} size="md" className="dc-ap-title">
              Analysis
            </Text>
            {groupCount > 0 && (
              <Badge size="sm" variant="light" color={groupingColor} className="dc-ap-title-count">
                {groupCount} group{groupCount === 1 ? '' : 's'}
              </Badge>
            )}
            {labels && (
              <SegmentedControl
                size="xs"
                value={shown}
                onChange={(v) => onTabChange?.(v as AnalysisTab)}
                data={[
                  { value: 'groups', label: 'Groups' },
                  { value: 'labels', label: 'Labels' },
                ]}
                data-testid="analysis-tabs"
              />
            )}
          </Group>
        }
        data-testid="analysis-panel"
      >
        {shown === 'labels' ? labels : children}
      </Drawer>
    </>
  );
};

export default GroupingHeaderControl;

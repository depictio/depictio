import React from 'react';
import { Badge, Button, Drawer, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  ANALYSIS_PANEL_TOGGLE_EVENT,
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

/** Capped in vw like the filter drawer, so a phone keeps a strip of dashboard
 *  in view. Below that cap the apps stop padding and the panel overlays. */
const PANEL_WIDTH = `min(${ANALYSIS_PANEL_WIDTH_PX}px, 92vw)`;

/** The panel's slide, which the content column's padding transition matches.
 *  Mantine's Drawer default. */
const PANEL_TRANSITION_MS = 250;

/** `header={{ height: 50 }}` in App.tsx and EditorApp.tsx. The panel starts
 *  below it so the header — including this button, the only way out of the
 *  mode — stays visible and clickable while the panel is docked. */
const DASHBOARD_HEADER_HEIGHT = 50;

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
}> = ({
  groupCount,
  colorBy,
  opened,
  onOpenedChange,
  armed,
  onToggle,
  pushesContent,
  children,
}) => {
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
      swingPx: ANALYSIS_PANEL_WIDTH_PX,
      durationMs: PANEL_TRANSITION_MS,
    });
  }, [opened, pushesContent]);
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
      <Tooltip
        label="Save selections as groups, color or split every figure, compare groups"
        withArrow
        openDelay={400}
      >
        <Button
          // `xs` + a 14px icon, matching Edit / Save / Settings beside it —
          // `compact-sm` set a larger font than its neighbours and made the
          // cluster look ragged.
          size="xs"
          color={groupingColor}
          // Filled while a Color-by mode is on OR analysis mode is armed:
          // the button doubles as the always-visible indicator that a
          // dashboard-wide override is repainting the figures, and as the
          // one control that turns the mode back off.
          variant={modeLabel || armed ? 'filled' : 'light'}
          leftSection={<Icon icon="mdi:select-group" width={14} height={14} />}
          rightSection={
            groupCount > 0 ? (
              <Badge size="xs" variant="white" circle>
                {groupCount}
              </Badge>
            ) : undefined
          }
          onClick={onToggle}
        >
          {modeLabel ? `Analysis: ${modeLabel}` : 'Analysis'}
        </Button>
      </Tooltip>
      <Drawer
        opened={opened}
        // The × closes the panel only; the mode (and with it every capability
        // marker) is the header button's business — see the note above.
        onClose={() => onOpenedChange(false)}
        position="right"
        size={PANEL_WIDTH}
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
        styles={{ inner: { top: DASHBOARD_HEADER_HEIGHT } }}
        title={
          <Group gap="xs">
            <Icon icon="mdi:select-group" width={20} height={20} />
            <Text fw={600} size="md">
              Analysis
            </Text>
            {groupCount > 0 && (
              <Badge size="sm" variant="light" color={groupingColor}>
                {groupCount} group{groupCount === 1 ? '' : 's'}
              </Badge>
            )}
          </Group>
        }
        data-testid="analysis-panel"
      >
        {children}
      </Drawer>
    </>
  );
};

export default GroupingHeaderControl;

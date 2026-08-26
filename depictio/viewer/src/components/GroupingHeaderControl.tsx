import React from 'react';
import { Badge, Button, Popover, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { GROUPING_COLOR } from 'depictio-react-core';
import type { ColorByState } from 'depictio-react-core';

/**
 * Header home of the Grouping panel (select & compare, issue #89).
 *
 * Grouping is dashboard-family state: groups and the Color-by mode are shared
 * across a multi-tab dashboard's tabs, and Color-by recolors every figure on
 * screen. A mode with dashboard-wide effect must stay visible even when the
 * (per-tab) filter panel is collapsed, so it lives in the header — next to the
 * other global controls — as a button that always shows whether the mode is
 * active, with the full panel in its popover.
 *
 * `opened` is controlled by the app, and analysis mode (`armed`) is tracked
 * separately from it on purpose. Mantine closes a Popover on mousedown outside
 * it — which is exactly the mousedown that starts a lasso on a figure. If the
 * mode followed the panel's open state, every capability marker would vanish
 * at the instant the user acted on one. So the panel dismisses normally while
 * the mode persists, and this button is the explicit way out of it.
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
  /** The SelectionGroupsPanel node, owned by the app (state is the app's). */
  children: React.ReactNode;
}> = ({ groupCount, colorBy, opened, onOpenedChange, armed, onToggle, children }) => {
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
    <Popover
      opened={opened}
      onChange={onOpenedChange}
      width={300}
      position="bottom-end"
      withArrow
      shadow="md"
    >
      <Popover.Target>
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
            color={GROUPING_COLOR}
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
      </Popover.Target>
      <Popover.Dropdown>{children}</Popover.Dropdown>
    </Popover>
  );
};

export default GroupingHeaderControl;

import React, { useState } from 'react';
import { Badge, Button, Popover, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
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
 */
const GroupingHeaderControl: React.FC<{
  groupCount: number;
  colorBy: ColorByState;
  /** The SelectionGroupsPanel node, owned by the app (state is the app's). */
  children: React.ReactNode;
}> = ({ groupCount, colorBy, children }) => {
  const [opened, setOpened] = useState(false);
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
      onChange={setOpened}
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
            size="compact-sm"
            // Filled while a Color-by mode is on: the button doubles as the
            // always-visible indicator that a dashboard-wide override is
            // repainting the figures.
            variant={modeLabel ? 'filled' : 'light'}
            leftSection={<Icon icon="mdi:select-group" width={16} height={16} />}
            rightSection={
              groupCount > 0 ? (
                <Badge size="xs" variant="white" circle>
                  {groupCount}
                </Badge>
              ) : undefined
            }
            onClick={() => setOpened((o) => !o)}
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

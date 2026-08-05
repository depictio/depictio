import React, { createContext, useState } from 'react';
import { ActionIcon, Group, Popover, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import DataGridBody, { type TierAnnotation } from '../data/DataGridBody';

/**
 * Bridges the per-renderer Settings + Show-data popovers into ComponentChrome's
 * `extraActions` slot — that way the ActionIcons sit in the same hover-revealed
 * row as metadata/fullscreen/download/reset and match their Mantine styling
 * (variant=light, size=sm), instead of floating in the panel header.
 *
 * Wiring:
 *  - ComponentRenderer's advanced_viz dispatch holds the React node state and
 *    renders an <AdvancedVizExtrasProvider> around the renderer.
 *  - AdvancedVizFrame, when given controls / dataRows, builds the two
 *    Popovers and calls `publish(jsx)`. ComponentRenderer threads the
 *    published JSX into `extraActions` so chrome renders them.
 *
 * The popovers themselves use Mantine's Floating-UI-backed Popover which
 * portals the dropdown to document.body — so even when the chrome action
 * row fades out on mouseleave (the action row is opacity-gated), an OPEN
 * dropdown stays visible. Closing requires a click outside (closeOnClickOutside).
 */

type Publisher = (jsx: React.ReactNode) => void;

export const AdvancedVizExtrasContext = createContext<Publisher | null>(null);

interface ProviderProps {
  children: React.ReactNode;
  /** Receives the latest JSX the framed renderer wants to publish. */
  onChange: (jsx: React.ReactNode) => void;
}

export const AdvancedVizExtrasProvider: React.FC<ProviderProps> = ({ children, onChange }) => (
  <AdvancedVizExtrasContext.Provider value={onChange}>{children}</AdvancedVizExtrasContext.Provider>
);

interface SettingsPopoverProps {
  controls: React.ReactNode;
}

export const AdvancedVizSettingsPopover: React.FC<SettingsPopoverProps> = ({ controls }) => {
  // Tooltip wraps Popover.Target's child via a sibling span — putting Tooltip
  // *inside* Popover.Target wraps the ActionIcon, which breaks Mantine's
  // ref-forwarding and produces a multi-click open bug (the click-outside
  // detector sees the cloned wrapper as "outside" and closes the popover on
  // the very mousedown that opened it). Native HTML `title` keeps a hover
  // label without an extra wrapper.
  //
  // closeOnClickOutside is disabled here because the controls inside the
  // dropdown include Mantine Selects whose own dropdown menus are portaled
  // to document.body — clicking those was firing the outer popover's
  // "click outside" detector and closing Settings before `onChange` could
  // commit (so users couldn't change the embedding compute method). The
  // popover can still be dismissed by clicking the settings icon again
  // (Mantine toggles on target click), pressing Escape, or via the
  // explicit close-X button in the dropdown header.
  //
  // Controlled `opened` state so the in-dropdown close-X can dismiss it;
  // also keeps Mantine's target-click toggle working.
  const [opened, setOpened] = useState(false);
  return (
    <Popover
      position="bottom-end"
      shadow="md"
      withArrow
      closeOnClickOutside={false}
      closeOnEscape
      opened={opened}
      onChange={setOpened}
    >
      <Popover.Target>
        <ActionIcon
          variant="light"
          color="teal"
          size="sm"
          aria-label="Viz settings"
          title="Viz settings"
          onClick={() => setOpened((v) => !v)}
        >
          <Icon icon="tabler:adjustments-horizontal" width={16} height={16} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown p="sm" style={{ maxWidth: 380 }}>
        <Stack gap="xs">
          <Group justify="space-between" wrap="nowrap" gap="xs">
            <Text size="xs" fw={600} c="dimmed">
              Viz controls
            </Text>
            <ActionIcon
              variant="subtle"
              size="xs"
              color="gray"
              aria-label="Close viz controls"
              title="Close"
              onClick={() => setOpened(false)}
            >
              <Icon icon="tabler:x" width={14} height={14} />
            </ActionIcon>
          </Group>
          {controls}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

export type { TierAnnotation } from '../data/DataGridBody';

interface DataPopoverProps {
  dataRows: Record<string, unknown[]>;
  dataColumns?: string[];
  tierAnnotation?: TierAnnotation;
}

// closeOnClickOutside disabled for the same reason as the Settings popover:
// AG Grid's column menu + filter operator dropdown ("contains", "equals",
// ...) is rendered in its own portal at document.body level. When users
// clicked those, the popover's outside-click detector saw them as outside
// and closed the table - the dropdown flashed for ~100ms before everything
// disappeared, and sorting / filtering became impossible. Dismiss via the
// close button in the table's header, the icon (toggle), or Escape.
export const AdvancedVizDataPopover: React.FC<DataPopoverProps> = ({
  dataRows,
  dataColumns,
  tierAnnotation,
}) => {
  // Controlled so the table's own close button can reach it; Mantine only
  // attaches its toggle to the target while uncontrolled, hence the onClick.
  const [opened, setOpened] = useState(false);

  // Hide the icon outright when there is nothing behind it. Unlike the map's
  // popover, whose data only arrives once opened, this one is handed its rows
  // up front - so an icon with no rows behind it is just a dead affordance.
  const cols = dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows);
  if (cols.length === 0) return null;

  return (
    <Popover
      position="bottom-end"
      shadow="md"
      withArrow
      closeOnClickOutside={false}
      closeOnEscape
      opened={opened}
      onChange={setOpened}
    >
      <Popover.Target>
        <ActionIcon
          variant="light"
          color="violet"
          size="sm"
          aria-label="Show underlying data"
          title="Show data"
          onClick={() => setOpened((v) => !v)}
        >
          <Icon icon="tabler:table" width={16} height={16} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown
        p="sm"
        style={{
          width: 'min(820px, 88vw)',
          // Cap the dropdown so it never extends past the viewport;
          // overflow:auto lets users scroll the whole popover when the grid
          // pushes content below the bottom of the screen.
          maxHeight: '85vh',
          overflow: 'auto',
        }}
      >
        <DataGridBody
          dataRows={dataRows}
          dataColumns={dataColumns}
          tierAnnotation={tierAnnotation}
          onClose={() => setOpened(false)}
        />
      </Popover.Dropdown>
    </Popover>
  );
};

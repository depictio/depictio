import React, { createContext, Suspense, lazy, useState } from 'react';
import { ActionIcon, Group, Popover, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

// Lazy, matching `MapDataButton`: AG Grid is ~250kB plus its own stylesheets,
// and this module is now also reached from the (otherwise grid-free) map path,
// where a static import would drag the whole vendor-aggrid chunk onto a
// dashboard that never opens a table. Mantine unmounts a closed dropdown, so it
// resolves on first open and never otherwise.
const DataGridBody = lazy(() => import('../data/DataGridBody'));
import type { TierAnnotation } from '../data/DataGridBody';
import type { LoadAllState } from '../chrome/LoadAllButton';

/**
 * Bridges the per-renderer Settings + Show-data popovers into ComponentChrome's
 * `extraActions` slot — that way the ActionIcons sit in the same hover-revealed
 * row as metadata/fullscreen/download/reset and match their Mantine styling:
 * size=sm, and the cluster's subtle-at-rest / filled-when-engaged pair, so a
 * popover that is open reads as open. Not floating in the panel header.
 *
 * Wiring:
 *  - AdvancedVizDispatch holds the published payload and renders an
 *    <AdvancedVizExtrasProvider> around the renderer.
 *  - AdvancedVizFrame, when given controls / dataRows, calls
 *    `publish(payload)` — the raw fields, not finished JSX, so the inspector
 *    can present the same content docked.
 *  - AdvancedVizDispatch builds the two Popovers from that payload and passes
 *    them to chrome's `extraActions` slot.
 *
 * The popovers themselves use Mantine's Floating-UI-backed Popover which
 * portals the dropdown to document.body — so even when the chrome action
 * row fades out on mouseleave (the action row is opacity-gated), an OPEN
 * dropdown stays visible. Closing requires a click outside (closeOnClickOutside).
 */

/**
 * What a framed renderer publishes about itself.
 *
 * Structured rather than pre-wrapped JSX: the dispatch builds the popovers out
 * of it, and the inspector builds docked tabs out of the same fields. Publishing
 * finished popovers, as this did originally, left the inspector nothing it could
 * re-present.
 */
export interface AdvancedVizExtrasPayload {
  /** Tier-2 settings JSX, rendered bare in a tab or inside the settings popover. */
  controls?: React.ReactNode;
  data?: {
    rows: Record<string, unknown[]>;
    columns?: string[];
    tierAnnotation?: TierAnnotation;
  };
  /** Reduced-sampling state, when the renderer can expand to the full view.
   *  Shaped as `LoadAllState` so the dispatch can hand it straight to
   *  `LoadAllButton`. */
  reduction?: LoadAllState;
}

type Publisher = (payload: AdvancedVizExtrasPayload | null) => void;

export const AdvancedVizExtrasContext = createContext<Publisher | null>(null);

interface ProviderProps {
  children: React.ReactNode;
  /** Receives the latest payload the framed renderer wants to publish. */
  onChange: Publisher;
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
          variant={opened ? 'filled' : 'subtle'}
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

/** The columns actually rendered, in order. Shared so the popover can decide
 *  whether to render an icon at all without duplicating the fallback rule. */
function resolveDataColumns(
  dataRows: Record<string, unknown[]>,
  dataColumns?: string[],
): string[] {
  return (dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows)) as string[];
}

/**
 * Popover wrapper around `DataGridBody` — the fallback surface whenever the
 * inspector is disabled, which docks the same grid in a tab instead.
 *
 * closeOnClickOutside is disabled because AG Grid's column menu and filter
 * operator dropdown ("contains", "equals", …) render in their own portal at
 * document.body level. When users clicked those, the outside-click detector saw
 * them as outside and closed the table: the dropdown flashed for ~100ms before
 * everything disappeared, and sorting / filtering became impossible. Dismiss via
 * the close button in the table's header, the icon (toggle), or Escape.
 */
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
  if (resolveDataColumns(dataRows, dataColumns).length === 0) return null;

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
          variant={opened ? 'filled' : 'subtle'}
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
        <Suspense fallback={null}>
          <DataGridBody
            dataRows={dataRows}
            dataColumns={dataColumns}
            tierAnnotation={tierAnnotation}
            onClose={() => setOpened(false)}
          />
        </Suspense>
      </Popover.Dropdown>
    </Popover>
  );
};

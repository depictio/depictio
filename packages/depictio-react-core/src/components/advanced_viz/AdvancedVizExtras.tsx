import React, { createContext, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Group,
  Popover,
  Stack,
  Text,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { Icon } from '@iconify/react';

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

// Row-count thresholds for the Show-data popover.
//   ≤ PAGINATION_THRESHOLD → single scrollable view (DOM virtualization handles it).
//   > PAGINATION_THRESHOLD → AG Grid paginates (default page size 100).
// The data endpoint /advanced_viz/data caps at 100k rows so we never need
// the SSRM (server-side row model) here — client-side virtualization
// comfortably handles 100k rows.
const PAGINATION_THRESHOLD = 1000;

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
  const [opened, setOpened] = useState(false);
  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      shadow="md"
      withArrow
      trapFocus
      closeOnClickOutside
    >
      <Popover.Target>
        <Tooltip label="Viz settings" position="left" withArrow>
          <ActionIcon
            variant="light"
            color="teal"
            size="sm"
            aria-label="Viz settings"
            onClick={() => setOpened((v) => !v)}
          >
            <Icon icon="tabler:adjustments-horizontal" width={16} height={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="sm" style={{ maxWidth: 380 }}>
        <Stack gap="xs">
          <Text size="xs" fw={600} c="dimmed">
            Viz controls
          </Text>
          {controls}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

interface DataPopoverProps {
  dataRows: Record<string, unknown[]>;
  dataColumns?: string[];
}

export const AdvancedVizDataPopover: React.FC<DataPopoverProps> = ({ dataRows, dataColumns }) => {
  const { colorScheme } = useMantineColorScheme();
  const [opened, setOpened] = useState(false);

  const cols = useMemo(
    () => (dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows)) as string[],
    [dataRows, dataColumns],
  );
  const total = cols.length > 0 ? dataRows[cols[0]]?.length ?? 0 : 0;

  // Column-oriented → row-oriented for AG Grid. Only flip when the popover
  // is opened so the work isn't done on every refresh of the chart upstream.
  const rowData = useMemo(() => {
    if (!opened || cols.length === 0) return [];
    const out: Record<string, unknown>[] = [];
    for (let i = 0; i < total; i++) {
      const row: Record<string, unknown> = {};
      for (const c of cols) row[c] = dataRows[c][i];
      out.push(row);
    }
    return out;
  }, [opened, cols, dataRows, total]);

  const colDefs = useMemo(
    () =>
      cols.map((c) => ({
        field: c,
        headerName: c,
        sortable: true,
        filter: true,
        resizable: true,
        // Polars columns can carry dots (e.g. ``sepal.length``); without a
        // valueGetter AG Grid treats the dot as a nested-path separator.
        valueGetter: (params: { data?: Record<string, unknown> }) => params.data?.[c],
      })),
    [cols],
  );

  if (cols.length === 0) return null;

  const isDark = colorScheme === 'dark';
  const paginated = total > PAGINATION_THRESHOLD;

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      shadow="md"
      withArrow
      closeOnClickOutside
    >
      <Popover.Target>
        <Tooltip label="Show data" position="left" withArrow>
          <ActionIcon
            variant="light"
            color="violet"
            size="sm"
            aria-label="Show underlying data"
            onClick={() => setOpened((v) => !v)}
          >
            <Icon icon="tabler:table" width={16} height={16} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown p="sm" style={{ width: 'min(820px, 88vw)' }}>
        <Stack gap="xs">
          <Group gap={6} justify="space-between">
            <Text size="xs" fw={600} c="dimmed">
              Underlying data
            </Text>
            <Badge size="xs" color="gray" variant="light">
              {total.toLocaleString()} rows · {cols.length} cols
              {paginated ? ' · paginated' : ''}
            </Badge>
          </Group>
          <div
            className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
            style={{ width: '100%', height: 340 }}
          >
            <AgGridReact
              rowData={rowData}
              columnDefs={colDefs}
              animateRows={false}
              rowBuffer={25}
              pagination={paginated}
              paginationPageSize={100}
              paginationPageSizeSelector={[50, 100, 250, 500]}
              defaultColDef={{ minWidth: 100, flex: 1, suppressHeaderMenuButton: false }}
            />
          </div>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

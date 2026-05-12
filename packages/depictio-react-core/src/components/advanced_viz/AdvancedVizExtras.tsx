import React, { createContext, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Group,
  Popover,
  ScrollArea,
  Stack,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
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

const DATA_PREVIEW_ROWS = 50;

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
  const [opened, setOpened] = useState(false);
  const cols = (dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows)) as string[];
  const total = cols.length > 0 ? dataRows[cols[0]]?.length ?? 0 : 0;
  const previewN = Math.min(total, DATA_PREVIEW_ROWS);
  if (cols.length === 0) return null;

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
      <Popover.Dropdown p="sm" style={{ width: 'min(720px, 80vw)' }}>
        <Stack gap="xs">
          <Group gap={6} justify="space-between">
            <Text size="xs" fw={600} c="dimmed">
              Underlying data
            </Text>
            <Badge size="xs" color="gray" variant="light">
              {total.toLocaleString()} rows
              {total > DATA_PREVIEW_ROWS ? ` · preview ${DATA_PREVIEW_ROWS}` : ''}
            </Badge>
          </Group>
          <ScrollArea h={300} type="auto" offsetScrollbars>
            <Table striped withTableBorder withColumnBorders fz="xs" stickyHeader>
              <Table.Thead>
                <Table.Tr>
                  {cols.map((c) => (
                    <Table.Th key={c}>{c}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {Array.from({ length: previewN }).map((_, rowIdx) => (
                  <Table.Tr key={rowIdx}>
                    {cols.map((c) => (
                      <Table.Td key={c}>{formatCell(dataRows[c][rowIdx])}</Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

function formatCell(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    if (Number.isInteger(v)) return String(v);
    const abs = Math.abs(v);
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return v.toExponential(3);
    return v.toFixed(4).replace(/\.?0+$/, '');
  }
  return String(v);
}

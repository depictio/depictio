import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  Popover,
  ScrollArea,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import ErrorBoundary from '../ErrorBoundary';

interface AdvancedVizFrameProps {
  /** Inner content (the viz itself). */
  children: React.ReactNode;
  /** Title rendered at the top of the bordered container. */
  title?: string;
  /** Optional sub-title shown below the title (dim, smaller). */
  subtitle?: string;
  /**
   * Tier-2 controls (sliders / dropdowns / toggles) for the viz. Rendered
   * inside a Popover triggered by a Settings ActionIcon in the panel's top-
   * right corner. Stays visible while open (not dependent on chrome hover).
   */
  controls?: React.ReactNode;
  /** Loading state for initial fetch. */
  loading?: boolean;
  /** Error to display in place of children. */
  error?: string | null;
  /** Empty-state message when data fetched but row_count === 0. */
  emptyMessage?: string;
  /**
   * Optional column-oriented row data; when supplied, a "Show data" ActionIcon
   * surfaces a Popover preview of the rows feeding the chart (first N rows in
   * a compact Mantine Table). Keeps the explore-the-data path one click away
   * without re-introducing the cumbersome bottom drawer.
   */
  dataRows?: Record<string, unknown[]>;
  /** Column ordering for the data popover; defaults to Object.keys(dataRows). */
  dataColumns?: string[];
}

const DATA_PREVIEW_ROWS = 50;

/**
 * Shared wrapper for advanced-viz renderers.
 *
 * Renders a bordered Mantine Paper with the viz title (+ optional subtitle)
 * at the top-left. Two ActionIcons sit at the top-right:
 *   - Settings (sliders icon) → opens a Popover with the per-viz controls.
 *   - Show data (eye icon)    → opens a Popover with a 50-row preview of
 *                               the rows feeding the chart.
 *
 * Chrome icons (metadata / fullscreen / download / reset) float over the
 * panel from ComponentChrome above; these two icons live in the panel
 * because their Popover content must stay visible while the user interacts
 * with it (the chrome icons fade out on mouseleave).
 */
const AdvancedVizFrame: React.FC<AdvancedVizFrameProps> = ({
  children,
  title,
  subtitle,
  controls,
  loading,
  error,
  emptyMessage,
  dataRows,
  dataColumns,
}) => {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);

  const tableInfo = useMemo(() => {
    if (!dataRows) return null;
    const cols = dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows);
    if (cols.length === 0) return null;
    const totalRows = dataRows[cols[0]]?.length ?? 0;
    return { cols, totalRows };
  }, [dataRows, dataColumns]);

  return (
    <ErrorBoundary>
      <Paper
        p="sm"
        withBorder
        radius="md"
        style={{
          flex: 1,
          minHeight: 0,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          borderWidth: 1.5,
        }}
      >
        <Group justify="space-between" align="flex-start" wrap="nowrap" mb={6}>
          {title || subtitle ? (
            <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
              {title ? (
                <Text fw={600} size="sm" lineClamp={1}>
                  {title}
                </Text>
              ) : null}
              {subtitle ? (
                <Text size="xs" c="dimmed" lineClamp={2}>
                  {subtitle}
                </Text>
              ) : null}
            </Stack>
          ) : (
            <div style={{ flex: 1 }} />
          )}
          <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
            {controls ? (
              <Popover
                opened={settingsOpen}
                onChange={setSettingsOpen}
                position="bottom-end"
                shadow="md"
                withArrow
                trapFocus
                closeOnClickOutside
              >
                <Popover.Target>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="md"
                    aria-label="Viz settings"
                    onClick={() => setSettingsOpen((v) => !v)}
                  >
                    <Icon icon="tabler:adjustments-horizontal" width={18} height={18} />
                  </ActionIcon>
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
            ) : null}
            {tableInfo ? (
              <Popover
                opened={dataOpen}
                onChange={setDataOpen}
                position="bottom-end"
                shadow="md"
                withArrow
                closeOnClickOutside
              >
                <Popover.Target>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    size="md"
                    aria-label="Show underlying data"
                    onClick={() => setDataOpen((v) => !v)}
                  >
                    <Icon icon="tabler:table" width={18} height={18} />
                  </ActionIcon>
                </Popover.Target>
                <Popover.Dropdown p="sm" style={{ width: 'min(700px, 80vw)' }}>
                  <Stack gap="xs">
                    <Group gap={6} justify="space-between">
                      <Text size="xs" fw={600} c="dimmed">
                        Underlying data
                      </Text>
                      <Badge size="xs" color="gray" variant="light">
                        {tableInfo.totalRows.toLocaleString()} rows
                        {tableInfo.totalRows > DATA_PREVIEW_ROWS
                          ? ` · preview ${DATA_PREVIEW_ROWS}`
                          : ''}
                      </Badge>
                    </Group>
                    <ScrollArea h={300} type="auto" offsetScrollbars>
                      <Table striped withTableBorder withColumnBorders fz="xs" stickyHeader>
                        <Table.Thead>
                          <Table.Tr>
                            {tableInfo.cols.map((c) => (
                              <Table.Th key={c}>{c}</Table.Th>
                            ))}
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {Array.from({
                            length: Math.min(tableInfo.totalRows, DATA_PREVIEW_ROWS),
                          }).map((_, rowIdx) => (
                            <Table.Tr key={rowIdx}>
                              {tableInfo.cols.map((c) => (
                                <Table.Td key={c}>{formatCell(dataRows![c][rowIdx])}</Table.Td>
                              ))}
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </ScrollArea>
                  </Stack>
                </Popover.Dropdown>
              </Popover>
            ) : null}
          </Group>
        </Group>
        <div style={{ flex: '1 1 auto', minHeight: 0, position: 'relative' }}>
          {loading ? (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Loader size="sm" />
            </div>
          ) : error ? (
            <Alert color="red" title="Failed to render" variant="light">
              <Text size="xs">{error}</Text>
            </Alert>
          ) : emptyMessage ? (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'var(--mantine-color-dimmed)',
                fontSize: '0.85rem',
              }}
            >
              {emptyMessage}
            </div>
          ) : (
            children
          )}
        </div>
      </Paper>
    </ErrorBoundary>
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

export default AdvancedVizFrame;

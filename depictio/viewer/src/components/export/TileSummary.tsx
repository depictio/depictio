import React, { useState } from 'react';
import {
  Box,
  Collapse,
  Group,
  Progress,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS } from 'depictio-react-core';

/** One tile of an export: what it is, and what the export makes of it. */
export interface TileItem {
  id: string;
  title: string;
  /** The tile's kind in plain words ("card · donut", "figure"). */
  kind?: string | null;
  /** A key of the `statuses` map the summary is given. */
  status: string;
  /** Why, in the reader's words: shown on hover. */
  note?: string | null;
}

/** The tiles of one tab (or one section), in the order they should read. */
export interface TileGroup {
  id: string;
  title: string;
  items: TileItem[];
}

/** How a status reads: a short label and a Mantine colour name. */
export interface TileStatus {
  label: string;
  color: string;
}

const dot = (color: string, size = 8): React.CSSProperties => ({
  width: size,
  height: size,
  borderRadius: '50%',
  flexShrink: 0,
  background: `var(--mantine-color-${color}-filled)`,
});

/**
 * What an export makes of each tile, grouped by tab: one line per tab with
 * its count and a bar of its statuses, unfolding to its tiles (#1480).
 *
 * Shared by the report and the dashboard-only export modals in place of
 * their tile tables: a reader scans the tabs, opens the one they care about,
 * and reads a tile's status and reason on hover (its dot carries the status,
 * the legend its counts). A single tab opens unfolded.
 */
const TileSummary: React.FC<{
  groups: TileGroup[];
  statuses: Record<string, TileStatus>;
  /** Status keys in the order the legend and bars show them. */
  order: string[];
  testId?: string;
  /** Each tile's test id is `<itemTestId>-<status>` when set. */
  itemTestId?: string;
}> = ({ groups, statuses, order, testId = 'tile-summary', itemTestId }) => {
  const shown = groups.filter((g) => g.items.length > 0);
  const [open, setOpen] = useState<Set<string>>(
    () => new Set(shown.length === 1 ? [shown[0].id] : []),
  );
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const totals = new Map<string, number>();
  for (const g of shown) {
    for (const item of g.items) totals.set(item.status, (totals.get(item.status) ?? 0) + 1);
  }
  const statusOf = (key: string): TileStatus => statuses[key] ?? { label: key, color: 'gray' };

  return (
    <Stack gap={6} data-testid={testId}>
      {/* Aligned on the chevrons of the tab rows below. */}
      <Group gap="md" pl={13} pr="xs">
        {order
          .filter((key) => (totals.get(key) ?? 0) > 0)
          .map((key) => (
            <Group key={key} gap={6} wrap="nowrap">
              <Box style={dot(statusOf(key).color)} />
              <Text size="xs" c="dimmed">
                {totals.get(key)} {statusOf(key).label}
              </Text>
            </Group>
          ))}
      </Group>
      <Stack gap={2}>
        {shown.map((g) => {
          const counts = order
            .map((key) => [key, g.items.filter((i) => i.status === key).length] as const)
            .filter(([, n]) => n > 0);
          const expanded = open.has(g.id);
          return (
            <Box key={g.id} data-testid={`${testId}-group`}>
              <UnstyledButton
                onClick={() => toggle(g.id)}
                w="100%"
                py={6}
                px="xs"
                style={{ borderRadius: 'var(--mantine-radius-sm)' }}
                aria-expanded={expanded}
              >
                <Group gap="sm" wrap="nowrap">
                  <Icon
                    icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
                    width={16}
                    style={{ flexShrink: 0 }}
                  />
                  <Text size="sm" fw={500} style={{ flex: 1 }} truncate>
                    {g.title}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                    {g.items.length} tile{g.items.length === 1 ? '' : 's'}
                  </Text>
                  <Progress.Root size={6} w={120} style={{ flexShrink: 0 }}>
                    {counts.map(([key, n]) => (
                      <Progress.Section
                        key={key}
                        value={(100 * n) / g.items.length}
                        color={statusOf(key).color}
                      />
                    ))}
                  </Progress.Root>
                </Group>
              </UnstyledButton>
              <Collapse in={expanded}>
                <Stack gap={2} pl={34} pr="xs" pb={6}>
                  {g.items.map((item) => (
                    <Tooltip
                      key={item.id}
                      label={`${statusOf(item.status).label}${item.note ? `: ${item.note}` : ''}`}
                      multiline
                      w={320}
                      position="top-start"
                      zIndex={Z_LAYERS.tooltip}
                    >
                      <Group
                        gap="xs"
                        wrap="nowrap"
                        py={2}
                        data-tile-status={item.status}
                        data-testid={itemTestId ? `${itemTestId}-${item.status}` : undefined}
                      >
                        <Box style={dot(statusOf(item.status).color, 7)} />
                        <Text size="xs" style={{ flex: 1 }} truncate>
                          {item.title}
                        </Text>
                        {item.kind && (
                          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                            {item.kind}
                          </Text>
                        )}
                      </Group>
                    </Tooltip>
                  ))}
                </Stack>
              </Collapse>
            </Box>
          );
        })}
      </Stack>
    </Stack>
  );
};

export default TileSummary;

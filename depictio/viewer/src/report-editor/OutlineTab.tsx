import React from 'react';
import { ActionIcon, Badge, Card, Group, SegmentedControl, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { InteractiveFilter, ReportLayer, ReportTabPlacement } from 'depictio-react-core';

import { moveTile, patchTile, setTabPlacement } from './model';
import type { TabView } from './model';
import TileRow from './TileRow';

interface OutlineTabProps {
  tab: TabView;
  /** Position among the report's tabs: 0 is the main tab, fixed in place. */
  index: number;
  count: number;
  filters: InteractiveFilter[];
  onEdit: (change: (layer: ReportLayer) => ReportLayer) => void;
  onMoveTab: (direction: -1 | 1) => void;
}

/** One tab of the report: where it goes, and its components in order. */
const OutlineTab: React.FC<OutlineTabProps> = ({ tab, index, count, filters, onEdit, onMoveTab }) => {
  let lastSection: string | null | undefined;

  return (
    <Card withBorder radius="md" p="md" data-testid="report-outline-tab" data-tab-id={tab.tabId}>
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <Group gap={2} wrap="nowrap">
              <Tooltip label={tab.isMain ? 'The main tab stays first' : 'Move the tab up'}>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  disabled={tab.isMain || index <= 1}
                  onClick={() => onMoveTab(-1)}
                  aria-label="Move tab up"
                >
                  <Icon icon="mdi:chevron-up" width={18} />
                </ActionIcon>
              </Tooltip>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                disabled={tab.isMain || index >= count - 1}
                onClick={() => onMoveTab(1)}
                aria-label="Move tab down"
              >
                <Icon icon="mdi:chevron-down" width={18} />
              </ActionIcon>
            </Group>
            <Text fw={600} truncate>
              {tab.title}
            </Text>
            <Badge variant="light" color="gray" size="sm">
              {tab.tiles.filter((t) => t.inReport).length} of {tab.tiles.length} in the report
            </Badge>
          </Group>
          <SegmentedControl
            size="xs"
            value={tab.placement}
            disabled={tab.isMain}
            onChange={(v) =>
              onEdit((l) => setTabPlacement(l, tab.tabId, v as ReportTabPlacement, index))
            }
            data={[
              { label: 'Body', value: 'body' },
              { label: 'Appendix', value: 'appendix' },
            ]}
          />
        </Group>

        {tab.tiles.length === 0 && (
          <Text size="sm" c="dimmed">
            This tab has no components.
          </Text>
        )}

        {tab.tiles.map((view, i) => {
          const heading = view.section !== lastSection ? view.section : undefined;
          lastSection = view.section;
          return (
            <React.Fragment key={view.componentId}>
              {heading && (
                <Text fw={600} size="sm" c="dimmed" pt={i === 0 ? 0 : 'xs'} data-testid="report-section-heading">
                  {heading}
                </Text>
              )}
              <TileRow
                view={view}
                sections={tab.sections}
                filters={filters}
                canMoveUp={i > 0}
                canMoveDown={i < tab.tiles.length - 1}
                onPatch={(patch) => onEdit((l) => patchTile(l, view.entry, patch))}
                onMove={(dir) => onEdit((l) => moveTile(l, tab, i, i + dir))}
              />
            </React.Fragment>
          );
        })}
      </Stack>
    </Card>
  );
};

export default OutlineTab;

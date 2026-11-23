import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Checkbox,
  Collapse,
  Group,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { componentTypeVisual } from 'depictio-react-core';
import type { InteractiveFilter, ReportOrientation, ReportTile } from 'depictio-react-core';

import type { TileView } from './model';
import TileLive, { LIVE_TYPES } from './TileLive';

const OWN_SECTION = '__own__';

const ORIENTATIONS: { value: ReportOrientation; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'portrait', label: 'Portrait' },
  { value: 'landscape', label: 'Landscape' },
];

interface TileRowProps {
  view: TileView;
  /** Section titles of the tile's tab, for "Move to section". */
  sections: string[];
  filters: InteractiveFilter[];
  canMoveUp: boolean;
  canMoveDown: boolean;
  onPatch: (patch: Partial<ReportTile>) => void;
  onMove: (direction: -1 | 1) => void;
}

/** One component of the report: its place, its caption and, on demand, a live
 *  view of the tile itself. */
const TileRow: React.FC<TileRowProps> = ({
  view,
  sections,
  filters,
  canMoveUp,
  canMoveDown,
  onPatch,
  onMove,
}) => {
  const [showLive, setShowLive] = useState(false);
  const { entry } = view;
  const type = entry.component_type ?? '';
  const live = LIVE_TYPES.has(type);
  const typeLabel = type ? componentTypeVisual(type).label : 'Component';
  const excluded = !view.inReport;
  // A moved tile may name a section the tab no longer lists.
  const sectionData = [
    { value: OWN_SECTION, label: 'Its own section' },
    ...sections.map((s) => ({ value: s, label: s })),
    ...(view.sectionOverride && !sections.includes(view.sectionOverride)
      ? [{ value: view.sectionOverride, label: view.sectionOverride }]
      : []),
  ];

  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      data-testid="report-tile-row"
      data-component-id={view.componentId}
      style={{ opacity: excluded ? 0.6 : 1 }}
    >
      <Stack gap="xs">
        <Group gap="xs" wrap="nowrap" justify="space-between">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <Group gap={2} wrap="nowrap">
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                disabled={!canMoveUp}
                onClick={() => onMove(-1)}
                aria-label="Move up"
              >
                <Icon icon="mdi:chevron-up" width={18} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                disabled={!canMoveDown}
                onClick={() => onMove(1)}
                aria-label="Move down"
              >
                <Icon icon="mdi:chevron-down" width={18} />
              </ActionIcon>
            </Group>
            <Text fw={500} size="sm" truncate>
              {entry.title}
            </Text>
            <Badge variant="light" color="gray" size="sm">
              {typeLabel}
            </Badge>
            {excluded && (
              <Badge variant="outline" color="gray" size="sm">
                Not in the report
              </Badge>
            )}
          </Group>
          <Tooltip
            label={live ? (showLive ? 'Hide the live tile' : 'Show the live tile') : 'No live view for this type'}
          >
            <ActionIcon
              variant={showLive ? 'light' : 'subtle'}
              color="gray"
              disabled={!live || excluded}
              onClick={() => setShowLive((v) => !v)}
              aria-label="Toggle live tile"
            >
              <Icon icon={showLive ? 'mdi:eye-off-outline' : 'mdi:eye-outline'} width={18} />
            </ActionIcon>
          </Tooltip>
        </Group>

        <Group gap="md" align="flex-end">
          <Switch
            label="In report"
            checked={view.inReport}
            onChange={(e) => {
              const on = e.currentTarget.checked;
              // Out of the report is out of the PDF too.
              onPatch(on ? { in_report: true } : { in_report: false, in_pdf: false });
            }}
          />
          <Switch
            label="In PDF"
            checked={view.inReport && view.inPdf}
            disabled={!view.inReport}
            onChange={(e) => onPatch({ in_pdf: e.currentTarget.checked })}
          />
          <Select
            label="Orientation"
            size="xs"
            w={130}
            allowDeselect={false}
            data={ORIENTATIONS}
            value={view.orientation}
            onChange={(v) => v && onPatch({ orientation: v as ReportOrientation })}
          />
          <Checkbox
            label="Page break before"
            checked={view.pageBreakBefore}
            onChange={(e) => onPatch({ page_break_before: e.currentTarget.checked })}
            pb={4}
          />
        </Group>

        <Group grow align="flex-start">
          <TextInput
            label="Caption"
            size="xs"
            value={view.caption}
            placeholder={entry.caption ?? 'The tile keeps its own caption'}
            onChange={(e) => onPatch({ caption: e.currentTarget.value || null })}
          />
          <Select
            label="Move to section"
            size="xs"
            allowDeselect={false}
            data={sectionData}
            value={view.sectionOverride || OWN_SECTION}
            onChange={(v) => onPatch({ section: !v || v === OWN_SECTION ? null : v })}
          />
        </Group>

        <Collapse in={showLive && live && !excluded}>
          <Box pt="xs">{showLive && live && !excluded && (
            <TileLive tabId={view.tabId} componentId={view.componentId} filters={filters} />
          )}</Box>
        </Collapse>
      </Stack>
    </Paper>
  );
};

export default TileRow;

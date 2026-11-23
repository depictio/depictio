import React from 'react';
import { Button, Group, Paper, SegmentedControl, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { ReportOrientation, ReportTile } from 'depictio-react-core';

import type { TileView } from './model';

const OWN_SECTION = '__own__';

const ORIENTATIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'portrait', label: 'Portrait' },
  { value: 'landscape', label: 'Landscape' },
];

interface TileInspectorProps {
  view: TileView;
  /** Section titles of the tile's tab. */
  sections: string[];
  canMoveUp: boolean;
  canMoveDown: boolean;
  onPatch: (patch: Partial<ReportTile>) => void;
  onMove: (direction: -1 | 1) => void;
}

/** The settings of the selected tile: its caption and how it sits in the PDF. */
const TileInspector: React.FC<TileInspectorProps> = ({
  view,
  sections,
  canMoveUp,
  canMoveDown,
  onPatch,
  onMove,
}) => {
  const { entry } = view;
  // A moved tile may name a section the tab no longer lists.
  const sectionData = [
    { value: OWN_SECTION, label: 'Where it is in the dashboard' },
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
      ml="md"
      data-testid="report-inspector"
      data-component-id={view.componentId}
    >
      <Stack gap="sm">
        <TextInput
          label="Caption"
          size="xs"
          value={view.caption}
          placeholder={entry.caption ?? 'The tile keeps its own caption'}
          onChange={(e) => onPatch({ caption: e.currentTarget.value || null })}
        />
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Switch
            label="Include in PDF"
            description="Off keeps it in the HTML report only"
            checked={view.inReport && view.inPdf}
            disabled={!view.inReport}
            onChange={(e) => onPatch({ in_pdf: e.currentTarget.checked })}
          />
          <Switch
            label="Page break before"
            description="Starts a new PDF page"
            checked={view.pageBreakBefore}
            onChange={(e) => onPatch({ page_break_before: e.currentTarget.checked })}
          />
        </Group>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            PDF page orientation
          </Text>
          <SegmentedControl
            size="xs"
            fullWidth
            data={ORIENTATIONS}
            value={view.orientation}
            onChange={(v) => onPatch({ orientation: v as ReportOrientation })}
          />
        </Stack>
        <Select
          label="Section"
          size="xs"
          allowDeselect={false}
          data={sectionData}
          value={view.sectionOverride || OWN_SECTION}
          onChange={(v) => onPatch({ section: !v || v === OWN_SECTION ? null : v })}
        />
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<Icon icon="mdi:arrow-up" width={14} />}
            disabled={!canMoveUp}
            onClick={() => onMove(-1)}
          >
            Move up
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<Icon icon="mdi:arrow-down" width={14} />}
            disabled={!canMoveDown}
            onClick={() => onMove(1)}
          >
            Move down
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
};

export default TileInspector;

import React from 'react';
import { Box, Button, Group, SegmentedControl, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { ArrowDown, ArrowUp, SlidersHorizontal } from 'lucide-react';
import type { ReportOrientation, ReportTile } from 'depictio-react-core';

import { STROKE } from '../chrome/variants/glass/icons';
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
  /** The report's settings put every tile across the page. */
  widthLocked?: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onPatch: (patch: Partial<ReportTile>) => void;
  onMove: (direction: -1 | 1) => void;
}

/** A tile's width: its dashboard row, or the whole page. */
const WIDTHS = [
  { value: 'row', label: 'As in the dashboard' },
  { value: 'full', label: 'Full width' },
];

/** The settings of the selected tile: its caption and how it sits in the PDF. */
const TileInspector: React.FC<TileInspectorProps> = ({
  view,
  sections,
  widthLocked = false,
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
    <Box
      className="re-inspector"
      data-testid="report-inspector"
      data-component-id={view.componentId}
    >
      <div className="re-inspector-head">
        <SlidersHorizontal size={14} strokeWidth={STROKE} aria-hidden />
        Tile settings
      </div>
      <Stack gap="sm">
        <TextInput
          label="Caption"
          size="xs"
          value={view.caption}
          placeholder={entry.caption ?? 'The tile keeps its own caption'}
          onChange={(e) => onPatch({ caption: e.currentTarget.value || null })}
        />
        {entry.component_type !== 'card' ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Width in the report
            </Text>
            <SegmentedControl
              size="xs"
              fullWidth
              data={WIDTHS}
              value={widthLocked || view.fullWidth ? 'full' : 'row'}
              disabled={widthLocked}
              onChange={(v) => onPatch({ full_width: v === 'full' })}
              data-testid="report-tile-width"
            />
            <Text size="xs" c="dimmed">
              {widthLocked
                ? 'Every tile is full width (Report settings).'
                : view.fullWidth
                ? 'Takes the whole page width; the rest of its dashboard row keeps sharing it.'
                : 'Shares its row with the tiles beside it in the dashboard.'}
            </Text>
          </Stack>
        ) : null}
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
          // In the settings popover: a list portalled out of it would count
          // as a click outside and close it.
          comboboxProps={{ withinPortal: false }}
        />
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<ArrowUp size={14} strokeWidth={STROKE} />}
            disabled={!canMoveUp}
            onClick={() => onMove(-1)}
          >
            Move up
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            leftSection={<ArrowDown size={14} strokeWidth={STROKE} />}
            disabled={!canMoveDown}
            onClick={() => onMove(1)}
          >
            Move down
          </Button>
        </Group>
      </Stack>
    </Box>
  );
};

export default TileInspector;

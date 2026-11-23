import React from 'react';
import { Badge, Box, Checkbox, Group, Paper, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { TileView } from './model';
import TileThumbnail from './TileThumbnail';
import { typeVisual } from './visuals';

export type DropPosition = 'before' | 'after';

interface TileCardProps {
  view: TileView;
  selected: boolean;
  /** The frame's thumbnail of the tile, a data URL, once it has sent one. */
  thumbnail: string | undefined;
  dragging: boolean;
  /** Where a dragged tile would land relative to this card. */
  dropIndicator: DropPosition | null;
  onSelect: () => void;
  onToggleInReport: (on: boolean) => void;
  onDragStart: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent, position: DropPosition) => void;
  onDrop: (event: React.DragEvent) => void;
  onDragEnd: () => void;
}

/** What differs from the defaults, in a word each. */
function summaryBadges(view: TileView): string[] {
  const out: string[] = [];
  if (view.inReport && !view.inPdf) out.push('HTML only');
  if (view.orientation === 'landscape') out.push('Landscape');
  if (view.orientation === 'portrait') out.push('Portrait');
  if (view.pageBreakBefore) out.push('Page break');
  if (view.caption) out.push('Own caption');
  return out;
}

/** One component in the structure: a compact card with its thumbnail. */
const TileCard: React.FC<TileCardProps> = ({
  view,
  selected,
  thumbnail,
  dragging,
  dropIndicator,
  onSelect,
  onToggleInReport,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}) => {
  const visual = typeVisual(view.entry.component_type);
  const badges = summaryBadges(view);
  const edge = '2px solid var(--mantine-primary-color-filled)';

  return (
    <Paper
      withBorder
      radius="md"
      p={6}
      draggable
      onClick={onSelect}
      onDragStart={onDragStart}
      onDragOver={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        onDragOver(e, e.clientY < rect.top + rect.height / 2 ? 'before' : 'after');
      }}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      data-testid={`report-tile-${view.tabId}:${view.componentId}`}
      data-tile-key={`${view.tabId}:${view.componentId}`}
      data-selected={selected || undefined}
      style={{
        cursor: 'pointer',
        opacity: dragging ? 0.4 : view.inReport ? 1 : 0.55,
        borderColor: selected ? 'var(--mantine-primary-color-filled)' : undefined,
        boxShadow: selected ? '0 0 0 1px var(--mantine-primary-color-filled)' : undefined,
        borderTop: dropIndicator === 'before' ? edge : undefined,
        borderBottom: dropIndicator === 'after' ? edge : undefined,
      }}
    >
      <Group gap="xs" wrap="nowrap">
        <Box c="dimmed" style={{ cursor: 'grab', display: 'flex' }} aria-label="Drag to reorder">
          <Icon icon="mdi:drag-vertical" width={18} />
        </Box>
        <Checkbox
          size="xs"
          checked={view.inReport}
          onChange={(e) => onToggleInReport(e.currentTarget.checked)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Include ${view.entry.title} in the report`}
          data-testid="report-include-toggle"
        />
        <TileThumbnail
          tileKey={`${view.tabId}:${view.componentId}`}
          title={view.entry.title}
          componentType={view.entry.component_type}
          png={thumbnail}
        />
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Group gap={6} wrap="nowrap">
            <Icon icon={visual.icon} width={14} color={visual.color} style={{ flex: 'none' }} />
            <Text size="sm" fw={500} truncate>
              {view.entry.title}
            </Text>
          </Group>
          <Group gap={4} mt={2}>
            <Text size="xs" c="dimmed">
              {visual.label}
            </Text>
            {!view.inReport && (
              <Badge size="xs" variant="outline" color="gray">
                Not in the report
              </Badge>
            )}
            {badges.map((b) => (
              <Badge key={b} size="xs" variant="light" color="gray">
                {b}
              </Badge>
            ))}
          </Group>
        </Box>
      </Group>
    </Paper>
  );
};

export default TileCard;

import React from 'react';
import { ActionIcon, Badge, Box, Checkbox, Group, Paper, Popover, Text, Tooltip, UnstyledButton } from '@mantine/core';
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
  /** The tile's settings, shown in a popover from the card's footer. */
  settings: React.ReactNode;
  settingsOpen: boolean;
  onSettingsChange: (open: boolean) => void;
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
  if (view.fullWidth) out.push('Full width');
  if (view.caption) out.push('Own caption');
  return out;
}

/** One component in the structure: its render on top (a KPI card takes half a
 *  row, anything else a whole one), a slim footer under it. */
const TileCard: React.FC<TileCardProps> = ({
  view,
  selected,
  thumbnail,
  dragging,
  dropIndicator,
  onSelect,
  settings,
  settingsOpen,
  onSettingsChange,
  onToggleInReport,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}) => {
  const visual = typeVisual(view.entry.component_type);
  const badges = summaryBadges(view);
  const edge = '2px solid var(--mantine-primary-color-filled)';
  // Side by side, a card is before or after its neighbour by the pointer's x.
  const half = view.entry.component_type === 'card';
  const key = `${view.tabId}:${view.componentId}`;

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
        const before = half
          ? e.clientX < rect.left + rect.width / 2
          : e.clientY < rect.top + rect.height / 2;
        onDragOver(e, before ? 'before' : 'after');
      }}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      className={half ? 'rpt-tile rpt-tile--half' : 'rpt-tile'}
      data-testid={`report-tile-${key}`}
      data-tile-key={key}
      data-selected={selected || undefined}
      style={{
        cursor: 'pointer',
        opacity: dragging ? 0.4 : view.inReport ? 1 : 0.55,
        borderColor: selected ? 'var(--mantine-primary-color-filled)' : undefined,
        boxShadow: selected ? '0 0 0 1px var(--mantine-primary-color-filled)' : undefined,
        borderTop: dropIndicator === 'before' ? edge : undefined,
        borderBottom: dropIndicator === 'after' ? edge : undefined,
        borderLeft: half && dropIndicator === 'before' ? edge : undefined,
        borderRight: half && dropIndicator === 'after' ? edge : undefined,
      }}
    >
      <TileThumbnail
        tileKey={key}
        tabId={view.tabId}
        componentId={view.componentId}
        title={view.entry.title}
        componentType={view.entry.component_type}
        png={thumbnail}
      />
      <Group gap={6} wrap="nowrap" mt={6} style={{ overflow: 'hidden' }}>
        <Box c="dimmed" style={{ cursor: 'grab', display: 'flex', flex: 'none' }} aria-label="Drag to reorder">
          <Icon icon="mdi:drag-vertical" width={16} />
        </Box>
        <Checkbox
          size="xs"
          checked={view.inReport}
          onChange={(e) => onToggleInReport(e.currentTarget.checked)}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Include ${view.entry.title} in the report`}
          data-testid="report-include-toggle"
        />
        <Icon icon={visual.icon} width={14} color={visual.color} style={{ flex: 'none' }} />
        {/* The title opens the tile's settings too: the keyboard way to them
            (the card's own click selects it, the thumbnail's keys enlarge it). */}
        <UnstyledButton
          onClick={(e) => {
            e.stopPropagation();
            onSettingsChange(!settingsOpen);
          }}
          aria-label={`Settings for ${view.entry.title}`}
          style={{ flex: 1, minWidth: 0, display: 'flex' }}
        >
          <Text size="xs" fw={500} truncate title={view.entry.title}>
            {view.entry.title}
          </Text>
        </UnstyledButton>
        {!view.inReport && (
          <Badge size="xs" variant="outline" color="gray" style={{ flex: 'none' }}>
            Not in the report
          </Badge>
        )}
        {badges.map((b) => (
          <Badge key={b} size="xs" variant="light" color="gray" style={{ flex: 'none' }}>
            {b}
          </Badge>
        ))}
        <Popover
          opened={settingsOpen}
          onChange={onSettingsChange}
          position="bottom-end"
          width={380}
          shadow="md"
          withArrow
          trapFocus
          // Inside the editor's root, whose variables the settings are drawn with.
          portalProps={{ target: '.re-root' }}
        >
          <Popover.Target>
            <Tooltip label="Tile settings" withArrow openDelay={300} disabled={settingsOpen}>
              <ActionIcon
                size="sm"
                variant={settingsOpen ? 'light' : 'subtle'}
                color="gray"
                style={{ flex: 'none' }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSettingsChange(!settingsOpen);
                }}
                aria-label={`Settings for ${view.entry.title}`}
                aria-expanded={settingsOpen}
                data-testid="report-tile-settings"
              >
                <Icon icon="mdi:tune-variant" width={15} />
              </ActionIcon>
            </Tooltip>
          </Popover.Target>
          <Popover.Dropdown onClick={(e) => e.stopPropagation()}>{settings}</Popover.Dropdown>
        </Popover>
      </Group>
    </Paper>
  );
};

export default TileCard;

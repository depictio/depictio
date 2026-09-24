import React from 'react';
import { ActionIcon, Button, Group, Paper, Popover, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type {
  AnnotationDraft,
  PendingAnnotation,
  PendingDraftPatch,
} from '../../annotations/AnnotationLayerContext';
import { ANNOTATE_UI_ATTR } from '../../annotations/escape';
import { annotateHint, NAVIGATING_HINT, SURFACE_TOOLS } from '../../annotations/layer';
import type { AnnotationStats } from '../../annotations/summary';
import type { AnnotateOptions, AnnotateSurface, AnnotateTool } from '../../annotations/layer';
import { Z_LAYERS } from '../../zLayers';
import AnnotationForm from './AnnotationForm';

export interface AnnotateToolbarProps {
  tool: AnnotateTool;
  options: AnnotateOptions;
  /** `map`: only the tools a map can take (marked points, notes). Default `cartesian`. */
  surface?: AnnotateSurface;
  onChange: (tool: AnnotateTool, options: AnnotateOptions) => void;
  onDone: () => void;
  /** The capture waiting for a label on this component, if any. */
  pending: PendingAnnotation | null;
  onSave: (draft: AnnotationDraft) => Promise<void>;
  onCancel: () => void;
  /** Live form state, drawn as a preview of the pending shape. */
  onDraftChange?: (patch: PendingDraftPatch) => void;
  /** Counts measured on the data for the pending shape, shown in the form. */
  pendingStats?: AnnotationStats;
  /**
   * The modebar's zoom or pan took over the drag gesture: no tool is shown
   * active until one is picked again.
   */
  navigating?: boolean;
  /**
   * `figure` (default): the Plotly drawing tools. `rows`: a table, where the
   * only tool is marking the selected rows (a "points" annotation keyed on the
   * row-id column) with a "Mark N rows" button.
   */
  variant?: 'figure' | 'rows';
  /** `rows` variant: how many rows are selected in the grid. */
  selectedCount?: number;
  /** `rows` variant: capture the selected rows. */
  onMarkRows?: () => void;
}

interface ToolButton {
  key: string;
  tool: AnnotateTool;
  label: string;
  icon: string;
  active: boolean;
  select: () => void;
}

/**
 * Floating tool palette shown on a figure in annotate mode, plus the popover
 * that asks for the label of the shape just drawn. Anchored to the palette so
 * it stays inside the card, whatever gesture produced the shape.
 */
const AnnotateToolbar: React.FC<AnnotateToolbarProps> = ({
  tool,
  options,
  surface = 'cartesian',
  onChange,
  onDone,
  pending,
  onSave,
  onCancel,
  onDraftChange,
  pendingStats,
  navigating = false,
  variant = 'figure',
  selectedCount = 0,
  onMarkRows,
}) => {
  const rowsMode = variant === 'rows';
  const allFigureTools: ToolButton[] = [
    {
      key: 'range-x',
      tool: 'range',
      label: 'Range on x',
      icon: 'mdi:arrow-expand-horizontal',
      active: tool === 'range' && options.rangeAxis === 'x',
      select: () => onChange('range', { ...options, rangeAxis: 'x' }),
    },
    {
      key: 'range-y',
      tool: 'range',
      label: 'Range on y',
      icon: 'mdi:arrow-expand-vertical',
      active: tool === 'range' && options.rangeAxis === 'y',
      select: () => onChange('range', { ...options, rangeAxis: 'y' }),
    },
    {
      key: 'line-x',
      tool: 'line',
      label: 'Vertical line (at an x value)',
      icon: 'mdi:border-vertical',
      active: tool === 'line' && options.lineAxis === 'x',
      select: () => onChange('line', { ...options, lineAxis: 'x' }),
    },
    {
      key: 'line-y',
      tool: 'line',
      label: 'Horizontal line (at a y value)',
      icon: 'mdi:border-horizontal',
      active: tool === 'line' && options.lineAxis === 'y',
      select: () => onChange('line', { ...options, lineAxis: 'y' }),
    },
    {
      key: 'points-lasso',
      tool: 'points',
      label: 'Mark points (lasso)',
      icon: 'mdi:lasso',
      active: tool === 'points' && options.selectMode === 'lasso',
      select: () => onChange('points', { ...options, selectMode: 'lasso' }),
    },
    {
      key: 'points-box',
      tool: 'points',
      label: 'Mark points (box)',
      icon: 'mdi:selection-drag',
      active: tool === 'points' && options.selectMode === 'select',
      select: () => onChange('points', { ...options, selectMode: 'select' }),
    },
    {
      key: 'note',
      tool: 'note',
      label: 'Note',
      icon: 'mdi:message-arrow-left-outline',
      active: tool === 'note',
      select: () => onChange('note', options),
    },
  ];
  const figureTools = allFigureTools.filter((t) => SURFACE_TOOLS[surface].includes(t.tool));
  const tools: ToolButton[] = rowsMode
    ? [
        {
          key: 'rows',
          tool: 'points',
          label: 'Mark rows',
          icon: 'mdi:table-row',
          active: true,
          select: () => undefined,
        },
      ]
    : navigating
      ? figureTools.map((t) => ({ ...t, active: false }))
      : figureTools;
  const hint = rowsMode
    ? selectedCount > 0
      ? `${selectedCount} row${selectedCount === 1 ? '' : 's'} selected`
      : 'Click rows to select them, then mark them'
    : navigating
      ? NAVIGATING_HINT
      : annotateHint(tool, options, surface);

  // Rendered in the fullscreen element when there is one: a portal to <body>
  // would be invisible behind a fullscreen card.
  const portalTarget =
    typeof document !== 'undefined' && document.fullscreenElement
      ? (document.fullscreenElement as HTMLElement)
      : undefined;

  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  return (
    <Popover
      opened={pending != null}
      onClose={onCancel}
      position={rowsMode ? 'bottom-end' : 'bottom-start'}
      width={300}
      shadow="md"
      withArrow
      trapFocus
      closeOnEscape={false}
      closeOnClickOutside={false}
      zIndex={Z_LAYERS.tooltip}
      portalProps={portalTarget ? { target: portalTarget } : undefined}
    >
      <Popover.Target>
        <Paper
          className="dgl-no-drag"
          shadow="sm"
          radius="md"
          p={4}
          withBorder
          data-testid="annotate-toolbar"
          {...{ [ANNOTATE_UI_ATTR]: '' }}
          onMouseDown={stop}
          onPointerDown={stop}
          onTouchStart={stop}
          // A table keeps its header checkbox and badge column (top-left)
          // reachable: the rows palette sits top-right instead.
          style={{ position: 'absolute', top: 4, ...(rowsMode ? { right: 4 } : { left: 4 }), zIndex: 2 }}
        >
          <Stack gap={2}>
            <Group gap={4} wrap="nowrap">
              <ActionIcon.Group>
                {tools.map((t) => (
                  <Tooltip key={t.key} label={t.label} withArrow openDelay={300}>
                    <ActionIcon
                      size="sm"
                      variant={t.active ? 'filled' : 'default'}
                      onClick={t.select}
                      aria-label={t.label}
                      aria-pressed={t.active}
                    >
                      <Icon icon={t.icon} width={14} />
                    </ActionIcon>
                  </Tooltip>
                ))}
              </ActionIcon.Group>
              {rowsMode && (
                <Button
                  size="compact-xs"
                  variant="filled"
                  disabled={selectedCount === 0 || pending != null}
                  onClick={onMarkRows}
                  data-testid="annotate-mark-rows"
                >
                  {selectedCount > 0
                    ? `Mark ${selectedCount} selected row${selectedCount === 1 ? '' : 's'}`
                    : 'Mark selected rows'}
                </Button>
              )}
              <Tooltip label="Done (Esc)" withArrow>
                <ActionIcon size="sm" variant="subtle" color="gray" onClick={onDone} aria-label="Leave annotate mode">
                  <Icon icon="mdi:check" width={14} />
                </ActionIcon>
              </Tooltip>
            </Group>
            <Text size="xs" c="dimmed" px={2}>
              {hint}
            </Text>
          </Stack>
        </Paper>
      </Popover.Target>
      <Popover.Dropdown onMouseDown={stop} onPointerDown={stop} {...{ [ANNOTATE_UI_ATTR]: '' }}>
        {pending && (
          <AnnotationForm
            pending={pending}
            onSave={onSave}
            onCancel={onCancel}
            onDraftChange={onDraftChange}
            stats={pendingStats}
          />
        )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default AnnotateToolbar;

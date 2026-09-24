import React from 'react';
import { ActionIcon, Button, Group, Paper, Popover, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { AnnotationDraft, PendingAnnotation } from '../../annotations/AnnotationLayerContext';
import { ANNOTATE_UI_ATTR } from '../../annotations/escape';
import { annotateHint } from '../../annotations/layer';
import type { AnnotateOptions, AnnotateTool } from '../../annotations/layer';
import { Z_LAYERS } from '../../zLayers';
import AnnotationForm from './AnnotationForm';

export interface AnnotateToolbarProps {
  tool: AnnotateTool;
  options: AnnotateOptions;
  onChange: (tool: AnnotateTool, options: AnnotateOptions) => void;
  onDone: () => void;
  /** The capture waiting for a label on this component, if any. */
  pending: PendingAnnotation | null;
  onSave: (draft: AnnotationDraft) => Promise<void>;
  onCancel: () => void;
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
  onChange,
  onDone,
  pending,
  onSave,
  onCancel,
  variant = 'figure',
  selectedCount = 0,
  onMarkRows,
}) => {
  const rowsMode = variant === 'rows';
  const figureTools: ToolButton[] = [
    {
      key: 'range-x',
      label: 'Range on x',
      icon: 'mdi:arrow-expand-horizontal',
      active: tool === 'range' && options.rangeAxis === 'x',
      select: () => onChange('range', { ...options, rangeAxis: 'x' }),
    },
    {
      key: 'range-y',
      label: 'Range on y',
      icon: 'mdi:arrow-expand-vertical',
      active: tool === 'range' && options.rangeAxis === 'y',
      select: () => onChange('range', { ...options, rangeAxis: 'y' }),
    },
    {
      key: 'line',
      label: 'Reference line',
      icon: 'mdi:vector-line',
      active: tool === 'line',
      select: () => onChange('line', options),
    },
    {
      key: 'points',
      label: 'Mark points',
      icon: 'mdi:selection-ellipse',
      active: tool === 'points',
      select: () => onChange('points', options),
    },
    {
      key: 'note',
      label: 'Note',
      icon: 'mdi:message-arrow-left-outline',
      active: tool === 'note',
      select: () => onChange('note', options),
    },
  ];
  const tools: ToolButton[] = rowsMode
    ? [
        {
          key: 'rows',
          label: 'Mark rows',
          icon: 'mdi:table-row',
          active: true,
          select: () => undefined,
        },
      ]
    : figureTools;
  const hint = rowsMode
    ? selectedCount > 0
      ? `${selectedCount} row${selectedCount === 1 ? '' : 's'} selected`
      : 'Click rows to select them, then mark them'
    : annotateHint(tool, options);

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
              {!rowsMode && tool === 'line' && (
                <Tooltip
                  label={options.lineAxis === 'x' ? 'Vertical line (at an x value)' : 'Horizontal line (at a y value)'}
                  withArrow
                >
                  <ActionIcon
                    size="sm"
                    variant="light"
                    onClick={() =>
                      onChange('line', { ...options, lineAxis: options.lineAxis === 'x' ? 'y' : 'x' })
                    }
                    aria-label="Switch line direction"
                  >
                    <Text size="xs" fw={700}>
                      {options.lineAxis}
                    </Text>
                  </ActionIcon>
                </Tooltip>
              )}
              {!rowsMode && tool === 'points' && (
                <Tooltip
                  label={options.selectMode === 'lasso' ? 'Lasso (switch to box)' : 'Box (switch to lasso)'}
                  withArrow
                >
                  <ActionIcon
                    size="sm"
                    variant="light"
                    onClick={() =>
                      onChange('points', {
                        ...options,
                        selectMode: options.selectMode === 'lasso' ? 'select' : 'lasso',
                      })
                    }
                    aria-label="Switch selection gesture"
                  >
                    <Icon
                      icon={options.selectMode === 'lasso' ? 'mdi:lasso' : 'mdi:selection-drag'}
                      width={14}
                    />
                  </ActionIcon>
                </Tooltip>
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
          />
        )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default AnnotateToolbar;

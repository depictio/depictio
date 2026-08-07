import React from 'react';
import {
  ActionIcon,
  Box,
  Collapse,
  Group,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import {
  activeFiltersFor,
  filterDisplayLabel,
  formatFilterValue,
} from '../../activeFilters';
import { INTERACTIVE_FRAME, interactiveAccent, interactiveIcon } from './frame';

/**
 * Icon for a selection row, by the component the selection was made on.
 *
 * A selection used to be drawn with one generic marquee glyph whatever it came
 * from, which named the gesture rather than the thing — a lasso over a map
 * looked exactly like a row picked out of a table. These are the icons each
 * component type already wears elsewhere (the map panel's control, the
 * builder's component list), so a row and its source are recognisably the same
 * thing. Every id here appears as a literal in viewer source, which is what
 * gets it into the bundled icon subset — see `generate-icon-subset.mjs`.
 */
const SELECTION_ICONS: Record<string, string> = {
  map: 'mdi:map-marker-multiple',
  table: 'mdi:table',
  figure: 'mdi:chart-scatter-plot',
  advanced_viz: 'mdi:chart-line',
};

/** Fallback for a selection whose source component can't be resolved. */
const SELECTION_ICON_FALLBACK = 'mdi:selection-drag';

interface ActiveFilterSummaryProps {
  filters: InteractiveFilter[];
  /** Full stored_metadata — chart/table selections resolve their label from
   *  their source component, which is not an interactive component. */
  components: StoredMetadata[];
  /** Emits `{ index, value: null, source }`, which mergeFiltersBySource
   *  interprets as "drop the entry for this (index, source) pair". */
  onClear: (filter: InteractiveFilter) => void;
  open: boolean;
  onToggle: () => void;
}

/**
 * Removable summary of everything currently narrowing the dashboard.
 *
 * Without this the only way to see which filters are on is to scroll the whole
 * panel, and the only way to undo one is to find its control. Selections made
 * on a chart, table or map appear here too, so the single "clear this one"
 * gesture works the same regardless of where a filter came from.
 *
 * A list, not a row of pills: the entries are a label and a value each, and
 * pills sized to their own content wrap into a ragged block that changes height
 * every time a filter moves. Two aligned columns stay the same shape whatever
 * is in them, which matters here because this sits above the controls and
 * pushes them down. It folds for the same reason — on a dashboard with a dozen
 * filters on, the summary must not be the whole panel.
 *
 * Each row wears its control's own icon and accent, so it is recognisably the
 * same filter as the one further down the panel. Colour here identifies a
 * component, which is what the accent already means everywhere else — it is not
 * a category code. An earlier version tinted panel filters and chart selections
 * two different hues, which invented a distinction the icons already carry and
 * put two palettes in a column that also has section accents in it.
 */
const ActiveFilterSummary: React.FC<ActiveFilterSummaryProps> = ({
  filters,
  components,
  onClear,
  open,
  onToggle,
}) => {
  const active = activeFiltersFor(filters);
  if (active.length === 0) return null;

  return (
    <Box mt={6}>
      <UnstyledButton onClick={onToggle} aria-expanded={open} style={{ width: '100%' }}>
        <Group gap={4} wrap="nowrap" justify="space-between">
          <Text size="xs" c="dimmed">
            {active.length === 1 ? '1 filter active' : `${active.length} filters active`}
          </Text>
          <Icon
            icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'}
            width={14}
            height={14}
            style={{ flexShrink: 0, color: 'var(--mantine-color-dimmed)' }}
          />
        </Group>
      </UnstyledButton>

      <Collapse in={open}>
        {/* Capped and scrolled rather than allowed to run: this sits above the
            controls, and a dashboard with a dozen filters on would otherwise
            push them off the panel entirely. Roughly seven rows, after which
            the summary stops growing and starts scrolling. */}
        <Stack gap={0} mt={2} mah={160} style={{ overflowY: 'auto' }}>
          {active.map((f) => {
            const label = filterDisplayLabel(f, components);
            const value = formatFilterValue(f);
            const fromSelection = f.source !== undefined;
            const meta = components.find((c) => c.index === f.index);
            // Same icon and same accent as the control this row stands for, so
            // a row and its filter are recognisably one thing — `interactiveIcon`
            // and `interactiveAccent` are the accessors the control itself reads.
            // A selection has no control in the panel to match, so it takes the
            // icon of the component it was made on: where it came from is the
            // useful thing to show, and it is what tells you which map or table
            // to go back to in order to change it. It still takes that
            // component's accent.
            const icon =
              f.source === 'ai_prompt'
                ? 'material-symbols:auto-awesome-outline'
                : fromSelection
                  ? (meta && SELECTION_ICONS[meta.component_type || '']) || SELECTION_ICON_FALLBACK
                  : meta
                    ? interactiveIcon(meta)
                    : 'mdi:filter-variant';
            const accent = meta ? interactiveAccent(meta) : undefined;
            return (
              <Group
                key={`${f.index}:${f.source ?? ''}`}
                gap={6}
                wrap="nowrap"
                style={{ minWidth: 0 }}
              >
                {/* Wrapped in a span because Tooltip needs a ref-able child.
                    Every row carries an icon, never only some: the panel is a
                    narrow column, and an icon on one row and not the next is
                    what makes its labels start at two different x positions.
                    Same reasoning as `frame.tsx`, which is why the controls
                    below all have one too. */}
                <Tooltip
                  label={fromSelection ? `Selected on ${label}` : label}
                  withArrow
                  openDelay={400}
                >
                  <span style={{ display: 'flex', flexShrink: 0 }}>
                    <Icon
                      icon={icon}
                      width={INTERACTIVE_FRAME.compactIconSize}
                      height={INTERACTIVE_FRAME.compactIconSize}
                      style={{ color: accent || 'var(--mantine-color-blue-6)' }}
                    />
                  </span>
                </Tooltip>
                {/* The accent stops at the icon. `InteractiveTitle` tints the
                    title too, but a control is one unit on its own row, while
                    these are a list — coloured labels beside dimmed values at
                    `xs` read as a legend and cost the contrast that makes the
                    two columns scannable.

                    The label yields its room to the value: a truncated value
                    ("3 sel…") says nothing, while a truncated label still
                    reads next to the control it names. */}
                <Text size="xs" fw={500} truncate style={{ flex: '1 1 auto', minWidth: 0 }}>
                  {label}
                </Text>
                {value && (
                  <Text size="xs" c="dimmed" truncate style={{ flex: '0 1 auto', minWidth: 0 }}>
                    {value}
                  </Text>
                )}
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="xs"
                  aria-label={`Clear filter ${label}`}
                  onClick={() => onClear({ ...f, value: null })}
                  style={{ flexShrink: 0 }}
                >
                  <Icon icon="mdi:close" width={12} height={12} />
                </ActionIcon>
              </Group>
            );
          })}
        </Stack>
      </Collapse>
    </Box>
  );
};

export default ActiveFilterSummary;

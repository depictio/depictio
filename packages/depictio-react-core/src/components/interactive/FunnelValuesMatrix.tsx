/**
 * Values by stages matrix for the funnel overview's "values of a column" mode.
 *
 * One row per distinct value of the charted column, one column for the
 * unfiltered data and one per stage. A filled cell means the value is still
 * present after that stage, an empty one that it was removed at or before it.
 * Stages are cumulative, so each row reads as a run of filled cells followed by
 * empty ones, and where the run ends is the filter that dropped the value.
 * The row logic lives in `funnelStages` (`buildValuesMatrix`).
 */
import React, { useMemo, useState } from 'react';
import {
  Badge,
  Box,
  getThemeColor,
  Group,
  ScrollArea,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { FunnelColumnValues } from '../../api';
import {
  buildValuesMatrix,
  filterMatrixRows,
  formatCount,
  MATRIX_ROW_LIMIT,
  matrixCellLabel,
  matrixSummary,
  type MatrixCell,
} from './funnelStages';

/** A stage column's header. */
export interface MatrixStage {
  /** Short name shown in the header. */
  name: string;
  /** The chart's band label for this stage, shown in the header tooltip. */
  label: string;
  /** Mantine palette name or CSS color: the group's color for a group stage. */
  color: string;
}

export interface FunnelValuesMatrixProps {
  columnName: string;
  initial: FunnelColumnValues | null | undefined;
  /** Each stage's values, aligned with `stages`. */
  stageValues: readonly (FunnelColumnValues | null | undefined)[];
  stages: readonly MatrixStage[];
  /** Palette name for the unfiltered column and the legend. */
  accent: string;
}

const ALL_DATA = 'All data';
const CELL_PX = 12;
/** Past this the value column truncates; the full value stays in the title. */
const VALUE_COLUMN_PX = 180;
/** Tall enough for a dozen rows before the matrix scrolls on its own. */
const MATRIX_MAX_HEIGHT = 340;

/** The count line under a header, its accessible name and the header tooltip:
 *  the distinct count for the unfiltered column, what it removed for a stage. */
function headerCount(
  stage: MatrixStage | null,
  removed: number | null,
  total: number | null,
): { text: string; label: string; tooltip: string } {
  if (!stage) {
    return {
      text: formatCount(total),
      label: `${formatCount(total)} values`,
      tooltip: `Unfiltered: ${formatCount(total)} distinct values.`,
    };
  }
  if (removed === null) {
    return {
      text: '?',
      label: 'unknown removed',
      tooltip: `${stage.label}. Removed an unknown number of values.`,
    };
  }
  return {
    text: `−${removed.toLocaleString()}`,
    label: `${removed} removed`,
    tooltip: `${stage.label}. Removed ${removed.toLocaleString()} ${removed === 1 ? 'value' : 'values'}.`,
  };
}

const Swatch: React.FC<{ cell: MatrixCell; paint: string; label?: string }> = ({
  cell,
  paint,
  label,
}) => {
  const style: React.CSSProperties = {
    display: 'inline-block',
    width: CELL_PX,
    height: CELL_PX,
    flexShrink: 0,
    boxSizing: 'border-box',
    borderRadius: 'var(--mantine-radius-xs)',
    verticalAlign: 'middle',
  };
  if (cell === 'kept') style.background = paint;
  else if (cell === 'removed') style.border = '1px solid var(--mantine-color-default-border)';
  else style.border = '1px dashed var(--mantine-color-dimmed)';
  return (
    <Box
      component="span"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      title={label}
      data-cell={cell}
      style={style}
    />
  );
};

/** Keeps the value column in view while the stages scroll sideways. */
const stickyValueCell: React.CSSProperties = {
  position: 'sticky',
  left: 0,
  zIndex: 1,
  background: 'var(--mantine-color-body)',
};

const FunnelValuesMatrix: React.FC<FunnelValuesMatrixProps> = ({
  columnName,
  initial,
  stageValues,
  stages,
  accent,
}) => {
  const theme = useMantineTheme();
  const [query, setQuery] = useState('');

  const matrix = useMemo(() => buildValuesMatrix(initial, stageValues), [initial, stageValues]);
  const matching = useMemo(() => filterMatrixRows(matrix.rows, query), [matrix, query]);
  const shown = matching.slice(0, MATRIX_ROW_LIMIT);

  const columns = useMemo(() => [ALL_DATA, ...stages.map((s) => s.name)], [stages]);
  const accentPaint = getThemeColor(accent, theme);
  const paints = useMemo(
    () => [accentPaint, ...stages.map((s) => getThemeColor(s.color, theme))],
    [accentPaint, stages, theme],
  );

  const searching = query.trim() !== '';
  let emptyMessage: string | null = null;
  if (matrix.rows.length === 0) emptyMessage = 'No values to list.';
  else if (shown.length === 0) emptyMessage = `No value matches “${query.trim()}”.`;

  return (
    <Stack gap={6} data-testid="funnel-values-matrix">
      <Group justify="space-between" align="flex-end" wrap="wrap" gap="xs">
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="sm" fw={600} truncate>
            Values of {columnName} by stage
          </Text>
          <Text size="xs" c="dimmed" data-testid="funnel-values-summary">
            {matrixSummary(matrix.counts)}
          </Text>
        </Stack>
        <TextInput
          size="xs"
          placeholder="Search values"
          aria-label={`Search values of ${columnName}`}
          leftSection={<Icon icon="mdi:magnify" width={14} height={14} />}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          style={{ flex: '0 1 200px', minWidth: 140 }}
          data-testid="funnel-values-search"
        />
      </Group>

      <Group gap="md" wrap="wrap">
        <Group gap={4} wrap="nowrap">
          <Swatch cell="kept" paint={accentPaint} />
          <Text size="xs" c="dimmed">
            still present
          </Text>
        </Group>
        <Group gap={4} wrap="nowrap">
          <Swatch cell="removed" paint={accentPaint} />
          <Text size="xs" c="dimmed">
            removed at or before this stage
          </Text>
        </Group>
        {matrix.hasUnknown && (
          <Group gap={4} wrap="nowrap">
            <Swatch cell="unknown" paint={accentPaint} />
            <Text size="xs" c="dimmed">
              unknown
            </Text>
          </Group>
        )}
      </Group>

      {emptyMessage ? (
        <Text size="xs" c="dimmed">
          {emptyMessage}
        </Text>
      ) : (
        <ScrollArea.Autosize mah={MATRIX_MAX_HEIGHT} type="auto" offsetScrollbars>
          <Table
            stickyHeader
            withRowBorders={false}
            verticalSpacing={2}
            horizontalSpacing={6}
            style={{ width: 'auto' }}
          >
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ ...stickyValueCell, zIndex: 2, verticalAlign: 'bottom' }}>
                  <Text size="xs" fw={600} truncate style={{ maxWidth: VALUE_COLUMN_PX }}>
                    {columnName}
                  </Text>
                </Table.Th>
                {columns.map((name, col) => {
                  const stage = col > 0 ? stages[col - 1] : null;
                  const removed = col > 0 ? matrix.removed[col - 1] : null;
                  const count = headerCount(stage, removed, matrix.counts[0]);
                  return (
                    <Table.Th key={col} style={{ textAlign: 'center', verticalAlign: 'bottom' }}>
                      <Tooltip label={count.tooltip} withArrow multiline maw={260} openDelay={200}>
                        <Stack gap={0} align="center">
                          <Group gap={4} wrap="nowrap">
                            {stage && (
                              <Badge size="xs" variant="light" color={stage.color} circle>
                                {col}
                              </Badge>
                            )}
                            <Text size="xs" fw={600} truncate style={{ maxWidth: 88 }}>
                              {name}
                            </Text>
                          </Group>
                          <Text size="xs" c="dimmed" aria-label={count.label}>
                            {count.text}
                          </Text>
                        </Stack>
                      </Tooltip>
                    </Table.Th>
                  );
                })}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.map((row) => (
                <Table.Tr key={row.value}>
                  <Table.Td style={stickyValueCell}>
                    <Text
                      size="xs"
                      ff="monospace"
                      truncate
                      title={row.value}
                      style={{ maxWidth: VALUE_COLUMN_PX }}
                    >
                      {row.value}
                    </Text>
                  </Table.Td>
                  {row.cells.map((cell, col) => (
                    <Table.Td key={col} style={{ textAlign: 'center' }}>
                      <Swatch
                        cell={cell}
                        paint={paints[col]}
                        label={matrixCellLabel(row, col, columns)}
                      />
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea.Autosize>
      )}

      {matching.length > shown.length && (
        <Text size="xs" c="dimmed" data-testid="funnel-values-limit">
          Showing {shown.length.toLocaleString()} of {matching.length.toLocaleString()}{' '}
          {searching ? 'matching values' : 'values'}. Search to find the rest.
        </Text>
      )}
      {searching && shown.length > 0 && matching.length <= shown.length && (
        <Text size="xs" c="dimmed">
          {matching.length.toLocaleString()} of {matrix.rows.length.toLocaleString()} values
          match.
        </Text>
      )}
      {matrix.unlisted > 0 && (
        <Text size="xs" c="dimmed" data-testid="funnel-values-unlisted">
          {matrix.unlisted.toLocaleString()} of the {formatCount(matrix.counts[0])} values have
          no row: the server lists only the first values of each stage in sorted order, and these
          fell past every list. Search cannot find them; the counts under each stage cover every
          value.
        </Text>
      )}
      {matrix.hasUnknown && (
        <Text size="xs" c="dimmed">
          Dashed cells are unknown: that stage failed to load, or its value list was capped
          before reaching the value.
        </Text>
      )}
    </Stack>
  );
};

export default FunnelValuesMatrix;

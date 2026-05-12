import React, { useMemo, useState } from 'react';
import {
  Alert,
  Collapse,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Table,
  Text,
  UnstyledButton,
} from '@mantine/core';

import ErrorBoundary from '../ErrorBoundary';

interface AdvancedVizFrameProps {
  /** Inner content (the viz itself). */
  children: React.ReactNode;
  /** Optional top-bar controls rendered above the chart (sliders, search, top-N). */
  controls?: React.ReactNode;
  /** Loading state for initial fetch. */
  loading?: boolean;
  /** Error to display in place of children. */
  error?: string | null;
  /** Empty-state message when data fetched but row_count === 0. */
  emptyMessage?: string;
  /**
   * Optional column-oriented row data for the "Show data" collapsible panel
   * below the chart. Keys are column names, values are equally-sized arrays
   * of cell values (same shape as the response from /advanced_viz/data).
   */
  dataRows?: Record<string, unknown[]>;
  /** Column ordering (if omitted, uses Object.keys(dataRows)). */
  dataColumns?: string[];
}

const ROWS_PREVIEW_CAP = 200;

/**
 * Shared wrapper for advanced-viz renderers. Provides:
 *  - error boundary
 *  - loading skeleton
 *  - empty-state messaging
 *  - a top-bar slot for builtin Tier-2 controls (sliders, search, top-N)
 *  - a collapsible "Show data" panel that renders the rows feeding the chart
 *    when `dataRows` is supplied
 *
 * Chrome (title, fullscreen, download, reset) is added by ComponentRenderer's
 * wrapWithChrome() one level above — same convention as figure/table.
 */
const AdvancedVizFrame: React.FC<AdvancedVizFrameProps> = ({
  children,
  controls,
  loading,
  error,
  emptyMessage,
  dataRows,
  dataColumns,
}) => {
  const [tableOpen, setTableOpen] = useState(false);

  const tableInfo = useMemo(() => {
    if (!dataRows) return null;
    const cols = dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows);
    if (cols.length === 0) return null;
    const totalRows = dataRows[cols[0]]?.length ?? 0;
    return { cols, totalRows };
  }, [dataRows, dataColumns]);

  return (
    <ErrorBoundary>
      <Stack gap="xs" style={{ width: '100%', height: '100%' }}>
        {controls ? (
          <div style={{ flex: '0 0 auto', padding: '4px 8px' }}>{controls}</div>
        ) : null}
        <div style={{ flex: '1 1 auto', minHeight: 0, position: 'relative' }}>
          {loading ? (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Loader size="sm" />
            </div>
          ) : error ? (
            <Alert color="red" title="Failed to render" variant="light">
              <Text size="xs">{error}</Text>
            </Alert>
          ) : emptyMessage ? (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'var(--mantine-color-dimmed)',
                fontSize: '0.85rem',
              }}
            >
              {emptyMessage}
            </div>
          ) : (
            children
          )}
        </div>
        {tableInfo && !loading && !error ? (
          <div style={{ flex: '0 0 auto', borderTop: '1px solid var(--mantine-color-default-border)' }}>
            <UnstyledButton
              onClick={() => setTableOpen((v) => !v)}
              style={{ width: '100%', padding: '4px 8px' }}
            >
              <Group gap={6}>
                <Text size="xs" c="dimmed">
                  {tableOpen ? '▾' : '▸'} {tableOpen ? 'Hide data' : 'Show data'}
                </Text>
                <Text size="xs" c="dimmed">
                  ({tableInfo.totalRows.toLocaleString()} rows
                  {tableInfo.totalRows > ROWS_PREVIEW_CAP
                    ? `, showing first ${ROWS_PREVIEW_CAP}`
                    : ''}
                  )
                </Text>
              </Group>
            </UnstyledButton>
            <Collapse in={tableOpen}>
              <ScrollArea h={220} type="auto" offsetScrollbars>
                <Table striped withTableBorder withColumnBorders fz="xs" stickyHeader>
                  <Table.Thead>
                    <Table.Tr>
                      {tableInfo.cols.map((c) => (
                        <Table.Th key={c}>{c}</Table.Th>
                      ))}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {Array.from({
                      length: Math.min(tableInfo.totalRows, ROWS_PREVIEW_CAP),
                    }).map((_, rowIdx) => (
                      <Table.Tr key={rowIdx}>
                        {tableInfo.cols.map((c) => (
                          <Table.Td key={c}>{formatCell(dataRows![c][rowIdx])}</Table.Td>
                        ))}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            </Collapse>
          </div>
        ) : null}
      </Stack>
    </ErrorBoundary>
  );
};

function formatCell(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    // Show floats with up to 4 significant digits, ints raw.
    if (Number.isInteger(v)) return String(v);
    const abs = Math.abs(v);
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return v.toExponential(3);
    return v.toFixed(4).replace(/\.?0+$/, '');
  }
  return String(v);
}

export default AdvancedVizFrame;

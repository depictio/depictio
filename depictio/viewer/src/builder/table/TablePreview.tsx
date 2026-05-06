/**
 * Live preview for the Table builder. Mirrors the Dash component-container
 * div produced by depictio/dash/modules/table_component/frontend.py:design_table
 * — the table renders directly from the resolved DC, no extra config needed.
 *
 * Honors the user's per-column visibility config (cols_json[col].hide) so
 * deselecting columns in the builder is reflected immediately.
 */
import React, { useEffect, useState } from 'react';
import { ScrollArea, Table, Text } from '@mantine/core';
import { fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';

type ColCfg = { hide?: boolean; pinned?: 'left' | 'right' | null };

const PREVIEW_FETCH_LIMIT = 20;
const PREVIEW_DISPLAY_ROWS = 10;

const TablePreview: React.FC = () => {
  const dcId = useBuilderStore((s) => s.dcId);
  const config = useBuilderStore((s) => s.config) as {
    cols_json?: Record<string, ColCfg>;
    striped?: boolean;
    compact?: boolean;
  };

  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId) {
      setPreview(null);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId, PREVIEW_FETCH_LIMIT)
      .then((res) => {
        if (cancelled) return;
        setPreview(res);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : 'Failed to load preview';
        setError(msg);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  if (!dcId) {
    return (
      <PreviewPanel
        empty
        emptyMessage="Pick a data collection to preview the table..."
      />
    );
  }

  if (loading) {
    return <PreviewPanel loading />;
  }

  if (error) {
    return <PreviewPanel error={error} />;
  }

  if (!preview) {
    return <PreviewPanel empty />;
  }

  const colsJson = config.cols_json || {};
  const visibleColumns = preview.columns.filter(
    (col) => colsJson[col]?.hide !== true,
  );
  const displayRows = preview.rows.slice(0, PREVIEW_DISPLAY_ROWS);

  return (
    <PreviewPanel>
      <ScrollArea type="auto" offsetScrollbars>
        <Table
          striped={config.striped ?? true}
          highlightOnHover
          withTableBorder
          withColumnBorders
          verticalSpacing={config.compact ? 4 : 'sm'}
          horizontalSpacing={config.compact ? 'xs' : 'md'}
          fz={config.compact ? 'xs' : 'sm'}
        >
          <Table.Thead>
            <Table.Tr>
              {visibleColumns.map((col) => (
                <Table.Th key={col}>{col}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {displayRows.map((row, i) => (
              <Table.Tr key={i}>
                {visibleColumns.map((col) => (
                  <Table.Td key={col}>
                    {row[col] === null || row[col] === undefined
                      ? ''
                      : String(row[col])}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      <Text size="xs" c="dimmed" mt="sm">
        Showing {displayRows.length} of {preview.total_rows} rows,{' '}
        {visibleColumns.length} columns
      </Text>
    </PreviewPanel>
  );
};

export default TablePreview;

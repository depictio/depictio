/**
 * The rows a new run brought into a Delta collection (#1397), as a table.
 *
 * "Only new rows" (the default) asks the server for that run's rows alone, on
 * the run column every CLI row carries: a plain preview reads the first rows of
 * the table, where an appended run seldom is. Switched off, it shows the
 * table's first rows with those of the runs already seen faded.
 *
 * Shared by the What's new panel (a modal) and the project page
 * (`?table=<dc>&new_runs=<run,...>`).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Group, LoadingOverlay, Stack, Switch, Text, useComputedColorScheme } from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';

import { fetchDataCollectionPreview } from 'depictio-react-core';
import type { InteractiveFilter, PreviewResult } from 'depictio-react-core';

import { RUN_COLUMN } from './newsSplit';

const ROW_LIMIT = 200;
const SEEN_ROW_OPACITY = 0.35;

/** `?new_runs=a,b` on the project page: the runs whose rows to bring out. */
export function readNewRunsFromQuery(search: string): string[] {
  const raw = new URLSearchParams(search).get('new_runs');
  return raw ? raw.split(',').map((s) => s.trim()).filter(Boolean) : [];
}

/** The project page's link to a collection's new rows. */
export function newRowsHref(projectId: string, dcId: string, runs: string[]): string {
  const params = new URLSearchParams({ table: dcId, new_runs: runs.join(',') });
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}

function runFilter(dcId: string, runs: string[]): InteractiveFilter {
  return {
    index: 'whats-new:new-rows',
    value: runs,
    column_name: RUN_COLUMN,
    interactive_component_type: 'MultiSelect',
    metadata: { dc_id: dcId, column_name: RUN_COLUMN, interactive_component_type: 'MultiSelect' },
  } as InteractiveFilter;
}

const NewRowsPreview: React.FC<{ dcId: string; runs: string[]; height?: number }> = ({
  dcId,
  runs,
  height = 400,
}) => {
  const [onlyNew, setOnlyNew] = useState(true);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scheme = useComputedColorScheme('light');
  const runsKey = runs.join(',');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId, ROW_LIMIT, onlyNew ? [runFilter(dcId, runs)] : [])
      .then((res) => {
        if (!cancelled) setPreview(res);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message || 'Failed to load the rows.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dcId, runsKey, onlyNew]);

  const rows = (preview?.rows ?? []) as Record<string, unknown>[];
  const columns = useMemo(() => {
    const names = preview?.columns?.length ? preview.columns : Object.keys(rows[0] ?? {});
    // The run column first: it is what this view is about.
    const ordered = names.includes(RUN_COLUMN)
      ? [RUN_COLUMN, ...names.filter((n) => n !== RUN_COLUMN)]
      : names;
    return ordered.map((field) => ({ field, headerName: field }));
  }, [preview, rows]);
  const fresh = useMemo(() => new Set(runs), [runsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const hasRunColumn = columns.some((c) => c.field === RUN_COLUMN);
  const total = preview?.total_rows ?? rows.length;

  return (
    <Stack gap="xs" data-testid="new-rows-preview">
      <Group justify="space-between" wrap="nowrap">
        <Text size="xs" c="dimmed">
          {onlyNew
            ? `${total} new row${total === 1 ? '' : 's'} from ${runs.join(', ')}`
            : `First ${rows.length} of ${total} rows; rows of runs already seen are faded`}
          {rows.length < total && onlyNew ? `, first ${rows.length} shown` : ''}
        </Text>
        <Switch
          size="xs"
          label="Only new rows"
          checked={onlyNew}
          onChange={(e) => setOnlyNew(e.currentTarget.checked)}
          data-testid="new-rows-only"
        />
      </Group>
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
      {preview && !hasRunColumn && (
        <Text size="xs" c="dimmed">
          This collection has no run column, so its new rows cannot be told apart.
        </Text>
      )}
      <div
        className={scheme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={{ height, width: '100%', position: 'relative' }}
      >
        <LoadingOverlay visible={loading} zIndex={1} />
        <AgGridReact
          rowData={rows}
          columnDefs={columns}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          getRowStyle={(p: { data?: Record<string, unknown> }) => {
            const run = p.data?.[RUN_COLUMN];
            return !onlyNew && run != null && !fresh.has(String(run))
              ? { opacity: SEEN_ROW_OPACITY }
              : undefined;
          }}
          suppressCellFocus
        />
      </div>
    </Stack>
  );
};

export default NewRowsPreview;

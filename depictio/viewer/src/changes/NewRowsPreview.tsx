/**
 * The rows a new run brought into a Delta collection (#1397), as a table.
 *
 * The same system as the dashboard's Overlay: the new runs' rows come first and
 * stand out, the rows already seen follow, faded. "Hide what you had seen"
 * drops them. The new rows are asked for on the run column every CLI row
 * carries, since a plain preview reads the first rows of the table, where an
 * appended run seldom is.
 *
 * Shared by the What's new panel (a modal) and the project page
 * (`?table=<dc>&new_runs=<run,...>`).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Button, Group, LoadingOverlay, Stack, Switch, Text, useComputedColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';
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

const NewRowsPreview: React.FC<{
  dcId: string;
  runs: string[];
  height?: number;
  /** Back to the plain table (the project page); absent in the modal. */
  onClear?: () => void;
}> = ({ dcId, runs, height = 400, onClear }) => {
  const [onlyNew, setOnlyNew] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [seenRows, setSeenRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scheme = useComputedColorScheme('light');
  const runsKey = runs.join(',');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const fresh = new Set(runs);
    Promise.all([
      fetchDataCollectionPreview(dcId, ROW_LIMIT, [runFilter(dcId, runs)]),
      onlyNew ? Promise.resolve(null) : fetchDataCollectionPreview(dcId, ROW_LIMIT),
    ])
      .then(([news, all]) => {
        if (cancelled) return;
        setPreview(news);
        // The rows already seen: the table's first rows, less the new ones.
        setSeenRows(
          ((all?.rows ?? []) as Record<string, unknown>[]).filter(
            (r) => !fresh.has(String(r[RUN_COLUMN])),
          ),
        );
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

  const newRows = (preview?.rows ?? []) as Record<string, unknown>[];
  const rows = useMemo(() => [...newRows, ...seenRows], [newRows, seenRows]);
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
  const total = preview?.total_rows ?? newRows.length;

  return (
    <Stack gap="xs" data-testid="new-rows-preview">
      <Group justify="space-between" wrap="nowrap">
        <Text size="xs" c="dimmed">
          {`${total} new row${total === 1 ? '' : 's'} from ${runs.join(', ')}`}
          {newRows.length < total ? `, first ${newRows.length} shown` : ''}
          {onlyNew || seenRows.length === 0 ? '' : `; below, faded, rows you had seen`}
        </Text>
        <Group gap="sm" wrap="nowrap">
        {onClear && (
          <Button
            size="xs"
            variant="light"
            leftSection={<Icon icon="tabler:filter-off" width={16} />}
            onClick={onClear}
            data-testid="new-rows-clear"
          >
            Back to full table
          </Button>
        )}
        <Switch
          size="xs"
          label="Hide what you had seen"
          checked={onlyNew}
          onChange={(e) => setOnlyNew(e.currentTarget.checked)}
          data-testid="new-rows-hide-seen"
        />
        </Group>
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
          getRowStyle={(p: { data?: Record<string, unknown> }): Record<string, string> | undefined => {
            const run = p.data?.[RUN_COLUMN];
            if (run == null) return undefined;
            return fresh.has(String(run))
              ? { boxShadow: 'inset 3px 0 0 var(--mantine-primary-color-filled)', fontWeight: '600' }
              : { opacity: String(SEEN_ROW_OPACITY) };
          }}
          suppressCellFocus
        />
      </div>
    </Stack>
  );
};

export default NewRowsPreview;

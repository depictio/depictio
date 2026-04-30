/**
 * Data Preview pane. Mirrors the AG Grid panel rendered by the Dash stepper
 * `update_stepper_data_preview` callback (depictio/dash/layouts/stepper.py:838+).
 *
 *  - For table DCs: AG Grid with pagination (10 rows/page), sortable, filterable
 *  - For multiqc DCs: blue alert (no tabular preview)
 *  - For other non-tabular DCs: similar alert
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Center,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef } from 'ag-grid-community';
import { fetchDataCollectionPreview } from 'depictio-react-core';
import type { PreviewResult } from 'depictio-react-core';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';

interface Props {
  dcId: string;
  dcType: string | null;
  shape: { num_rows?: number; num_columns?: number } | null;
}

const DataPreviewTable: React.FC<Props> = ({ dcId, dcType, shape }) => {
  const isMultiQC = dcType?.toLowerCase() === 'multiqc';
  const isTable = dcType?.toLowerCase() === 'table' || dcType == null;

  const [data, setData] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isMultiQC || !dcId) return;
    setLoading(true);
    setError(null);
    fetchDataCollectionPreview(dcId, 100)
      .then((res) => setData(res))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [dcId, isMultiQC]);

  const columnDefs = useMemo<ColDef[]>(() => {
    if (!data?.columns) return [];
    return data.columns.map((c) => ({
      field: c,
      headerName: c,
      sortable: true,
      filter: true,
      resizable: true,
      minWidth: 120,
      valueFormatter: (params) => {
        const v = params.value;
        if (v == null) return '';
        if (typeof v === 'object') return JSON.stringify(v);
        return String(v);
      },
    }));
  }, [data]);

  if (isMultiQC) {
    return (
      <Alert
        color="blue"
        icon={<Icon icon="mdi:chart-line" width={20} />}
        title="MultiQC report"
      >
        MultiQC data collections don't show a data preview — their visualizations
        are rendered directly by the MultiQC component.
      </Alert>
    );
  }

  if (!isTable) {
    return (
      <Alert
        color="gray"
        icon={<Icon icon="mdi:information-outline" width={20} />}
        title="No tabular preview"
      >
        This data collection doesn't support tabular preview.
      </Alert>
    );
  }

  if (loading) {
    return (
      <Center p="lg">
        <Group>
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Loading data preview…
          </Text>
        </Group>
      </Center>
    );
  }

  if (error) {
    return (
      <Alert color="red" title="Failed to load preview">
        <Text size="xs">{error}</Text>
      </Alert>
    );
  }

  if (!data || data.columns.length === 0) {
    return (
      <Alert color="yellow" title="No data">
        <Text size="sm">No rows returned for this data collection.</Text>
      </Alert>
    );
  }

  const totalRowsAll = shape?.num_rows ?? data.total_rows ?? data.rows.length;
  const totalCols = shape?.num_columns ?? data.columns.length;

  return (
    <Stack gap="xs">
      <div className="ag-theme-quartz" style={{ width: '100%', height: 420 }}>
        <AgGridReact
          rowData={data.rows}
          columnDefs={columnDefs}
          pagination={true}
          paginationPageSize={10}
          paginationPageSizeSelector={[10, 25, 50, 100]}
          defaultColDef={{
            flex: 1,
            minWidth: 120,
            sortable: true,
            filter: true,
            resizable: true,
          }}
        />
      </div>

      <Text size="xs" c="dimmed" mt="xs">
        Showing {data.rows.length} of {totalRowsAll.toLocaleString('en-US')} rows,{' '}
        {totalCols} columns
      </Text>
    </Stack>
  );
};

export default DataPreviewTable;

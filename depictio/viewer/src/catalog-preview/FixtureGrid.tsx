import React from 'react';
import { AgGridReact } from 'ag-grid-react';
import type { FixturePreview } from './shared';

const FixtureGrid: React.FC<{ fixture: FixturePreview }> = ({ fixture }) => (
  <AgGridReact
    rowData={fixture.rows}
    columnDefs={fixture.columns.map((c) => ({
      field: c,
      headerName: c,
      sortable: true,
      filter: true,
      resizable: true,
    }))}
    defaultColDef={{ flex: 1, minWidth: 110, resizable: true }}
    suppressFieldDotNotation
  />
);

export default FixtureGrid;

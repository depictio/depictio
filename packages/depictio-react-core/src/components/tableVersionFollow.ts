/**
 * How a mounted table follows a change of data version or definition.
 *
 * A table is unlike the other renderers. Its columns and row count come from
 * a one-shot bootstrap, and its rows from a datasource AG Grid holds on to
 * once `onGridReady` has installed it. Putting the version in a dependency
 * list therefore did nothing: the bootstrap returned early because the grid
 * was already ready, and the rebuilt datasource never reached the grid. A
 * table kept paging the previous commit's rows under a banner naming the new
 * one, and kept the previous definition's columns until a page reload.
 *
 * The fix is to treat "which data, which definition" as the grid's identity:
 *
 *   - the table is ready only for the identity its bootstrap ran for, so a
 *     new identity unmounts the grid in the very render that changes it and
 *     the bootstrap runs again (columns, total, default sort);
 *   - the grid's React key carries the identity, so the grid that comes back
 *     is a new instance and `onGridReady` installs the datasource built for
 *     the new identity;
 *   - a page requested by the previous identity's datasource that lands after
 *     the switch is dropped, rather than painting old rows or an old total.
 *
 * Kept free of React so the decisions can be executed by a test rather than
 * re-read in a review.
 */

import type { IDatasource, IGetRowsParams } from 'ag-grid-community';

import type { TableResponse } from '../api';

/** The data and definition a table grid was built for. */
export function tableGridIdentity(versionKey: string, definitionKey: string): string {
  return JSON.stringify([versionKey, definitionKey]);
}

/**
 * Whether the table may show its grid.
 *
 * Derived rather than stored as a flag, so a new identity reads "not ready"
 * in the same render that introduces it. A flag reset by an effect would
 * leave one render in which the old grid is still mounted against the new
 * datasource.
 */
export function isTableReady(readyFor: string | null, identity: string): boolean {
  return readyFor !== null && readyFor === identity;
}

/**
 * The grid's React key. AG Grid cannot swap the infinite and client-side row
 * models on a live instance, and `rowHeight` / `headerHeight` are initial-only,
 * so both remount it; so does a new identity, which is what puts the new
 * datasource in place.
 */
export function tableGridKey(showAll: boolean, uiScale: number, identity: string): string {
  return `${showAll ? 'client' : 'infinite'}-${uiScale}-${identity}`;
}

export interface TableDatasourceDeps {
  /** One page of rows, under the identity this datasource was built for. */
  fetchRows: (start: number, limit: number) => Promise<TableResponse>;
  /** False once the table has moved to another identity. */
  isCurrent: () => boolean;
  /** Data version the cached row blocks were fetched against (see below). */
  dataVersionRef: { current: string | number | null };
  /** Drop every cached block and page again from row 0. */
  purge: () => void;
  onTotal: (total: number) => void;
  onError: (err: unknown) => void;
}

/** The infinite row model's datasource for one identity. */
export function createTableDatasource(deps: TableDatasourceDeps): IDatasource {
  return {
    getRows: (params: IGetRowsParams) => {
      const start = params.startRow;
      const limit = params.endRow - params.startRow;
      deps
        .fetchRows(start, limit)
        .then((res) => {
          // Fetched for the identity the table has since left: neither its
          // rows nor its total describe what the banner now names.
          if (!deps.isCurrent()) {
            params.failCallback();
            return;
          }
          // An unsorted table is served in Delta scan order. That order is
          // stable while files are only appended, but a compaction (OPTIMIZE /
          // vacuum) rewrites the active file list and reorders the scan, at
          // which point already-cached blocks no longer line up with freshly
          // fetched ones, and the grid silently shows some rows twice and
          // others not at all. The data version changes when that can have
          // happened, so purge and restart paging from a consistent snapshot.
          const version = res.data_version ?? null;
          if (version !== null && deps.dataVersionRef.current === null) {
            deps.dataVersionRef.current = version;
          } else if (version !== null && version !== deps.dataVersionRef.current) {
            deps.dataVersionRef.current = version;
            params.failCallback();
            deps.purge();
            return;
          }
          // lastRow tells the grid the total. It is required so the scrollbar is
          // accurate and the grid stops asking past the end.
          const lastRow =
            typeof res.total === 'number' && res.total >= 0 ? res.total : undefined;
          params.successCallback(res.rows, lastRow);
          if (typeof res.total === 'number') deps.onTotal(res.total);
        })
        .catch((err) => {
          if (deps.isCurrent()) deps.onError(err);
          params.failCallback();
        });
    },
  };
}

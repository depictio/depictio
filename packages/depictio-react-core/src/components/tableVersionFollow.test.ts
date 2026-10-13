import { describe, expect, it } from 'vitest';
import type { IGetRowsParams } from 'ag-grid-community';

import type { TableResponse } from '../api';
import { dataVersionBody } from '../dataVersions';
import { renderDefinitionKey } from '../renderKey';
import {
  createTableDatasource,
  isTableReady,
  tableGridIdentity,
  tableGridKey,
} from './tableVersionFollow';

const DC = '646b0f3c1e4a2d7f8e5b9003';
const keyFor = (state: Parameters<typeof dataVersionBody>[0]) =>
  JSON.stringify(dataVersionBody(state));

const live = keyFor({});
const asOfV1 = keyFor({ asOfVersionId: 'v1' });
const pinned0 = keyFor({ pins: { [DC]: 0 } });
const table = { index: 't', component_type: 'table', dc_id: DC, columns: ['a', 'b'] };
const def = renderDefinitionKey(table as never);
const defRestored = renderDefinitionKey({ ...table, columns: ['a'] } as never);

function page(rows: number, total: number, dataVersion: number | null = 7): TableResponse {
  return {
    columns: [],
    rows: Array.from({ length: rows }, (_, i) => ({ i })),
    total,
    data_version: dataVersion,
  };
}

/** A fake IGetRowsParams that records how the datasource answered. */
function rowsRequest() {
  const calls: { success?: [unknown[], number | undefined]; failed: boolean } = { failed: false };
  const params = {
    startRow: 0,
    endRow: 100,
    successCallback: (rows: unknown[], lastRow?: number) => {
      calls.success = [rows, lastRow];
    },
    failCallback: () => {
      calls.failed = true;
    },
  } as unknown as IGetRowsParams;
  return { params, calls };
}

/** A promise the test resolves by hand, to land a page after a switch. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('a table grid follows its data version and definition', () => {
  it('a pin change, an as-of change or a swapped definition is a new identity', () => {
    const base = tableGridIdentity(live, def);
    expect(tableGridIdentity(asOfV1, def)).not.toBe(base);
    expect(tableGridIdentity(pinned0, def)).not.toBe(base);
    expect(tableGridIdentity(live, defRestored)).not.toBe(base);
    expect(tableGridIdentity(live, def)).toBe(base);
  });

  it('a definition read from another stored version is a new identity too', () => {
    const fromV1 = renderDefinitionKey(table as never, 'v1');
    const fromV2 = renderDefinitionKey(table as never, 'v2');
    expect(fromV1).not.toBe(fromV2);
    expect(tableGridIdentity(live, fromV1)).not.toBe(tableGridIdentity(live, fromV2));
  });

  it('the grid is not ready for an identity its bootstrap did not run for', () => {
    // This is what makes the bootstrap (columns, total) run again after a pin
    // change: the grid that was ready for live data is not ready for v1.
    const readyFor = tableGridIdentity(live, def);
    expect(isTableReady(readyFor, tableGridIdentity(live, def))).toBe(true);
    expect(isTableReady(readyFor, tableGridIdentity(asOfV1, def))).toBe(false);
    expect(isTableReady(readyFor, tableGridIdentity(live, defRestored))).toBe(false);
    expect(isTableReady(null, tableGridIdentity(live, def))).toBe(false);
  });

  it('a new identity remounts the grid, so onGridReady installs the new datasource', () => {
    const before = tableGridKey(false, 1, tableGridIdentity(live, def));
    expect(tableGridKey(false, 1, tableGridIdentity(asOfV1, def))).not.toBe(before);
    expect(tableGridKey(false, 1, tableGridIdentity(live, defRestored))).not.toBe(before);
    // The reasons it already remounted for still hold.
    expect(tableGridKey(true, 1, tableGridIdentity(live, def))).not.toBe(before);
    expect(tableGridKey(false, 1.2, tableGridIdentity(live, def))).not.toBe(before);
  });
});

describe('createTableDatasource', () => {
  function build(fetchRows: (start: number, limit: number) => Promise<TableResponse>) {
    const state = {
      current: true,
      totals: [] as number[],
      errors: [] as unknown[],
      purged: 0,
      dataVersionRef: { current: null as string | number | null },
    };
    const ds = createTableDatasource({
      fetchRows,
      isCurrent: () => state.current,
      dataVersionRef: state.dataVersionRef,
      purge: () => {
        state.purged += 1;
      },
      onTotal: (t) => state.totals.push(t),
      onError: (e) => state.errors.push(e),
    });
    return { ds, state };
  }

  it('serves the rows and the total of its own identity', async () => {
    const { ds, state } = build(async () => page(50, 50));
    const { params, calls } = rowsRequest();
    ds.getRows(params);
    await flush();
    expect(calls.success?.[0]).toHaveLength(50);
    expect(calls.success?.[1]).toBe(50);
    expect(state.totals).toEqual([50]);
  });

  it('drops a page that lands after the table moved to another identity', async () => {
    // The scenario of the bug: "use v1's data" while the live table's page is
    // in flight. That page (150 rows) must not paint, nor set the total.
    const pending = deferred<TableResponse>();
    const { ds, state } = build(() => pending.promise);
    const { params, calls } = rowsRequest();
    ds.getRows(params);
    state.current = false;
    pending.resolve(page(100, 150));
    await flush();
    expect(calls.success).toBeUndefined();
    expect(calls.failed).toBe(true);
    expect(state.totals).toEqual([]);
  });

  it('does not report a failure of an identity the table has left', async () => {
    const pending = deferred<TableResponse>();
    const { ds, state } = build(() => pending.promise);
    const { params, calls } = rowsRequest();
    ds.getRows(params);
    state.current = false;
    pending.reject(new Error('Version v1 no longer exists'));
    await flush();
    expect(state.errors).toEqual([]);
    expect(calls.failed).toBe(true);
  });

  it('reports a failure of its own identity', async () => {
    const { ds, state } = build(async () => {
      throw new Error('boom');
    });
    const { params } = rowsRequest();
    ds.getRows(params);
    await flush();
    expect(state.errors).toHaveLength(1);
  });

  it('still purges when the data version moves under a mounted grid', async () => {
    const pages = [page(100, 150, 1), page(100, 150, 2)];
    const { ds, state } = build(async () => pages.shift()!);
    const first = rowsRequest();
    ds.getRows(first.params);
    await flush();
    expect(first.calls.success).toBeDefined();
    const second = rowsRequest();
    ds.getRows(second.params);
    await flush();
    expect(second.calls.failed).toBe(true);
    expect(state.purged).toBe(1);
    expect(state.dataVersionRef.current).toBe(2);
  });
});

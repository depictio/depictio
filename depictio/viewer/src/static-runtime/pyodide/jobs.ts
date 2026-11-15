/**
 * Python-live tiles (`BundleManifest.python_components`): the api shim asks
 * here before it falls back to a frozen payload.
 *
 * Each job runs the server's own Python over the bundled table under the
 * CURRENT filter mask — computed by the same in-browser engine every live
 * tile uses, cross-DC links resolved — so a Python tile filters exactly like a
 * TypeScript one. Above the job's `max_rows` the caller serves the
 * export-time snapshot instead (stated in the tier detail).
 */
import { resolveUri, type PythonComponent } from 'depictio-static-core';

import type { InteractiveFilter } from '../../../../../packages/depictio-react-core/src/api';
import { bundle, rawBundle } from '../bundle';
import {
  dataRefFor,
  liveEngine,
  resolveLinkFilters,
  tableFor,
  toBoundFilters,
} from '../liveData';
import { callJob, ensureTable, pythonRuntimeEmbedded } from './runtime';

/** The Python job for a component, when this bundle can run it. */
export function pythonJob(componentId: string | undefined): PythonComponent | null {
  if (!componentId || !pythonRuntimeEmbedded()) return null;
  const job = rawBundle().python_components?.[componentId];
  return job && dataRefFor(job.dc_id) ? job : null;
}

/** The component whose job reads `dcId` with `kind`, for dc-keyed requests. */
export function pythonJobFor(dcId: string, kind: PythonComponent['job']): [string, PythonComponent] | null {
  if (!pythonRuntimeEmbedded()) return null;
  for (const [cid, job] of Object.entries(rawBundle().python_components ?? {})) {
    if (job.job === kind && job.dc_id === dcId && dataRefFor(dcId)) return [cid, job];
  }
  return null;
}

export class TooManyRowsError extends Error {}

/** Run `job` for `request` under `filters`. */
export async function runPythonJob<T>(
  job: PythonComponent,
  request: unknown,
  filters: InteractiveFilter[],
): Promise<{ result: T; rows: number }> {
  const ref = dataRefFor(job.dc_id);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${job.dc_id}"`);
  const { handle } = await tableFor(job.dc_id);
  const bound = toBoundFilters(await resolveLinkFilters(job.dc_id, filters));
  const mask = bound.length ? (await liveEngine().mask(handle, bound)).mask : null;
  let rows = ref.rows;
  if (mask) {
    rows = 0;
    for (let i = 0; i < mask.length; i++) rows += mask[i] === 1 ? 1 : 0;
  }
  if (job.max_rows && rows > job.max_rows) {
    throw new TooManyRowsError(
      `${rows.toLocaleString()} filtered rows is above this tile's in-browser limit ` +
        `(${job.max_rows.toLocaleString()}); showing the export-time snapshot`,
    );
  }
  await ensureTable(job.dc_id, () => {
    const resolved = resolveUri(bundle(), job.table_uri);
    if (resolved.kind !== 'inline') throw new Error('Python runtime: inline tables only');
    return resolved.bytes;
  });
  const fn = job.job;
  const result = await callJob<T>(fn, { ...(job.spec ?? {}), ...(request as object) }, job.dc_id, mask ? Uint8Array.from(mask) : null);
  return { result, rows };
}

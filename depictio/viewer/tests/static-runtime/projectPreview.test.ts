/**
 * The project page's data preview, offline: a collection's first rows come
 * from its bundled Parquet through the dashboard's own engine, and a
 * collection the file does not carry is refused rather than fetched.
 *
 * Run like tests/projects (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/static-runtime
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import type { BundleManifest } from 'depictio-static-core';

const FIXTURES = join(__dirname, '../../../../packages/depictio-static-core/fixtures');
const DC = 'dc00000000000000000000e1';

/** The tab fixture, carrying the engine's real Parquet fixture as one of its
 *  tables (the hand-written fixture's own blob is a placeholder). */
function manifestWithTable(): BundleManifest {
  const manifest = JSON.parse(
    readFileSync(join(FIXTURES, 'manifest-tabs.json'), 'utf-8'),
  ) as BundleManifest;
  const bytes = readFileSync(join(FIXTURES, 'engine-fixture.parquet'));
  manifest.inline_blobs[`dc_${DC}`] = bytes.toString('base64');
  manifest.data_refs[DC] = {
    uri: `inline:dc_${DC}`,
    rows: 2000,
    size_bytes: bytes.length,
    columns: [
      { name: 'idx_i32', dtype: 'Int32' },
      { name: 'value_i64', dtype: 'Int64' },
      { name: 'category_str', dtype: 'String' },
      { name: 'batch', dtype: 'Int64' },
      { name: '__code__batch', dtype: 'Int32' },
      { name: '__ts__event_date', dtype: 'Int64' },
    ],
    companions: { __code__batch: 'batch', __ts__event_date: 'event_date' },
    codebooks: {},
  };
  return manifest;
}

describe('previewLive', () => {
  let previewLive: typeof import('../../src/static-runtime/liveData').previewLive;

  beforeAll(async () => {
    const manifest = manifestWithTable();
    // The runtime reads the manifest from `window` (main.tsx puts it there).
    (globalThis as unknown as { window: Record<string, unknown> }).window = {
      __DEPICTIO_BUNDLE__: manifest,
    };
    ({ previewLive } = await import('../../src/static-runtime/liveData'));
  });

  it("reads a bundled table's first rows, in file order, without companions", async () => {
    const preview = await previewLive(DC, 3);
    expect(preview.columns).toEqual(['idx_i32', 'value_i64', 'category_str', 'batch']);
    expect(preview.total_rows).toBe(2000);
    expect(preview.total_columns).toBe(4);
    expect(preview.rows.map((r) => r.idx_i32)).toEqual([0, 1, 2]);
    // Int64 arrives as a JSON number, as from the server, never a BigInt.
    expect(typeof preview.rows[0].value_i64).toBe('number');
    expect(preview.rows[0].value_i64).toBe(188);
  });

  it('refuses a collection the file does not carry', async () => {
    await expect(previewLive('dc00000000000000000000m1', 10)).rejects.toThrow(/no data_ref/);
  });
});

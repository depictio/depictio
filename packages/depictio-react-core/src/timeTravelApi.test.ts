/**
 * The time-travel request contracts, executed against a stubbed `fetch`.
 *
 * Each test calls the real API function and asserts on the request it sends
 * or on how it reads the answer: what `definition_version`, the filter
 * options, the status and the versioned cross-tab read put on the wire, and
 * what a 409 or a stale `as_of_version` turns into.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DATA_VERSION_GONE_EVENT,
  DEFINITION_COLLECTION_CHANGED_MESSAGE,
  HttpError,
  fetchColumnRangeAt,
  fetchCrossTabComponents,
  fetchDashboard,
  fetchDataVersionStatus,
  fetchUniqueValuesAt,
  isHttpStatus,
  isStaleDataVersionDetail,
  isStaleDataVersionError,
  renderFigure,
  renderTable,
  restoreComponentFromVersion,
  type DataVersionGoneDetail,
} from './api';
import { dataPinBody, dataVersionBody, isDataVersionActive } from './dataVersions';

const DC = '646b0f3c1e4a2d7f8e5b9003';

interface Sent {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
}

let sent: Sent[] = [];
let respond: (url: string) => { status: number; body: unknown } = () => ({ status: 200, body: {} });
let events: DataVersionGoneDetail[] = [];

beforeEach(() => {
  sent = [];
  events = [];
  const target = new EventTarget();
  target.addEventListener(DATA_VERSION_GONE_EVENT, (e) => {
    events.push((e as CustomEvent<DataVersionGoneDetail>).detail);
  });
  vi.stubGlobal('window', target);
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    sent.push({
      url,
      method: init.method ?? 'GET',
      body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
    });
    const { status, body } = respond(url);
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  respond = () => ({ status: 200, body: {} });
});

describe('the request body', () => {
  it('a preview sends its version as definition_version, never component_overrides', () => {
    const body = dataVersionBody({ asOfVersionId: 'v-abc', definitionVersionId: 'v-abc' });
    expect(body).toEqual({ as_of_version: 'v-abc', definition_version: 'v-abc' });
    expect('component_overrides' in body).toBe(false);
  });

  it('a live render adds nothing', () => {
    expect(dataVersionBody({})).toEqual({});
  });

  it('filter options and status carry the pins, without the definition', () => {
    const state = { asOfVersionId: 'v1', pins: { [DC]: null }, definitionVersionId: 'v1' };
    expect(dataPinBody(state)).toEqual({ as_of_version: 'v1', data_versions: { [DC]: null } });
  });

  it('a version is active under as-of or a numeric pin, not a lone null pin', () => {
    expect(isDataVersionActive({})).toBe(false);
    expect(isDataVersionActive({ pins: { [DC]: null } })).toBe(false);
    expect(isDataVersionActive({ pins: { [DC]: 0 } })).toBe(true);
    expect(isDataVersionActive({ asOfVersionId: 'v1' })).toBe(true);
  });
});

describe('render responses (contracts A and E)', () => {
  it('definition_version reaches render_figure', async () => {
    respond = () => ({ status: 200, body: { figure: {}, metadata: {} } });
    await renderFigure('d1', 'c1', [], 'light', false, undefined, undefined, {
      definition_version: 'v-abc',
    });
    expect(sent[0].url).toContain('/dashboards/render_figure/d1/c1');
    expect(sent[0].body?.definition_version).toBe('v-abc');
  });

  it('a 409 says the version read another collection, on the tile', async () => {
    respond = () => ({ status: 409, body: { detail: 'collection mismatch' } });
    const err = await renderFigure('d1', 'c1', [], 'light', false, undefined, undefined, {
      definition_version: 'v-abc',
    }).catch((e) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect(err.status).toBe(409);
    expect(err.message).toBe(DEFINITION_COLLECTION_CHANGED_MESSAGE);
  });

  it('a stale as_of_version raises the gone event with the id that was sent', async () => {
    respond = () => ({ status: 400, body: { detail: 'Version v-old no longer exists' } });
    const err = await renderTable('d1', 't1', [], 0, 10, null, 'desc', undefined, {
      as_of_version: 'v-old',
    }).catch((e) => e);
    expect(isStaleDataVersionError(err)).toBe(true);
    expect(err.message).toBe('Version v-old no longer exists');
    expect(events).toEqual([
      { asOfVersionId: 'v-old', message: 'Version v-old no longer exists' },
    ]);
  });

  it('any other failure keeps its old message and raises nothing', async () => {
    respond = () => ({ status: 500, body: { detail: 'boom' } });
    const err = await renderFigure('d1', 'c1', []).catch((e) => e);
    expect(err.message).toBe('Failed to render figure: 500');
    expect(events).toEqual([]);
  });

  it('the stale detail is matched loosely', () => {
    expect(isStaleDataVersionDetail(400, 'Version abc no longer exists')).toBe(true);
    expect(isStaleDataVersionDetail(400, 'version abc no longer exists (pruned)')).toBe(true);
    expect(isStaleDataVersionDetail(404, 'Version abc no longer exists')).toBe(false);
    expect(isStaleDataVersionDetail(400, 'Invalid data_versions')).toBe(false);
    expect(isStaleDataVersionDetail(400, null)).toBe(false);
  });

  it('fetchDashboard keeps its status, so a deleted tab reads as a 404', async () => {
    respond = () => ({ status: 404, body: { detail: 'not found' } });
    const err = await fetchDashboard('gone').catch((e) => e);
    expect(isHttpStatus(err, 404)).toBe(true);
    expect(err.message).toBe('Failed to fetch dashboard: 404');
  });
});

describe('filter options (contract B)', () => {
  it('unique values are read at the version', async () => {
    respond = () => ({ status: 200, body: { values: ['Setosa'] } });
    const values = await fetchUniqueValuesAt('d1', DC, 'variety', { as_of_version: 'v1' }, "col('x') > 1");
    expect(values).toEqual(['Setosa']);
    expect(sent[0].url).toContain('/dashboards/filter_options/d1');
    expect(sent[0].method).toBe('POST');
    expect(sent[0].body).toEqual({
      dc_id: DC,
      column: 'variety',
      kind: 'unique',
      filter_expr: "col('x') > 1",
      as_of_version: 'v1',
    });
  });

  it('a range is read at the version', async () => {
    respond = () => ({ status: 200, body: { min: 1, max: 1.9, dtype: 'float64', unique: 9 } });
    const range = await fetchColumnRangeAt('d1', DC, 'petal.length', { data_versions: { [DC]: 0 } });
    expect(range).toEqual({ min: 1, max: 1.9, dtype: 'float64', unique: 9 });
    expect(sent[0].body).toEqual({
      dc_id: DC,
      column: 'petal.length',
      kind: 'range',
      data_versions: { [DC]: 0 },
    });
  });
});

describe('status, cross-tab and component restore (contracts C and D)', () => {
  it('the status is asked for the pins in use', async () => {
    respond = () => ({
      status: 200,
      body: { collections: [{ dc_id: DC, status: 'pinned', delta_version: 0 }] },
    });
    const res = await fetchDataVersionStatus('d1', { as_of_version: 'v1' });
    expect(sent[0].url).toContain('/dashboards/data_version_status/d1');
    expect(sent[0].body).toEqual({ as_of_version: 'v1' });
    expect(res.collections[0].status).toBe('pinned');
  });

  it('a preview reads the cross-tab components as they were in the version', async () => {
    respond = () => ({ status: 200, body: { parent_dashboard_id: 'p', floating: [] } });
    await fetchCrossTabComponents('child', 'v-abc');
    await fetchCrossTabComponents('child');
    expect(sent[0].url).toMatch(/\/dashboards\/cross_tab_components\/child\?version_id=v-abc$/);
    expect(sent[1].url).toMatch(/\/dashboards\/cross_tab_components\/child$/);
  });

  it('restoring one component names its tab', async () => {
    respond = () => ({ status: 200, body: {} });
    await restoreComponentFromVersion('v1', 'tab-b', 'card-petal-width', true);
    expect(sent[0].body).toEqual({
      tab_id: 'tab-b',
      component_index: 'card-petal-width',
      restore_layout: true,
    });
  });
});

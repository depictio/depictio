/**
 * A render whose data collection was deleted answers 410
 * `{detail: {code: 'data_collection_deleted', message}}`. The tile shows the
 * message as is, rather than "Failed to render figure: 410".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DATA_COLLECTION_DELETED_CODE,
  DATA_COLLECTION_DELETED_MESSAGE,
  HttpError,
  apiErrorCode,
  renderFigure,
  renderTable,
} from './api';

let status = 410;
let body: unknown = {};

beforeEach(() => {
  vi.stubGlobal('window', new EventTarget());
  vi.stubGlobal(
    'fetch',
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('render of a deleted data collection', () => {
  it('shows the server message on a figure tile', async () => {
    status = 410;
    body = {
      detail: { code: DATA_COLLECTION_DELETED_CODE, message: 'The collection is gone.' },
    };
    const err = await renderFigure('d1', 'c1', []).catch((e) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect(err.status).toBe(410);
    expect(err.message).toBe('The collection is gone.');
    expect(apiErrorCode(err)).toBe(DATA_COLLECTION_DELETED_CODE);
  });

  it('shows it on a table tile too', async () => {
    status = 410;
    body = {
      detail: {
        code: DATA_COLLECTION_DELETED_CODE,
        message: DATA_COLLECTION_DELETED_MESSAGE,
      },
    };
    const err = await renderTable('d1', 't1', [], 0, 10, null, 'desc').catch((e) => e);
    expect(err.message).toBe(DATA_COLLECTION_DELETED_MESSAGE);
    expect(err.message).not.toMatch(/410/);
  });

  it('falls back to the built-in sentence on a bare 410', async () => {
    status = 410;
    body = {};
    const err = await renderFigure('d1', 'c1', []).catch((e) => e);
    expect(err.message).toBe(DATA_COLLECTION_DELETED_MESSAGE);
    expect(apiErrorCode(err)).toBe(DATA_COLLECTION_DELETED_CODE);
  });

  it('recognises the code on another status', async () => {
    status = 404;
    body = { detail: { code: DATA_COLLECTION_DELETED_CODE, message: 'Gone.' } };
    const err = await renderFigure('d1', 'c1', []).catch((e) => e);
    expect(err.message).toBe('Gone.');
  });

  it('leaves a plain 500 alone', async () => {
    status = 500;
    body = { detail: 'boom' };
    const err = await renderFigure('d1', 'c1', []).catch((e) => e);
    expect(err.message).toBe('Failed to render figure: 500');
    expect(apiErrorCode(err)).toBeNull();
  });
});

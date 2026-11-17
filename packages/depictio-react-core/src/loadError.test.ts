import { describe, expect, it } from 'vitest';

import { HttpError, HttpStatusError } from './api';
import { classifyLoadError } from './loadError';

describe('classifyLoadError', () => {
  it.each([404, 410, 400, 422])('reads %i as a missing dashboard', (status) => {
    const info = classifyLoadError(new HttpError(`Failed to fetch dashboard: ${status}`, status));
    expect(info).toMatchObject({ kind: 'not-found', status, retryable: false });
  });

  it.each([401, 403])('reads %i as a refused account', (status) => {
    const info = classifyLoadError(new HttpStatusError(`refused: ${status}`, status));
    expect(info).toMatchObject({ kind: 'forbidden', status, retryable: false });
  });

  it.each([500, 502, 503, 504, 429, 418])('reads %i as unavailable and retryable', (status) => {
    const info = classifyLoadError(new HttpError(`Failed to fetch dashboard: ${status}`, status));
    expect(info).toMatchObject({ kind: 'unavailable', status, retryable: true });
  });

  it('reads a network failure (no status) as unavailable', () => {
    const info = classifyLoadError(new TypeError('Failed to fetch'));
    expect(info).toEqual({
      kind: 'unavailable',
      status: null,
      message: 'Failed to fetch',
      retryable: true,
    });
  });

  it('keeps the raw message for the technical details', () => {
    const info = classifyLoadError(new HttpError('Failed to fetch dashboard: 404', 404));
    expect(info.message).toBe('Failed to fetch dashboard: 404');
  });

  it('classifies a plain { status } object and ignores a non-numeric status', () => {
    expect(classifyLoadError({ status: 403 }).kind).toBe('forbidden');
    expect(classifyLoadError({ status: '404' }).kind).toBe('unavailable');
    expect(classifyLoadError({ status: 4.5 }).status).toBeNull();
  });

  it('survives values that are not errors', () => {
    expect(classifyLoadError(undefined)).toMatchObject({ kind: 'unavailable', status: null });
    expect(classifyLoadError(null).message).toBe('Unknown error');
    expect(classifyLoadError('boom').message).toBe('boom');
  });
});

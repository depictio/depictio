/**
 * Why a dashboard could not be loaded, as the page has to tell it apart.
 *
 * The fetch helpers throw an `HttpStatusError` (an `HttpError` for the
 * dashboard document) carrying the response status. The page needs three
 * answers, not a status code:
 *
 * - `not-found`: the dashboard does not exist, or the link is wrong (404, 410,
 *   and 400/422 for an id the server cannot even parse). Retrying cannot help.
 * - `forbidden`: the server refused this account (401, 403). Retrying with the
 *   same account cannot help; signing in as someone else might.
 * - `unavailable`: anything else: the server answered with an error (5xx), or
 *   did not answer at all (a network failure has no status). Retrying may help.
 *
 * Kept free of imports (the status is read by shape, not `instanceof`) so a
 * plain `{ status }` object, or an error from another bundle, classifies the
 * same way.
 */
export type LoadErrorKind = 'not-found' | 'forbidden' | 'unavailable';

export interface LoadErrorInfo {
  kind: LoadErrorKind;
  /** The HTTP status, or null when the request never got an answer. */
  status: number | null;
  /** The raw message, for a "Technical details" line. Never the headline. */
  message: string;
  /** Whether asking again can change the outcome. */
  retryable: boolean;
}

function statusOf(err: unknown): number | null {
  if (typeof err !== 'object' || err === null) return null;
  const status = (err as { status?: unknown }).status;
  return typeof status === 'number' && Number.isInteger(status) ? status : null;
}

function messageOf(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === 'string' && err) return err;
  if (typeof err === 'object' && err !== null) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === 'string' && message) return message;
  }
  return 'Unknown error';
}

export function classifyLoadError(err: unknown): LoadErrorInfo {
  const status = statusOf(err);
  const message = messageOf(err);
  if (status === 404 || status === 410 || status === 400 || status === 422) {
    return { kind: 'not-found', status, message, retryable: false };
  }
  if (status === 401 || status === 403) {
    return { kind: 'forbidden', status, message, retryable: false };
  }
  return { kind: 'unavailable', status, message, retryable: true };
}

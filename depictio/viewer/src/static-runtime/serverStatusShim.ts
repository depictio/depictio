/**
 * Shim for viewer/src/hooks/useServerStatus.ts in static bundles.
 *
 * The real hook raw-fetches /depictio/api/v1/utils/status every 30 s — a
 * fourth raw-fetch module the RFC's shim census (api.ts, useCurrentUser,
 * realtime) missed. A bundle has no server: report 'offline' statically,
 * no fetch, no polling. (The sidebar's red "Server offline" badge is
 * technically accurate for a bundle; replacing it with a friendlier
 * "Static bundle" chip is later polish.)
 */
export type { ServerStatus, ServerStatusValue } from '../hooks/useServerStatus';

import type { ServerStatus } from '../hooks/useServerStatus';

const STATIC_RESULT: ServerStatus = { status: 'offline', version: null };

export function useServerStatus(): ServerStatus {
  return STATIC_RESULT;
}

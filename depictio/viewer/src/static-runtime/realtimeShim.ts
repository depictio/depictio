/**
 * Shim for depictio-react-core's realtime.ts in static bundles.
 *
 * The real module opens raw WebSockets. It is already inert when the
 * dashboard document has no `project_realtime.enabled` (which a bundle never
 * has), so this shim exists for tree-shaking — the WebSocket plumbing and its
 * reconnect machinery drop out of the bundle entirely (RFC errata #5).
 */
export type {
  RealtimeStatus,
  RealtimeMode,
  RealtimeEvent,
  MonitoringLiveEvent,
} from '../../../../packages/depictio-react-core/src/realtime';

/** Must match ADMIN_MONITORING_CHANNEL in the Python models (and the real
 *  realtime.ts) — inlined so the shim pulls no runtime code from the real
 *  module. */
export const ADMIN_MONITORING_CHANNEL = '__admin_monitoring__';

interface StaticRealtimeResult {
  status: 'disconnected';
  pendingUpdate: false;
  acknowledgePending: () => void;
}

const STATIC_RESULT: StaticRealtimeResult = {
  status: 'disconnected',
  pendingUpdate: false,
  acknowledgePending: () => {},
};

export function useDataCollectionUpdates(
  _dashboardId?: string | null,
  _opts?: Record<string, unknown>,
): StaticRealtimeResult {
  return STATIC_RESULT;
}

export function useMonitoringEvents(): { status: 'disconnected'; events: never[] } {
  return { status: 'disconnected', events: [] };
}

/**
 * Real-time event subscription for the React viewer.
 *
 * Mirrors the disabled-but-built Dash plumbing:
 *   ``depictio/dash/components/realtime_websocket.py`` (frontend)
 *   ``depictio/dash/layouts/realtime_callbacks.py`` (callbacks)
 *   ``depictio/api/v1/endpoints/events_endpoints/routes.py`` (backend)
 *
 * Subscribes to ``/depictio/api/v1/events/ws?token=…&dashboard_id=…`` and
 * exposes connection state + the most recent ``data_collection_updated``
 * event. The viewer uses this to surface a "Data updated" notification
 * (manual mode) or to silently re-fire ``bulkComputeCards`` (auto mode).
 *
 * Callers control behavior via the ``mode`` opt:
 *   - ``manual`` (default): event fires the hook's ``onUpdate`` callback;
 *     the host decides what to render (typically a notification with a
 *     "Refresh" action).
 *   - ``auto``: still fires ``onUpdate``, but with ``auto: true`` so the host
 *     can re-fetch component data immediately.
 *
 * Pause/resume suppresses ``onUpdate`` while keeping the socket open.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export type RealtimeStatus = 'connecting' | 'connected' | 'disconnected';

export type RealtimeMode = 'manual' | 'auto';

/** Discriminated union of message shapes sent by the backend
 *  ``handle_client_message`` + ``EventService``. We only care about a handful
 *  for the viewer; everything else is logged and ignored. */
export type RealtimeEvent =
  | {
      event_type: 'connection_established';
      client_id?: string;
      timestamp?: string;
    }
  | {
      event_type: 'data_collection_updated' | 'data_collection_created';
      timestamp: string;
      dashboard_id?: string;
      data_collection_id?: string;
      payload?: Record<string, unknown>;
    }
  | { event_type: 'heartbeat'; timestamp?: string }
  | { type: 'subscribed' | 'unsubscribed' | 'pong'; dashboard_id?: string };

interface UseDataCollectionUpdatesOptions {
  /** Whether the host wants to receive update events. Defaults to true. */
  enabled?: boolean;
  /** ``manual`` (default) just notifies; ``auto`` flags events for silent
   *  re-fetch. The hook returns the chosen mode so a single state-of-record
   *  drives both the toggle UI and the consumer's reaction. */
  mode?: RealtimeMode;
  /** Pause / resume — suppresses ``onUpdate`` callbacks while keeping the
   *  socket open so reconnects don't pile up after a long pause. */
  paused?: boolean;
  /** Fired on every ``data_collection_updated`` event (when not paused).
   *  ``auto: true`` means the host should refresh silently; ``auto: false``
   *  means it should surface a notification and let the user choose. */
  onUpdate?: (
    event: Extract<
      RealtimeEvent,
      { event_type: 'data_collection_updated' | 'data_collection_created' }
    >,
    auto: boolean,
  ) => void;
}

interface UseDataCollectionUpdatesResult {
  status: RealtimeStatus;
  /** Set when an event arrives but the host is paused — lets the indicator
   *  show a "pending update" badge until the user reconnects / unpauses. */
  pendingUpdate: boolean;
  /** Manual override: dismiss the pending-update badge (e.g. after the host
   *  has applied the update by re-running its bulk fetches). */
  acknowledgePending: () => void;
}

/** Build the ``ws[s]://…/depictio/api/v1/events/ws`` URL from the current
 *  page's location. Mirrors the port-resolution dance in
 *  ``depictio/dash/layouts/realtime_callbacks.py:register_websocket_url_callback``
 *  (HTTPS → wss; dev's Dash port 5080 maps to API port 8058). */
function buildWebSocketUrl(token: string | null, dashboardId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const hostname = window.location.hostname;
  let port: string | null = window.location.port || null;

  // Dev convenience: Dash on 5080 → API on 8058. The React viewer normally
  // runs on 8122 same-origin so this branch rarely fires there, but keeps
  // parity with the Dash callback for shared environments.
  if (port === '5080') port = '8058';
  // Standard https / http on default port: keep empty so URL is clean.
  if (window.location.protocol === 'https:' && (port === '443' || port === '')) port = null;
  if (window.location.protocol === 'http:' && (port === '80' || port === '')) port = null;

  const portSuffix = port ? `:${port}` : '';
  const params = new URLSearchParams();
  if (token) params.set('token', token);
  params.set('dashboard_id', dashboardId);
  return `${proto}//${hostname}${portSuffix}/depictio/api/v1/events/ws?${params.toString()}`;
}

function readToken(): string | null {
  try {
    const raw = localStorage.getItem('local-store');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed?.access_token === 'string' ? parsed.access_token : null;
  } catch {
    return null;
  }
}

/** Subscribe to dashboard-scoped backend events. The hook owns one WebSocket
 *  for the current dashboard, reconnects with capped exponential backoff,
 *  and dispatches ``data_collection_updated`` events to ``onUpdate``. */
export function useDataCollectionUpdates(
  dashboardId: string | null,
  opts: UseDataCollectionUpdatesOptions = {},
): UseDataCollectionUpdatesResult {
  const { enabled = true, mode = 'manual', paused = false, onUpdate } = opts;

  const [status, setStatus] = useState<RealtimeStatus>('disconnected');
  const [pendingUpdate, setPendingUpdate] = useState(false);

  // Hold the latest opt callbacks in refs so reconnects don't tear down the
  // socket every time the consumer re-renders with new closures.
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);

  const acknowledgePending = useCallback(() => setPendingUpdate(false), []);

  useEffect(() => {
    if (!enabled || !dashboardId) {
      setStatus('disconnected');
      return undefined;
    }

    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const token = readToken();
      const url = buildWebSocketUrl(token, dashboardId);
      setStatus('connecting');

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch (err) {
        // Most browsers fail synchronously for malformed URLs only — log and
        // schedule a reconnect so the host doesn't see a permanent broken state.
        console.warn('[realtime] WebSocket constructor failed:', err);
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) return;
        reconnectAttempts.current = 0;
        setStatus('connected');
        // Belt-and-braces: the URL already carries dashboard_id, but the
        // backend also accepts an explicit subscribe message. Keeps state
        // consistent if the connection_manager API ever changes.
        try {
          ws.send(JSON.stringify({ type: 'subscribe', dashboard_id: dashboardId }));
        } catch {
          // ignore
        }
      };

      ws.onmessage = (ev) => {
        if (disposed) return;
        let parsed: RealtimeEvent;
        try {
          parsed = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (
          'event_type' in parsed &&
          (parsed.event_type === 'data_collection_updated' ||
            parsed.event_type === 'data_collection_created')
        ) {
          if (pausedRef.current) {
            setPendingUpdate(true);
            return;
          }
          onUpdateRef.current?.(parsed, modeRef.current === 'auto');
        }
      };

      ws.onerror = () => {
        if (disposed) return;
        // Most onerror events are followed by onclose; let the close handler
        // schedule the reconnect to avoid double timers.
      };

      ws.onclose = () => {
        if (disposed) return;
        setStatus('disconnected');
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      const attempt = reconnectAttempts.current++;
      // 1s, 2s, 4s, 8s, capped at 30s. Resets on successful onopen.
      const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5));
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // ignore
        }
        wsRef.current = null;
      }
      setStatus('disconnected');
    };
    // The connection identity is (dashboardId, enabled). Mode/paused/onUpdate
    // changes are picked up via refs without tearing down the socket.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, enabled]);

  // Whenever the host pauses, surface any pending update so the indicator
  // stays accurate. Whenever it unpauses, clear pendingUpdate (the host is
  // responsible for triggering its refetch).
  useEffect(() => {
    if (!paused) setPendingUpdate(false);
  }, [paused]);

  return { status, pendingUpdate, acknowledgePending };
}

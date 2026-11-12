/**
 * Live "an ingestion finished" events for a set of projects.
 *
 * The backend publishes `ingestion_finished` on the channel `project:<id>` and
 * accepts a subscription to it over the same WebSocket as the dashboard
 * events (`/depictio/api/v1/events/ws`), checking the reader's viewer
 * permission on the project. One socket carries every project the reader
 * follows. Connection handling mirrors `realtime.ts` in depictio-react-core
 * (JWT in the query string, capped exponential backoff), which cannot be
 * extended from here.
 */
import { useEffect, useRef } from 'react';

import { fetchChangesInbox } from 'depictio-react-core';

/** `localStorage` key the shared session lives under (see react-core `api.ts`). */
const SESSION_KEY = 'local-store';

export interface IngestionFinishedPayload {
  project_id: string;
  project_name?: string | null;
  run_id: string;
  status: string;
  run_tags: string[];
  collections: string[];
  at?: string;
}

interface IngestionFinishedMessage {
  event_type: 'ingestion_finished';
  payload: IngestionFinishedPayload;
}

export const projectChannel = (projectId: string): string => `project:${projectId}`;

function storedAccessToken(): string | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return typeof parsed?.access_token === 'string' ? parsed.access_token : null;
  } catch {
    return null;
  }
}

function webSocketUrl(token: string | null): string {
  const { protocol, hostname, port } = window.location;
  const scheme = protocol === 'https:' ? 'wss:' : 'ws:';
  // Same dev convenience as realtime.ts: the legacy front end on 5080 maps to
  // the API on 8058.
  const apiPort = port === '5080' ? '8058' : port;
  const suffix = apiPort && apiPort !== '80' && apiPort !== '443' ? `:${apiPort}` : '';
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${scheme}//${hostname}${suffix}/depictio/api/v1/events/ws${query}`;
}

/**
 * Subscribe to `ingestion_finished` for `projectIds`. Does nothing while
 * `enabled` is false or the list is empty. A project the reader may not see
 * is refused by the server and simply never delivers.
 */
export function useProjectIngestionEvents(
  projectIds: string[],
  onFinished: (payload: IngestionFinishedPayload) => void,
  enabled = true,
): void {
  const handlerRef = useRef(onFinished);
  handlerRef.current = onFinished;
  const key = [...new Set(projectIds)].sort().join(',');

  useEffect(() => {
    const ids = key ? key.split(',') : [];
    if (!enabled || ids.length === 0) return undefined;

    let disposed = false;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;

    const scheduleReconnect = () => {
      if (disposed) return;
      const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempts++, 5));
      timer = setTimeout(connect, delay);
    };

    async function connect() {
      if (disposed) return;
      // A reconnect may come long after the last request refreshed the token,
      // and a socket cannot refresh it: any authenticated call does.
      if (attempts > 0) await fetchChangesInbox().catch(() => undefined);
      if (disposed) return;
      try {
        ws = new WebSocket(webSocketUrl(storedAccessToken()));
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        attempts = 0;
        for (const id of ids) {
          ws?.send(JSON.stringify({ type: 'subscribe', dashboard_id: projectChannel(id) }));
        }
      };
      ws.onmessage = (ev) => {
        let message: Partial<IngestionFinishedMessage>;
        try {
          message = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (message.event_type === 'ingestion_finished' && message.payload) {
          handlerRef.current(message.payload);
        }
      };
      ws.onclose = () => {
        if (!disposed) scheduleReconnect();
      };
    }

    void connect();

    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      try {
        ws?.close();
      } catch {
        // already closed
      }
    };
  }, [key, enabled]);
}

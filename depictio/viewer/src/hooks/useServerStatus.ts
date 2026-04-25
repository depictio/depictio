import { useEffect, useState } from 'react';

/**
 * Polls /depictio/api/v1/utils/status every 30 seconds. Auth-tolerant:
 * a 401, network failure, or any non-2xx response surfaces as "offline" so
 * the badge degrades gracefully when the API is unreachable.
 */

export type ServerStatusValue = 'online' | 'offline' | 'unknown';

export interface ServerStatus {
  status: ServerStatusValue;
  version: string | null;
}

const STATUS_URL = '/depictio/api/v1/utils/status';
const POLL_INTERVAL_MS = 30_000;

export function useServerStatus(): ServerStatus {
  const [state, setState] = useState<ServerStatus>({ status: 'unknown', version: null });

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const res = await fetch(STATUS_URL, {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
          cache: 'no-cache',
        });
        if (!res.ok) {
          if (!cancelled) {
            setState((prev) => ({ status: 'offline', version: prev.version }));
          }
          return;
        }
        const data = (await res.json()) as { status?: string; version?: string };
        if (cancelled) return;
        const value: ServerStatusValue = data.status === 'online' ? 'online' : 'offline';
        setState({ status: value, version: data.version || null });
      } catch {
        if (!cancelled) {
          setState((prev) => ({ status: 'offline', version: prev.version }));
        }
      }
    };

    check();
    const id = window.setInterval(check, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return state;
}

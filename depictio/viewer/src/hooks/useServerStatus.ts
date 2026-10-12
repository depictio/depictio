import { useEffect, useState } from 'react';

/**
 * Polls /depictio/api/v1/utils/status every 30 seconds. Auth-tolerant:
 * a 401, network failure, or any non-2xx response surfaces as "offline" so
 * the badge degrades gracefully when the API is unreachable.
 */

export type ServerStatusValue = 'online' | 'offline' | 'unknown';

/** Feature flags advertised by the (public) status endpoint. */
export interface ServerFeatures {
  ai: boolean;
  ai_user_keys: boolean;
  /** Whole-dashboard generation (POST /ai/generate-dashboard). The server
   *  already folds `ai` into this flag, so it is never true while `ai` is off. */
  ai_generate_dashboard: boolean;
}

export interface ServerStatus {
  status: ServerStatusValue;
  version: string | null;
  features: ServerFeatures;
}

const NO_FEATURES: ServerFeatures = {
  ai: false,
  ai_user_keys: false,
  ai_generate_dashboard: false,
};

const STATUS_URL = '/depictio/api/v1/utils/status';
const POLL_INTERVAL_MS = 30_000;

export function useServerStatus(): ServerStatus {
  const [state, setState] = useState<ServerStatus>({
    status: 'unknown',
    version: null,
    features: NO_FEATURES,
  });

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
            setState((prev) => ({ ...prev, status: 'offline' }));
          }
          return;
        }
        const data = (await res.json()) as {
          status?: string;
          version?: string;
          features?: Partial<ServerFeatures>;
        };
        if (cancelled) return;
        const value: ServerStatusValue = data.status === 'online' ? 'online' : 'offline';
        setState({
          status: value,
          version: data.version || null,
          features: {
            ai: data.features?.ai === true,
            ai_user_keys: data.features?.ai_user_keys === true,
            ai_generate_dashboard: data.features?.ai_generate_dashboard === true,
          },
        });
      } catch {
        if (!cancelled) {
          setState((prev) => ({ ...prev, status: 'offline' }));
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

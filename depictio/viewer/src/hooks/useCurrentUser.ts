import { useEffect, useState } from 'react';

/**
 * Calls /depictio/api/v1/auth/me/optional to identify the current user.
 * Anonymous-tolerant: returns null on missing/invalid token (HTTP 200 with
 * body `null`, or any non-2xx). The strict `/auth/me` would 401 for anon —
 * the React viewer needs the optional variant so the badge degrades to
 * "Sign In" instead of erroring.
 */

const ME_URL = '/depictio/api/v1/auth/me/optional';

export interface CurrentUser {
  email: string;
  is_admin: boolean;
}

export interface UseCurrentUserResult {
  user: CurrentUser | null;
  loading: boolean;
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  try {
    const stored = localStorage.getItem('local-store');
    if (stored) {
      const parsed = JSON.parse(stored);
      if (parsed?.access_token) {
        headers.Authorization = `Bearer ${parsed.access_token}`;
      }
    }
  } catch {
    // ignore malformed localStorage
  }
  return headers;
}

export function useCurrentUser(): UseCurrentUserResult {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(ME_URL, { headers: authHeaders() });
        if (!res.ok) {
          if (!cancelled) {
            setUser(null);
            setLoading(false);
          }
          return;
        }
        const data = (await res.json()) as {
          id?: string;
          email?: string;
          is_admin?: boolean;
        } | null;
        if (cancelled) return;
        if (!data || !data.email) {
          setUser(null);
        } else {
          setUser({ email: data.email, is_admin: Boolean(data.is_admin) });
        }
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { user, loading };
}

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

export type AuthMode = 'standard' | 'single_user' | 'unauthenticated';

export interface UseCurrentUserResult {
  user: CurrentUser | null;
  authMode: AuthMode;
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
  const [authMode, setAuthMode] = useState<AuthMode>('standard');
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
        // Backend now returns { auth_mode, user }. Older shape (just user) is
        // tolerated for forward/backward compat during rollout.
        const data = (await res.json()) as
          | {
              auth_mode?: AuthMode;
              user?: { email?: string; is_admin?: boolean } | null;
              email?: string;
              is_admin?: boolean;
            }
          | null;
        if (cancelled) return;
        const mode: AuthMode = (data?.auth_mode as AuthMode) ?? 'standard';
        const u =
          data?.user ??
          (data?.email ? { email: data.email, is_admin: data.is_admin } : null);
        setAuthMode(mode);
        setUser(
          u && u.email
            ? { email: u.email, is_admin: Boolean(u.is_admin) }
            : null,
        );
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

  return { user, authMode, loading };
}

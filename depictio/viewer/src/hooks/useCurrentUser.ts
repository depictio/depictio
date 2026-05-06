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
  /** MongoDB ObjectId of the user. Required for project permissions checks
   *  (owners/editors/viewers lists store user IDs). Optional for forward
   *  compat with older backends that didn't stamp it. */
  id?: string;
  email: string;
  is_admin: boolean;
}

export type AuthMode = 'standard' | 'single_user' | 'unauthenticated';

export interface UseCurrentUserResult {
  user: CurrentUser | null;
  authMode: AuthMode;
  /** True when the server is configured for unauthenticated public access
   *  (`DEPICTIO_AUTH_PUBLIC_MODE=true`). Visitors are auto-minted temp users
   *  on boot, so `authMode` stays 'standard' — this flag is the only signal
   *  we get that the server is in a special public deployment. */
  isPublicMode: boolean;
  /** True when the server is in demo mode (a public_mode variant with a
   *  curated set of read-only example dashboards). */
  isDemoMode: boolean;
  /** True when the server runs in single-admin mode (no login UI). */
  isSingleUserMode: boolean;
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
  const [isPublicMode, setIsPublicMode] = useState<boolean>(false);
  const [isDemoMode, setIsDemoMode] = useState<boolean>(false);
  const [isSingleUserMode, setIsSingleUserMode] = useState<boolean>(false);
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
        // Backend now returns { auth_mode, user, is_public_mode, is_demo_mode,
        // is_single_user_mode }. Older shape (just user) is tolerated for
        // forward/backward compat during rollout.
        const data = (await res.json()) as
          | {
              auth_mode?: AuthMode;
              user?: { id?: string; email?: string; is_admin?: boolean } | null;
              id?: string;
              email?: string;
              is_admin?: boolean;
              is_public_mode?: boolean;
              is_demo_mode?: boolean;
              is_single_user_mode?: boolean;
            }
          | null;
        if (cancelled) return;
        const mode: AuthMode = (data?.auth_mode as AuthMode) ?? 'standard';
        const u =
          data?.user ??
          (data?.email
            ? { id: data.id, email: data.email, is_admin: data.is_admin }
            : null);
        setAuthMode(mode);
        setIsPublicMode(Boolean(data?.is_public_mode));
        setIsDemoMode(Boolean(data?.is_demo_mode));
        setIsSingleUserMode(Boolean(data?.is_single_user_mode));
        setUser(
          u && u.email
            ? { id: u.id, email: u.email, is_admin: Boolean(u.is_admin) }
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

  return { user, authMode, isPublicMode, isDemoMode, isSingleUserMode, loading };
}

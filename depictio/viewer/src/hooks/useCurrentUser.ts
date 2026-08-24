import { useEffect, useState } from 'react';

import { fetchAuthStatus } from 'depictio-react-core';

/**
 * Calls /depictio/api/v1/auth/me/optional to identify the current user.
 * Anonymous-tolerant: returns null on missing/invalid token (HTTP 200 with
 * body `null`, or any non-2xx). The strict `/auth/me` would 401 for anon —
 * the React viewer needs the optional variant so the badge degrades to
 * "Sign In" instead of erroring.
 *
 * Goes through `fetchAuthStatus` rather than `authFetch` on purpose: this is
 * an identity *probe*, and `authFetch` would refresh the token before asking,
 * i.e. answer "who am I?" by first making sure the answer is "somebody". The
 * chrome that owns this hook is mounted on `/auth` too, so a minting probe
 * signs a just-logged-out user straight back in. See `fetchAuthStatus`.
 */

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
  /** True when the server is in development mode (DEPICTIO_DEV_MODE=true).
   *  Used to suppress the walkthrough during local dev — devs hot-reload
   *  constantly and don't need the tour relaunching on every version bump. */
  isDevMode: boolean;
  /** Explicit walkthrough kill switch (DEPICTIO_WALKTHROUGH_DISABLED=true).
   *  Independent of dev mode — for deployments that just don't want the
   *  onboarding overlay at all (embedded iframes, staging used for
   *  screenshot capture, internal demos with their own narration). */
  walkthroughDisabled: boolean;
  /** True when the server runs in single-admin mode (no login UI). */
  isSingleUserMode: boolean;
  /** TTL of a temporary public-mode user, in hours. Used by the walkthrough
   *  to tell visitors how long a duplicated dashboard / temporary session
   *  will live. Falls back to 24 when the backend didn't supply a value. */
  temporaryUserExpiryHours: number;
  /** Sub-hour TTL component for temporary public-mode users. */
  temporaryUserExpiryMinutes: number;
  /** True when the server enables the docked inspector panel
   *  (`DEPICTIO_VIEWER_INSPECTOR_ENABLED=true`). While false, the component
   *  info and notes surfaces stay in their existing popover and drawer. */
  inspectorEnabled: boolean;
  loading: boolean;
}

export function useCurrentUser(): UseCurrentUserResult {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>('standard');
  const [isPublicMode, setIsPublicMode] = useState<boolean>(false);
  const [isDemoMode, setIsDemoMode] = useState<boolean>(false);
  const [isDevMode, setIsDevMode] = useState<boolean>(false);
  const [walkthroughDisabled, setWalkthroughDisabled] = useState<boolean>(false);
  const [isSingleUserMode, setIsSingleUserMode] = useState<boolean>(false);
  const [temporaryUserExpiryHours, setTemporaryUserExpiryHours] = useState<number>(24);
  const [temporaryUserExpiryMinutes, setTemporaryUserExpiryMinutes] = useState<number>(0);
  const [inspectorEnabled, setInspectorEnabled] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchAuthStatus();
        if (cancelled) return;
        setAuthMode((data.auth_mode as AuthMode) ?? 'standard');
        setIsPublicMode(Boolean(data.is_public_mode));
        setIsDemoMode(Boolean(data.is_demo_mode));
        setIsDevMode(Boolean(data.is_dev_mode));
        setWalkthroughDisabled(Boolean(data.walkthrough_disabled));
        setIsSingleUserMode(Boolean(data.is_single_user_mode));
        setInspectorEnabled(Boolean(data.inspector_enabled));
        if (typeof data.temporary_user_expiry_hours === 'number') {
          setTemporaryUserExpiryHours(data.temporary_user_expiry_hours);
        }
        if (typeof data.temporary_user_expiry_minutes === 'number') {
          setTemporaryUserExpiryMinutes(data.temporary_user_expiry_minutes);
        }
        const u = data.user;
        setUser(u?.email ? { id: u.id, email: u.email, is_admin: Boolean(u.is_admin) } : null);
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

  return {
    user,
    authMode,
    isPublicMode,
    isDemoMode,
    isDevMode,
    walkthroughDisabled,
    isSingleUserMode,
    temporaryUserExpiryHours,
    temporaryUserExpiryMinutes,
    inspectorEnabled,
    loading,
  };
}

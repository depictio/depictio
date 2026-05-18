import { useEffect, useState } from 'react';
import { fetchDashboard } from 'depictio-react-core';
import type {
  DashboardData,
  DashboardPermissions,
  DashboardPermissionsUser,
} from 'depictio-react-core';
import { useCurrentUser } from './useCurrentUser';

export interface UseDashboardAccessResult {
  isOwner: boolean;
  isPublicMode: boolean;
  isDemoMode: boolean;
  /** Toggle into figure Code Mode is allowed (false in public/demo). */
  canUseCodeMode: boolean;
  /** Editing the Code Mode editor + executing code is allowed
   *  (false in public/demo OR when the current user is not an owner). */
  canEditCode: boolean;
  loading: boolean;
}

/**
 * Resolves the current user's relationship to a dashboard for code-mode
 * gating. Anonymous / public-mode visitors get a fresh temp user on boot
 * who never owns any real dashboard, so `isOwner` collapses to false. The
 * server still enforces these on the API; this hook is for UI affordances
 * (disabling the Code Mode toggle, making the Monaco editor read-only).
 */
export function useDashboardAccess(
  dashboardId: string | null | undefined,
): UseDashboardAccessResult {
  const { user, isPublicMode, isDemoMode, loading: userLoading } = useCurrentUser();
  const [isOwner, setIsOwner] = useState<boolean>(false);
  const [dashLoading, setDashLoading] = useState<boolean>(Boolean(dashboardId));

  useEffect(() => {
    if (!dashboardId) {
      setIsOwner(false);
      setDashLoading(false);
      return;
    }
    let cancelled = false;
    setDashLoading(true);
    fetchDashboard(dashboardId)
      .then((dash: DashboardData) => {
        if (cancelled) return;
        const perms = (dash.permissions as DashboardPermissions | undefined) ?? {};
        const owners = perms.owners ?? [];
        const meId = user?.id;
        const meEmail = user?.email;
        const owned = owners.some((o: DashboardPermissionsUser) => {
          if (meId && (o._id === meId || o.id === meId)) return true;
          if (meEmail && o.email && o.email === meEmail) return true;
          return false;
        });
        setIsOwner(owned);
      })
      .catch(() => {
        if (!cancelled) setIsOwner(false);
      })
      .finally(() => {
        if (!cancelled) setDashLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, user?.id, user?.email]);

  const canUseCodeMode = !isPublicMode && !isDemoMode;
  const canEditCode = canUseCodeMode && isOwner;

  return {
    isOwner,
    isPublicMode,
    isDemoMode,
    canUseCodeMode,
    canEditCode,
    loading: userLoading || dashLoading,
  };
}

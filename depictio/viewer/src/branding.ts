import React from 'react';
import { isEmptyBrandTheme, type BrandTheme } from 'depictio-react-core';

// Re-exported so viewer code keeps importing them from here; the definitions
// live in react-core because shared components consume them too.
export { BrandingContext, useBranding } from 'depictio-react-core';

/**
 * Instance branding (issue #397): the deployment's brand theme — logo, name,
 * palette, surfaces, figure colors — served by `/utils/public-config` already
 * resolved (derived values materialised server-side).
 *
 * The config arrives over the network after first paint (the fetch is
 * fire-and-forget, matching the Google Analytics bootstrap), so the last known
 * theme is cached in localStorage: returning visitors get a branded first
 * paint with no flash, and only the very first visit late-applies.
 */

const STORAGE_KEY = 'depictio-branding-cache';
// v2: the flat {logo_url, primary_color, colorway} shape became a BrandTheme.
// A stale v1 entry is dropped rather than migrated — one unbranded first paint
// costs less than a migration path for a cache.
const CACHE_VERSION = 2;

export function readCachedBranding(): BrandTheme | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || parsed.version !== CACHE_VERSION) return null;
    const branding = parsed.branding;
    if (!branding || typeof branding !== 'object') return null;
    return branding as BrandTheme;
  } catch {
    return null;
  }
}

export function cacheBranding(branding: BrandTheme | null): void {
  try {
    if (isEmptyBrandTheme(branding)) {
      // Unbranded instance — drop any stale cache so a deployment that turns
      // branding off doesn't keep showing the old logo forever.
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: CACHE_VERSION, branding }));
    }
  } catch {
    // ignore quota / disabled storage
  }
}

// ── Module-level store ────────────────────────────────────────────────────────
// bootstrapPublicConfig() resolves before/after ThemeRoot mounts depending on
// network timing, so the fetched branding flows through a tiny external store
// (same pattern as the uiScale preference) instead of React state that might
// not exist yet.

let currentBranding: BrandTheme | null = readCachedBranding();
const subscribers = new Set<() => void>();

export function getBranding(): BrandTheme | null {
  return currentBranding;
}

export function setBranding(branding: BrandTheme | null): void {
  cacheBranding(branding);
  const normalized = isEmptyBrandTheme(branding) ? null : branding;
  // Referential equality is what React's useSyncExternalStore checks — skip
  // the notify when nothing changed to avoid a pointless theme rebuild.
  if (JSON.stringify(normalized) === JSON.stringify(currentBranding)) return;
  currentBranding = normalized;
  subscribers.forEach((fn) => fn());
}

export function subscribeBranding(callback: () => void): () => void {
  subscribers.add(callback);
  return () => {
    subscribers.delete(callback);
  };
}

// ── Browser tab title ─────────────────────────────────────────────────────────

/** Product name to fall back on when the deployment states none. */
const DEFAULT_APP_NAME = 'Depictio';

/**
 * Keep the browser tab title on `<instance name> — <page>`.
 *
 * The instance name is part of its identity, so it belongs in the tab too —
 * and it arrives after first paint, which is why this is a hook rather than a
 * one-off assignment: the title re-renders when the branding lands, or when an
 * admin renames the instance without a reload.
 *
 * Pass no `page` for a title that is just the instance name.
 */
export function usePageTitle(page?: string | null): void {
  const branding = React.useSyncExternalStore(subscribeBranding, getBranding);
  const appName = branding?.app_name || DEFAULT_APP_NAME;
  React.useEffect(() => {
    document.title = page ? `${appName} — ${page}` : appName;
  }, [appName, page]);
}

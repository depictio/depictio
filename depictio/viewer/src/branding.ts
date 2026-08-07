import { createContext, useContext } from 'react';

/**
 * Instance branding (issue #397): custom logo / name / colors for a
 * deployment (e.g. a core facility), served by `/utils/public-config`.
 *
 * The config arrives over the network after first paint (the fetch is
 * fire-and-forget, matching the Google Analytics bootstrap), so the last
 * known branding is cached in localStorage: returning visitors get a branded
 * first paint with no flash, and only the very first visit late-applies.
 */

export interface Branding {
  logo_url: string | null;
  logo_url_dark: string | null;
  app_name: string | null;
  primary_color: string | null;
  colorway: string[] | null;
}

const STORAGE_KEY = 'depictio-branding-cache';
const CACHE_VERSION = 1;

export function readCachedBranding(): Branding | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || parsed.version !== CACHE_VERSION) return null;
    const branding = parsed.branding;
    if (!branding || typeof branding !== 'object') return null;
    return branding as Branding;
  } catch {
    return null;
  }
}

export function cacheBranding(branding: Branding | null): void {
  try {
    if (!branding || Object.values(branding).every((value) => value == null)) {
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

export const BrandingContext = createContext<Branding | null>(null);

export function useBranding(): Branding | null {
  return useContext(BrandingContext);
}

// ── Module-level store ────────────────────────────────────────────────────────
// bootstrapPublicConfig() resolves before/after ThemeRoot mounts depending on
// network timing, so the fetched branding flows through a tiny external store
// (same pattern as the uiScale preference) instead of React state that might
// not exist yet.

let currentBranding: Branding | null = readCachedBranding();
const subscribers = new Set<() => void>();

export function getBranding(): Branding | null {
  return currentBranding;
}

export function setBranding(branding: Branding | null): void {
  cacheBranding(branding);
  const normalized =
    branding && Object.values(branding).some((value) => value != null) ? branding : null;
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

/** Hex colors are expanded into a Mantine palette under this name. */
export const BRAND_PALETTE_NAME = 'brand';

/** True when the value looks like a Mantine palette name rather than a hex color. */
export function isMantinePaletteName(color: string): boolean {
  return /^[a-z][a-z0-9-]*$/i.test(color) && !color.startsWith('#');
}

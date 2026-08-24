import { formatDateTime } from '../../lib/datetime';

/** True for icon values that point at an image file (e.g. workflow logos
 *  shipped with the Dash app at `/assets/images/logos/...`). */
export function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/** Resolve a Dash asset path (e.g. `/assets/images/logos/multiqc.png`) to a
 *  loadable URL. The Dash app serves /assets/ on port 5122; the SPA on 8122
 *  doesn't proxy them, so cross-port in dev. Mirrors `resolveAssetUrl()` in
 *  `chrome/Sidebar.tsx`. */
export function resolveAssetUrl(s: string): string {
  if (/^(https?:\/\/|data:)/.test(s)) return s;
  if (s.startsWith('/')) {
    const env = (import.meta as unknown as { env?: Record<string, string> }).env;
    if (env?.VITE_DASH_ORIGIN) return env.VITE_DASH_ORIGIN.replace(/\/$/, '') + s;
    if (
      typeof window !== 'undefined' &&
      window.location.hostname &&
      window.location.port === '8122'
    ) {
      return `${window.location.protocol}//${window.location.hostname}:5122${s}`;
    }
    return s;
  }
  return s;
}

/** Format `last_saved_ts` (ISO or "%Y-%m-%d %H:%M:%S", always UTC on the wire)
 *  as "yyyy-mm-dd HH:MM" **in the viewer's local timezone**.
 *  Thin re-export kept for the existing call sites; see `lib/datetime.ts`. */
export function formatLastSaved(raw: string): string {
  return formatDateTime(raw, raw);
}

/** Version key for a dashboard's thumbnail URL.
 *  Prefers `screenshot_ts` (stamped by the worker once the PNG is actually on
 *  disk) and falls back to `last_saved_ts` for documents predating that field. */
export function screenshotVersion(dashboard: {
  screenshot_ts?: string;
  last_saved_ts?: string;
}): string | undefined {
  return dashboard.screenshot_ts || dashboard.last_saved_ts || undefined;
}

export function screenshotUrl(
  dashboardId: string,
  theme: 'light' | 'dark',
  version?: string,
): string {
  // Cache-bust whenever the PNG is regenerated: the screenshot job overwrites
  // the file in place, so without a versioned URL the browser keeps showing the
  // old image until a hard reload. Pass `screenshotVersion(dashboard)` — it
  // advances when the *image* changes, which `last_saved_ts` alone no longer
  // does now that saves and screenshots are tracked separately (issue #932).
  const base = `/static/screenshots/${dashboardId}_${theme}.png`;
  if (!version) return base;
  return `${base}?v=${encodeURIComponent(version)}`;
}

/** Returns `value` when it's a non-empty string, otherwise `fallback`.
 *  Trims out the repeated `(typeof x === 'string' && x) || fallback` chains
 *  that appear all over the dashboard list rows/cards. */
export function coerceString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value ? value : fallback;
}

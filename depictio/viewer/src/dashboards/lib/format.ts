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

/** Format `last_saved_ts` (ISO or "%Y-%m-%d %H:%M:%S") as "yyyy-mm-dd HH:MM"
 *  to match `dashboards_management.py:607-611`. */
export function formatLastSaved(raw: string): string {
  const d = new Date(raw.replace('Z', '+00:00'));
  if (Number.isNaN(d.getTime())) return raw;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function screenshotUrl(
  dashboardId: string,
  theme: 'light' | 'dark',
  lastSavedTs?: string,
): string {
  // Cache-bust on every save: the auto-screenshot job overwrites the file
  // in place, so without a versioned URL the browser keeps showing the old
  // image until a hard reload. ``last_saved_ts`` changes whenever the
  // dashboard is saved (and the screenshot job runs as part of save), so
  // it's the right version key.
  const base = `/static/screenshots/${dashboardId}_${theme}.png`;
  if (!lastSavedTs) return base;
  return `${base}?v=${encodeURIComponent(lastSavedTs)}`;
}

/** Returns `value` when it's a non-empty string, otherwise `fallback`.
 *  Trims out the repeated `(typeof x === 'string' && x) || fallback` chains
 *  that appear all over the dashboard list rows/cards. */
export function coerceString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value ? value : fallback;
}

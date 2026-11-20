/**
 * Shim for viewer/src/chrome/variants/index.ts in static bundles.
 *
 * A bundle draws Paper (`glass`), the app's default chrome, so a file looks
 * like the dashboard it was exported from — its shell, dock and Plotly
 * styling (`glassPlotly`, applied by every renderer through the active chrome
 * style). The shell is gated for a read-only bundle where it reaches a
 * server: no profile tile, no server card, no "All dashboards", a home mark
 * that is identity only, the export provenance in the sidebar's foot; the
 * dock's edit / save / export actions are already left out by the header
 * model's own `useIsStaticBundle` gating.
 *
 * `?chrome=base` (kept for the browser session, as on a server) still opts
 * into Classic. What a bundle does NOT follow is the reader's profile pick or
 * an instance default: neither exists in a file, and a pick stored in this
 * browser by another bundle (file:// pages share one origin) must not change
 * how this one looks.
 */
import { setChromeStyle } from 'depictio-react-core';

import { CHROME_VARIANTS, DEFAULT_CHROME } from '../chrome/variants/index';

export * from '../chrome/variants/index';

const SESSION_KEY = 'depictio-chrome-session';

function bundleChrome() {
  const byId = new Map(CHROME_VARIANTS.map((v) => [v.id, v]));
  const fromUrl = new URLSearchParams(window.location.search).get('chrome')?.toLowerCase();
  let id: string | null = null;
  try {
    if (fromUrl && byId.has(fromUrl)) {
      sessionStorage.setItem(SESSION_KEY, fromUrl);
      id = fromUrl;
    } else {
      const kept = sessionStorage.getItem(SESSION_KEY);
      id = kept && byId.has(kept) ? kept : null;
    }
  } catch {
    id = fromUrl && byId.has(fromUrl) ? fromUrl : null;
  }
  return (id && byId.get(id)) || DEFAULT_CHROME;
}

setChromeStyle(bundleChrome());

/** No profile pick and no instance default inside a bundle: nothing to follow. */
export function useChromeVariant(): void {}

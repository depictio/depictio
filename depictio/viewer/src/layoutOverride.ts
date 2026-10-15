/**
 * `?layout=` of this page: how linked view sections are drawn.
 *
 * A dashboard declares its linked tiles as `display: linked` (one screen
 * height). The reader can compare it with the plain grid on the same tab:
 * `?layout=classic` draws linked views as ordinary sections, and `?layout=yaml`
 * (or `default`) goes back to what the dashboard declares.
 *
 * Read like `?chrome=` (chrome/variants/index.ts) and kept for the browser
 * session, so the pick survives a tab switch that drops the query string.
 */
import { useEffect, useState } from 'react';
import type { LayoutOverride } from 'depictio-react-core';

const SESSION_KEY = 'depictio-layout-session';

function asOverride(value: string | null | undefined): LayoutOverride {
  return value === 'classic' ? value : null;
}

/** `?layout=` of this page, else the last one this browser session saw. */
export function readLayoutOverride(): LayoutOverride {
  const fromUrl = new URLSearchParams(window.location.search).get('layout')?.toLowerCase();
  try {
    const picked = asOverride(fromUrl);
    if (picked) {
      sessionStorage.setItem(SESSION_KEY, picked);
      return picked;
    }
    // An explicit way back to the dashboard's own layout.
    if (fromUrl === 'yaml' || fromUrl === 'default') {
      sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    return asOverride(sessionStorage.getItem(SESSION_KEY));
  } catch {
    // Storage blocked: the pick lasts for as long as the URL carries it.
    return asOverride(fromUrl);
  }
}

/** The reader's layout override, null when the dashboard's own applies. */
export function useLayoutOverride(): LayoutOverride {
  const [override, setOverride] = useState<LayoutOverride>(readLayoutOverride);
  useEffect(() => {
    // Back/forward can land on a URL with another `?layout=`.
    const reread = () => setOverride(readLayoutOverride());
    window.addEventListener('popstate', reread);
    return () => window.removeEventListener('popstate', reread);
  }, []);
  return override;
}

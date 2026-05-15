/**
 * Persistent toggle for the funnels (cross-tab pin-based filter narrowing)
 * feature. Stored in `localStorage` under `depictio.funnels.enabled` so the
 * user's choice survives reloads.
 *
 * Defaults to `false` (opt-in) per the project convention for unfinished /
 * experimental features — see the user feedback note about not surfacing
 * latent bugs in unprepared deploys. The Settings drawer exposes the
 * toggle so authors can flip it without touching the URL or storage.
 */

import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'depictio.funnels.enabled';
const STORAGE_EVENT = 'depictio:funnels-enabled-changed';

function read(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null) return false;
    return JSON.parse(raw) === true;
  } catch {
    return false;
  }
}

function write(value: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    // Same-tab listeners — the browser only fires `storage` for *other*
    // tabs, so we dispatch our own custom event to keep multiple hook
    // instances on this page in sync.
    window.dispatchEvent(new CustomEvent(STORAGE_EVENT, { detail: value }));
  } catch {
    // ignore quota / disabled storage
  }
}

/** Returns `[enabled, setEnabled]`. */
export function useFunnelsEnabled(): [boolean, (next: boolean) => void] {
  const [enabled, setEnabled] = useState<boolean>(() => read());

  useEffect(() => {
    const onChange = () => setEnabled(read());
    window.addEventListener(STORAGE_EVENT, onChange);
    window.addEventListener('storage', (e) => {
      if (e.key === STORAGE_KEY) onChange();
    });
    return () => {
      window.removeEventListener(STORAGE_EVENT, onChange);
    };
  }, []);

  const update = useCallback((next: boolean) => {
    write(next);
    setEnabled(next);
  }, []);

  return [enabled, update];
}

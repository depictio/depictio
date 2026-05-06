import { useCallback, useEffect } from 'react';
import { useMantineColorScheme } from '@mantine/core';

/**
 * Color scheme hook that stays in sync with the Dash app's `theme-store`
 * (a `dcc.Store(storage_type="local")`, which writes the JSON-encoded value to
 * `localStorage` under the same key — so the value is literally `'"light"'` or
 * `'"dark"'`). On mount we hydrate Mantine from that key; on toggle we write
 * back so the Dash app picks up the same setting on its next render.
 */

const STORAGE_KEY = 'theme-store';

type Scheme = 'light' | 'dark';

function readStoredScheme(): Scheme | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    // dcc.Store stores the value JSON-encoded. The Dash side stores the raw
    // string ("light" or "dark"), but historical/legacy values may also be an
    // object like `{ colorScheme: "dark" }`. Tolerate both.
    const parsed = JSON.parse(raw);
    if (parsed === 'light' || parsed === 'dark') return parsed;
    if (parsed && typeof parsed === 'object' && (parsed.colorScheme === 'light' || parsed.colorScheme === 'dark')) {
      return parsed.colorScheme;
    }
    return null;
  } catch {
    return null;
  }
}

function writeStoredScheme(scheme: Scheme): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(scheme));
  } catch {
    // ignore quota / disabled storage
  }
}

export function useColorScheme() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  // On mount, hydrate Mantine from localStorage if the stored scheme differs.
  useEffect(() => {
    const stored = readStoredScheme();
    if (stored && stored !== colorScheme) {
      setColorScheme(stored);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const apply = useCallback(
    (scheme: Scheme) => {
      setColorScheme(scheme);
      writeStoredScheme(scheme);
    },
    [setColorScheme],
  );

  const toggle = useCallback(() => {
    const next: Scheme = colorScheme === 'dark' ? 'light' : 'dark';
    apply(next);
  }, [colorScheme, apply]);

  // Resolve "auto" → "light" for downstream consumers that expect a binary value.
  const resolved: Scheme = colorScheme === 'dark' ? 'dark' : 'light';

  return {
    colorScheme: resolved,
    toggle,
    setColorScheme: apply,
  };
}

import {
  localStorageColorSchemeManager,
  type MantineColorSchemeManager,
} from '@mantine/core';

/**
 * Colour scheme handed down by a page that embeds depictio, for instance the
 * docs site framing a demo dashboard: its light/dark toggle should drive the
 * dashboard inside the iframe too.
 *
 * Two inputs, both optional:
 *  - `?theme=dark|light` (or `#theme=`) on the URL, read once at boot, so the
 *    first paint is already right;
 *  - `postMessage({ type: 'depictio:set-color-scheme', scheme })` from the
 *    parent frame, so a later toggle on the embedding page re-themes live.
 *
 * Either one makes the scheme *borrowed*: it is applied without being written
 * to the viewer's own stored preference (`theme-store` and Mantine's key), so
 * opening a `?theme=` link or visiting an embed never changes what the person
 * gets on a normal visit. Inside a frame the borrowed scheme is kept in
 * `sessionStorage`, because a tab switch is a full page load and the new page
 * no longer carries the query parameter.
 */

export type Scheme = 'light' | 'dark';

export const SET_COLOR_SCHEME_MESSAGE = 'depictio:set-color-scheme';

const SESSION_KEY = 'depictio.embed.colorScheme';

const isScheme = (value: unknown): value is Scheme => value === 'light' || value === 'dark';

const FRAMED = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
})();

function readUrlScheme(): Scheme | null {
  try {
    const fromQuery = new URLSearchParams(window.location.search).get('theme');
    if (isScheme(fromQuery)) return fromQuery;
    const fromHash = new URLSearchParams(window.location.hash.slice(1)).get('theme');
    return isScheme(fromHash) ? fromHash : null;
  } catch {
    return null;
  }
}

function readSessionScheme(): Scheme | null {
  try {
    const value = sessionStorage.getItem(SESSION_KEY);
    return isScheme(value) ? value : null;
  } catch {
    return null;
  }
}

function writeSessionScheme(scheme: Scheme): void {
  try {
    sessionStorage.setItem(SESSION_KEY, scheme);
  } catch {
    // ignore quota / disabled storage
  }
}

/** The borrowed scheme currently in force, or null on a normal visit. */
let borrowed: Scheme | null = (() => {
  const fromUrl = readUrlScheme();
  if (fromUrl) {
    if (FRAMED) writeSessionScheme(fromUrl);
    return fromUrl;
  }
  return FRAMED ? readSessionScheme() : null;
})();

/** The scheme to boot with when one was handed down, else null. */
export function getEmbedColorScheme(): Scheme | null {
  return borrowed;
}

/** Keeps a scheme chosen while borrowing (the embed's own toggle, a parent
 *  message) for the rest of the framed session, without persisting it. */
export function rememberEmbedColorScheme(scheme: Scheme): void {
  borrowed = scheme;
  if (FRAMED) writeSessionScheme(scheme);
}

/**
 * Mantine's localStorage manager, except that while a scheme is borrowed it
 * reads that scheme, never writes, and ignores cross-tab storage events. Its
 * `get` runs before the first paint, which is what keeps an embed from
 * flashing the stored scheme first.
 */
export function createColorSchemeManager(): MantineColorSchemeManager {
  const base = localStorageColorSchemeManager();
  return {
    ...base,
    get: (defaultValue) => borrowed ?? base.get(defaultValue),
    set: (value) => {
      if (!borrowed) base.set(value);
    },
    subscribe: (onUpdate) =>
      base.subscribe((value) => {
        if (!borrowed) onUpdate(value);
      }),
  };
}

const parentListeners = new Set<(scheme: Scheme) => void>();

// Listening from module load rather than from a mounted component: the embedding
// page posts on the iframe's `load` event, which can fire while the app is
// still bootstrapping its session. A message that lands before React mounts
// still updates `borrowed`, which the colour scheme manager reads at mount.
// Only the direct parent is heard, and only well-formed messages; the effect
// is cosmetic, so no origin allowlist is needed.
if (FRAMED) {
  window.addEventListener('message', (event: MessageEvent) => {
    if (event.source !== window.parent) return;
    const data: unknown = event.data;
    if (!data || typeof data !== 'object') return;
    const { type, scheme } = data as { type?: unknown; scheme?: unknown };
    if (type !== SET_COLOR_SCHEME_MESSAGE || !isScheme(scheme)) return;
    rememberEmbedColorScheme(scheme);
    parentListeners.forEach((listener) => listener(scheme));
  });
}

/** Calls `onScheme` whenever the parent frame asks for a scheme. Returns the
 *  cleanup. */
export function onParentColorScheme(onScheme: (scheme: Scheme) => void): () => void {
  parentListeners.add(onScheme);
  return () => {
    parentListeners.delete(onScheme);
  };
}

import React from 'react';
import {
  BASE_CHROME_STYLE,
  onPublicConfig,
  setChromeStyle,
  useChromeStyle,
} from 'depictio-react-core';
import type { ChromeStyle } from 'depictio-react-core';

import DefaultShell from '../shell/DefaultShell';
import type { DashboardShell } from '../shell/types';

import glass from './glass/glass';
import GlassShell from './glass/Shell';

/**
 * The app's chrome styles: Glass (the default) and Classic (`base`, the
 * original look).
 *
 * Which one draws, first match wins:
 *   1. `?chrome=<id>` in the URL, kept for the rest of the browser session so
 *      a tab switch (a full page load without the query) keeps it; for
 *      support and testing;
 *   2. the reader's pick in their profile, kept in this browser;
 *   3. the instance default an admin set in the Branding panel (it arrives
 *      with `/utils/public-config`, so the last one is cached here and a
 *      returning visitor paints it at once);
 *   4. Glass.
 */
export const CHROME_VARIANTS: ChromeStyle[] = [glass, BASE_CHROME_STYLE];

export const DEFAULT_CHROME = glass;

/** Styles that lay the whole page out their own way. */
const SHELLS: Record<string, DashboardShell> = {
  [glass.id]: GlassShell,
};

/** The page layout of the active chrome style. */
export function useDashboardShell(): DashboardShell {
  return SHELLS[useChromeStyle().id] ?? DefaultShell;
}

const BY_ID = new Map(CHROME_VARIANTS.map((v) => [v.id, v]));
const PREF_KEY = 'depictio-chrome-variant';
const PREF_EVENT = 'depictio:chrome-variant-pref';
const SESSION_KEY = 'depictio-chrome-session';
const INSTANCE_KEY = 'depictio-chrome-instance-default';

/** `?chrome=` of this page, or the last one this browser session saw. */
function sessionChromeVariant(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get('chrome')?.toLowerCase();
  try {
    if (fromUrl && BY_ID.has(fromUrl)) {
      sessionStorage.setItem(SESSION_KEY, fromUrl);
      return fromUrl;
    }
    const kept = sessionStorage.getItem(SESSION_KEY);
    return kept && BY_ID.has(kept) ? kept : null;
  } catch {
    return fromUrl && BY_ID.has(fromUrl) ? fromUrl : null;
  }
}

function readStored(key: string): string | null {
  try {
    const id = localStorage.getItem(key);
    return id && BY_ID.has(id) ? id : null;
  } catch {
    return null;
  }
}

/** The reader's own pick, or null when they follow the instance default. */
function readChromePref(): string | null {
  return readStored(PREF_KEY);
}

function readInstanceDefault(): string | null {
  return readStored(INSTANCE_KEY);
}

/** Keeps the reader's pick in this browser. A pick made in the profile also
 *  ends a `?chrome=` override, so the reader sees what they chose. */
export function writeChromePref(id: string): void {
  try {
    localStorage.setItem(PREF_KEY, id);
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Storage blocked: the pick lasts for this page only.
  }
  window.dispatchEvent(new Event(PREF_EVENT));
}

/** Drops the reader's pick, so the instance default applies again. */
export function clearChromePref(): void {
  try {
    localStorage.removeItem(PREF_KEY);
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Storage blocked: nothing was kept.
  }
  window.dispatchEvent(new Event(PREF_EVENT));
}

/** Remembers the instance default that `/utils/public-config` reported, and
 *  switches open pages to it unless the reader picked their own. `undefined`
 *  (a backend without the field) leaves the cache alone; `null` clears it. */
export function applyInstanceDefault(id: string | null | undefined): void {
  if (id === undefined) return;
  const next = id && BY_ID.has(id) ? id : null;
  if (next === readInstanceDefault()) return;
  try {
    if (next) localStorage.setItem(INSTANCE_KEY, next);
    else localStorage.removeItem(INSTANCE_KEY);
  } catch {
    // Storage blocked: the default applies to this page only.
  }
  window.dispatchEvent(new Event(PREF_EVENT));
}

function resolveChromeVariant(): ChromeStyle {
  const id = sessionChromeVariant() ?? readChromePref() ?? readInstanceDefault();
  return (id && BY_ID.get(id)) || DEFAULT_CHROME;
}

// Applied when the registry loads, before any app's first render, so a page
// never paints a frame of another style first.
setChromeStyle(resolveChromeVariant());

// The instance default is only known once public-config has loaded; this
// registers whether that is before or after this module.
onPublicConfig((config) => applyInstanceDefault(config.default_chrome));

/** The style a reader without a pick of their own gets. */
function instanceDefaultStyle(): ChromeStyle {
  const id = readInstanceDefault();
  return (id && BY_ID.get(id)) || DEFAULT_CHROME;
}

/** What the profile's Look control shows and changes: the reader's own pick
 *  (null = following the instance default) and the style that default is. */
export function useChromeChoice(): {
  pick: string | null;
  instanceDefault: ChromeStyle;
  choose: (id: string | null) => void;
} {
  const [, bump] = React.useReducer((n: number) => n + 1, 0);
  React.useEffect(() => {
    window.addEventListener(PREF_EVENT, bump);
    return () => window.removeEventListener(PREF_EVENT, bump);
  }, []);
  return {
    pick: readChromePref(),
    instanceDefault: instanceDefaultStyle(),
    choose: (id) => (id ? writeChromePref(id) : clearChromePref()),
  };
}

/** Applies the reader's chrome style, and follows the profile pick. */
export function useChromeVariant(): void {
  React.useEffect(() => {
    const apply = () => setChromeStyle(resolveChromeVariant());
    apply();
    window.addEventListener(PREF_EVENT, apply);
    return () => window.removeEventListener(PREF_EVENT, apply);
  }, []);
}

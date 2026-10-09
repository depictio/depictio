import React from 'react';
import { BASE_CHROME_STYLE, setChromeStyle, useChromeStyle } from 'depictio-react-core';
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
 *   2. the reader's pick in Settings > Your view, kept in this browser;
 *   3. Glass.
 */
export const CHROME_VARIANTS: ChromeStyle[] = [glass, BASE_CHROME_STYLE];

const DEFAULT_CHROME = glass;

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

function readChromePref(): string | null {
  try {
    return localStorage.getItem(PREF_KEY);
  } catch {
    return null;
  }
}

/** Keeps the reader's pick in this browser. A pick made in Settings also
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

function resolveChromeVariant(): ChromeStyle {
  const id = sessionChromeVariant() ?? readChromePref();
  return (id && BY_ID.get(id)) || DEFAULT_CHROME;
}

// Applied when the registry loads, before any app's first render, so a page
// never paints a frame of another style first.
setChromeStyle(resolveChromeVariant());

/** Applies the reader's chrome style, and follows the Settings pick. */
export function useChromeVariant(): void {
  React.useEffect(() => {
    const apply = () => setChromeStyle(resolveChromeVariant());
    apply();
    window.addEventListener(PREF_EVENT, apply);
    return () => window.removeEventListener(PREF_EVENT, apply);
  }, []);
}

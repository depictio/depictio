import { useCallback, useEffect, useState } from 'react';

/**
 * Page-width preference for the dashboard canvas, like Notion's "full width"
 * or Obsidian's readable line length. With the sidebar and the filter panel
 * collapsed on a wide screen, a full-bleed grid stretches cards and prose
 * past what reads comfortably; this caps the canvas and centres it.
 *
 * Per browser, like the font size and the colour scheme: it is about the
 * screen in front of the reader, not about the dashboard.
 */

export type ContentWidth = 'full' | 'wide' | 'comfortable';

export const CONTENT_WIDTHS: { value: ContentWidth; label: string; maxPx: number | null }[] = [
  { value: 'full', label: 'Full', maxPx: null },
  { value: 'wide', label: 'Wide', maxPx: 1600 },
  { value: 'comfortable', label: 'Comfortable', maxPx: 1240 },
];

const STORAGE_KEY = 'depictio-content-width';

type Listener = (width: ContentWidth) => void;
const listeners = new Set<Listener>();

function isWidth(value: unknown): value is ContentWidth {
  return CONTENT_WIDTHS.some((w) => w.value === value);
}

/**
 * The tab the preference applies to, and the width its author asked for
 * (`content_width_default`). Set by the app when a tab mounts; the header
 * toggle and the settings drawer read and write through it without needing
 * the dashboard themselves.
 *
 * The viewer's choice is remembered per tab, like the filter panel's: an
 * author who opens a landing page at a reading width should not have that
 * undone by a width the viewer picked for a wide heatmap tab.
 */
let scope: { id: string | null; fallback: ContentWidth } = { id: null, fallback: 'full' };

function storageKey(): string {
  return scope.id ? `${STORAGE_KEY}:${scope.id}` : STORAGE_KEY;
}

export function readStoredContentWidth(): ContentWidth {
  try {
    const raw = localStorage.getItem(storageKey());
    return isWidth(raw) ? raw : scope.fallback;
  } catch {
    return scope.fallback;
  }
}

function notify(): void {
  const width = readStoredContentWidth();
  listeners.forEach((fn) => fn(width));
  // The grid, Plotly and AG Grid size to their container; a width change
  // moves it without a window resize, so fire the established reflow signal.
  window.dispatchEvent(new Event('resize'));
}

/** Points the preference at a tab and its author's default. */
export function setContentWidthScope(id: string | null, fallback: unknown): void {
  const next = { id, fallback: isWidth(fallback) ? fallback : 'full' };
  if (next.id === scope.id && next.fallback === scope.fallback) return;
  scope = next;
  notify();
}

function broadcast(width: ContentWidth): void {
  try {
    localStorage.setItem(storageKey(), width);
  } catch {
    // storage unavailable: the choice lasts for this page only
  }
  notify();
}

export function useContentWidthPref() {
  const [width, setWidth] = useState<ContentWidth>(readStoredContentWidth);

  useEffect(() => {
    const listener: Listener = (next) => setWidth(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const set = useCallback((next: ContentWidth) => broadcast(next), []);
  const cycle = useCallback(() => {
    const idx = CONTENT_WIDTHS.findIndex((w) => w.value === readStoredContentWidth());
    broadcast(CONTENT_WIDTHS[(idx + 1) % CONTENT_WIDTHS.length].value);
  }, []);

  return { width, set, cycle };
}

/**
 * The content width cap in px for the chosen preference, or null for full
 * width. The canvas centres within the room the filter panel leaves, so
 * the panel (open or as its rail) stays docked by the sidebar.
 */
export function useContentMaxWidth(): number | null {
  const { width } = useContentWidthPref();
  return CONTENT_WIDTHS.find((w) => w.value === width)?.maxPx ?? null;
}

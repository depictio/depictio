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

export function readStoredContentWidth(): ContentWidth {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return isWidth(raw) ? raw : 'full';
  } catch {
    return 'full';
  }
}

function broadcast(width: ContentWidth): void {
  try {
    localStorage.setItem(STORAGE_KEY, width);
  } catch {
    // storage unavailable: the choice lasts for this page only
  }
  listeners.forEach((fn) => fn(width));
  // The grid, Plotly and AG Grid size to their container; a width change
  // moves it without a window resize, so fire the established reflow signal.
  window.dispatchEvent(new Event('resize'));
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
 * width. Applied to the filter panel and the canvas together, so an open
 * panel stays beside the content it filters instead of being stranded at the
 * window edge while the canvas centres.
 */
export function useContentMaxWidth(): number | null {
  const { width } = useContentWidthPref();
  return CONTENT_WIDTHS.find((w) => w.value === width)?.maxPx ?? null;
}

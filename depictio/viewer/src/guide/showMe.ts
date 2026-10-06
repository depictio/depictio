/**
 * "Show me": point at the real element a Guide part is about.
 *
 * Deliberately not the walkthrough: no overlay, no step sequence, nothing to
 * dismiss. The Guide closes, the page is back, and the element gets a pulsing
 * ring for about two seconds, then the ring goes away on its own.
 *
 * The ring is a separate fixed element on <body> rather than a style on the
 * target: most targets sit inside a scroll container or an `overflow: hidden`
 * tile that would clip an outline, and a ring we own cannot disturb the
 * target's own styles. It follows the target for its lifetime, so a smooth
 * scroll into view or a sidebar sliding open carries the ring with it.
 */

export type GuideTarget =
  | 'tabs'
  | 'sections'
  | 'filters'
  | 'selection'
  | 'pinned'
  | 'actions'
  | 'analysis'
  | 'settings';

/** The tab's canvas: the scroll container every tile lives in. */
const CONTENT = '[data-testid="dashboard-content"]';

const RING_MS = 2200;
const RING_PAD = 4;

function hasBox(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

/** On screen horizontally: the header's right end is cut off on a phone. */
function inViewportX(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return hasBox(el) && r.left >= 0 && r.right <= window.innerWidth + 1;
}

function first(selector: string, accept: (el: Element) => boolean = hasBox): HTMLElement | null {
  for (const el of document.querySelectorAll<HTMLElement>(selector)) {
    if (accept(el)) return el;
  }
  return null;
}

/** A section's header row: the part that folds it, and that says "Filtered".
 *  The whole item can be taller than the screen, which no ring reads well on. */
function sectionHeader(item: HTMLElement | null): HTMLElement | null {
  return item ? (item.querySelector<HTMLElement>(':scope > *') ?? item) : null;
}

/**
 * The tile whose action row is worth pointing at: the first one in view with
 * more than one action (a card carries only its metadata icon), else the first
 * tile with any.
 */
function pickActionRow(): { row: HTMLElement; chrome: HTMLElement } | null {
  const content = document.querySelector(CONTENT);
  if (!content) return null;
  const view = content.getBoundingClientRect();
  let fallback: { row: HTMLElement; chrome: HTMLElement } | null = null;
  for (const chrome of content.querySelectorAll<HTMLElement>('.depictio-component-chrome')) {
    const row = chrome.querySelector<HTMLElement>(':scope > .depictio-component-actions');
    if (!row || row.children.length === 0 || !hasBox(chrome)) continue;
    fallback ??= { row, chrome };
    const r = chrome.getBoundingClientRect();
    const inView = r.top >= view.top && r.top < view.bottom - 80;
    if (inView && row.children.length > 1) return { row, chrome };
  }
  return fallback;
}

export interface ShowMeOptions {
  /** Component ids a selection can be made on, most relevant first. */
  selectionIds?: readonly string[];
}

/** The element `target` points at on the page now, or null when it has none. */
export function findGuideTarget(
  target: GuideTarget,
  opts: ShowMeOptions = {},
): HTMLElement | null {
  switch (target) {
    case 'tabs':
      // No size check: a collapsed sidebar still holds the list, and showing
      // it opens the sidebar first (see `useGuideShowMe`).
      return document.querySelector<HTMLElement>('[data-guide-target="tabs"]');
    case 'sections':
      return sectionHeader(first(`${CONTENT} .depictio-section-item:not(.is-plain)`));
    case 'filters':
      // The panel on a wide screen (open or folded to its rail); on a phone it
      // lives in a drawer, opened from the header's Filters button.
      return first('[data-tour-id="filter-panel"]') ?? first('[data-guide-target="filters-button"]');
    case 'selection': {
      for (const id of opts.selectionIds ?? []) {
        const el = first(`${CONTENT} [data-component-id="${CSS.escape(id)}"]`);
        if (el) return el;
      }
      // Then the map panel: floating, docked in the filter panel, or folded
      // away behind its control.
      return (
        first('[data-testid="map-panel-surface"]') ??
        first('[data-testid="map-panel-dock"]') ??
        first('[data-testid="map-panel-control"]', inViewportX)
      );
    }
    case 'pinned':
      return sectionHeader(first('[data-guide-target="pinned-sections"] .depictio-section-item'));
    case 'actions':
      return pickActionRow()?.row ?? null;
    case 'analysis':
      return first('[data-guide-target="analysis"]', inViewportX);
    case 'settings':
      return first('[data-guide-target="settings"]', inViewportX);
  }
}

let active: (() => void) | null = null;

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/**
 * Ring `el` for a couple of seconds. `reveal` gets a class for the same time —
 * the tile chrome uses it to keep its hover-only action row on screen.
 */
export function ringElement(
  el: HTMLElement,
  opts: { reveal?: HTMLElement | null; scroll?: ScrollLogicalPosition } = {},
): void {
  active?.();
  const reduced = prefersReducedMotion();
  // The ring takes the colour of the element's own scope: the dashboard's
  // primary under a brand, the app's otherwise.
  const color =
    getComputedStyle(el).getPropertyValue('--mantine-primary-color-filled').trim() ||
    'var(--mantine-primary-color-filled)';

  // Centring something taller than the screen would scroll its top away.
  const tall = el.getBoundingClientRect().height > window.innerHeight * 0.6;
  el.scrollIntoView({
    block: tall ? 'start' : (opts.scroll ?? 'nearest'),
    inline: 'nearest',
    behavior: reduced ? 'auto' : 'smooth',
  });
  opts.reveal?.classList.add('depictio-guide-reveal');

  const ring = document.createElement('div');
  ring.className = 'depictio-guide-ring';
  ring.setAttribute('aria-hidden', 'true');
  ring.style.setProperty('--depictio-guide-ring', color);
  document.body.appendChild(ring);

  const place = () => {
    const r = el.getBoundingClientRect();
    ring.style.left = `${r.left - RING_PAD}px`;
    ring.style.top = `${r.top - RING_PAD}px`;
    ring.style.width = `${r.width + RING_PAD * 2}px`;
    ring.style.height = `${r.height + RING_PAD * 2}px`;
  };

  let frame = 0;
  let fade = 0;
  const start = performance.now();
  const cleanup = () => {
    cancelAnimationFrame(frame);
    window.clearTimeout(fade);
    ring.remove();
    opts.reveal?.classList.remove('depictio-guide-reveal');
    if (active === cleanup) active = null;
  };
  const tick = (now: number) => {
    place();
    if (now - start < RING_MS) {
      frame = requestAnimationFrame(tick);
    } else {
      ring.classList.add('is-leaving');
      fade = window.setTimeout(cleanup, 300);
    }
  };
  place();
  frame = requestAnimationFrame(tick);
  active = cleanup;
}

/** Find `target` and ring it. False when the page has nothing to show. */
export function showGuideTarget(target: GuideTarget, opts: ShowMeOptions = {}): boolean {
  if (target === 'actions') {
    const picked = pickActionRow();
    if (!picked) return false;
    ringElement(picked.row, { reveal: picked.chrome, scroll: 'center' });
    return true;
  }
  const el = findGuideTarget(target, opts);
  if (!el) return false;
  const inCanvas = Boolean(el.closest(CONTENT));
  ringElement(el, { scroll: inCanvas ? 'center' : 'nearest' });
  return true;
}

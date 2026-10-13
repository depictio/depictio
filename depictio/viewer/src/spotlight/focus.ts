import { requestRevealComponent } from 'depictio-react-core';

import { prefersReducedMotion, ringElements } from '../guide/showMe';
// The ring's own styles: both apps load them with the Guide already, but the
// ring drawn here should not depend on that.
import '../guide/guide.css';

/**
 * Landing on a component: find it on the page, open whatever folds it away,
 * scroll it into view and flash a ring round it.
 *
 * The component may not be on the page yet. A tab reached from the search is a
 * fresh page load still fetching its dashboard; a folded section mounts its
 * tiles a render after it opens. So the lookup polls, asking the page to reveal
 * the component (`requestRevealComponent`, answered by the grid's sections, the
 * filter panel and the sections pinned from sibling tabs) until it shows or
 * the wait runs out.
 */

/** How long the ring stays: long enough to catch the eye after a scroll,
 *  short enough to be gone before the reader starts on the tile. */
const RING_MS = 1500;
/** Between two looks for the component, and two reveal requests. */
const POLL_MS = 120;
/** The longest a smooth scroll is waited for before the ring goes up anyway. */
const SETTLE_MAX_MS = 1200;

/** The query parameter a link to another tab carries its component in. */
export const COMPONENT_PARAM = 'component';

function isShown(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  // The canvas under the open Guide is kept mounted but hidden, and marked so.
  if (el.closest('[aria-hidden="true"]')) return false;
  return getComputedStyle(el).visibility !== 'hidden';
}

/**
 * The element that shows component `index`, or null while there is none on
 * screen. The chrome wrapper marks every drawn component; the grid cell and
 * the filter-panel slot mark theirs too, which covers a tile whose chrome is
 * still behind its viewport gate. A grid tile answers as the whole tile.
 */
export function findComponentElement(index: string): HTMLElement | null {
  const id = CSS.escape(index);
  const candidates = document.querySelectorAll<HTMLElement>(
    `[data-component-index="${id}"], [data-component-id="${id}"]`,
  );
  for (const el of candidates) {
    if (isShown(el)) return el.closest<HTMLElement>('.react-grid-item') ?? el;
  }
  return null;
}

const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
const nextFrame = () => new Promise<number>((resolve) => requestAnimationFrame(resolve));

/** The element's nearest scrolling ancestor: the canvas, a panel, a drawer. */
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const { overflowY } = getComputedStyle(p);
    if ((overflowY === 'auto' || overflowY === 'scroll') && p.scrollHeight > p.clientHeight) {
      return p;
    }
  }
  return null;
}

/**
 * Where the element is and how much of it its folding ancestors let through,
 * as one comparable string. A section that has just been asked to open grows
 * from nothing over its transition: until it is done, the tile inside is cut
 * off by the panel, the page is not yet long enough to scroll it into view,
 * and a scroll started then stops short.
 */
function layoutKey(el: HTMLElement, scroller: HTMLElement | null): string {
  const r = el.getBoundingClientRect();
  let top = r.top;
  let bottom = r.bottom;
  for (let p = el.parentElement; p && p !== scroller; p = p.parentElement) {
    const style = getComputedStyle(p);
    if (style.overflowY === 'visible' || style.overflowY === 'auto' || style.overflowY === 'scroll') {
      continue;
    }
    const clip = p.getBoundingClientRect();
    top = Math.max(top, clip.top);
    bottom = Math.min(bottom, clip.bottom);
  }
  return [r.top, r.height, Math.max(0, bottom - top), scroller?.scrollHeight ?? 0]
    .map(Math.round)
    .join(':');
}

/** Resolves once nothing about `el`'s place has changed for a few frames: a
 *  fold has finished opening, or a smooth scroll has landed. */
async function settled(el: HTMLElement): Promise<void> {
  const until = performance.now() + SETTLE_MAX_MS;
  const scroller = scrollParent(el);
  let last = layoutKey(el, scroller);
  let still = 0;
  while (performance.now() < until && still < 3) {
    await nextFrame();
    const key = layoutKey(el, scroller);
    still = key === last ? still + 1 : 0;
    last = key;
  }
}

function scrollToElement(el: HTMLElement): void {
  // Centring something taller than the screen would scroll its top away.
  const tall = el.getBoundingClientRect().height > window.innerHeight * 0.6;
  el.scrollIntoView({
    block: tall ? 'start' : 'center',
    inline: 'nearest',
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
  });
}

/** Whether the element's top edge is on screen, inside its scroller. */
function topInView(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  const scroller = scrollParent(el);
  const box = scroller?.getBoundingClientRect() ?? { top: 0, bottom: window.innerHeight };
  return r.top >= box.top - 1 && r.top < box.bottom - 24;
}

/**
 * Bring component `index` into view and ring it. Resolves to whether it was
 * found within `timeoutMs`.
 */
export async function focusComponent(
  index: string,
  { timeoutMs = 8000 }: { timeoutMs?: number } = {},
): Promise<boolean> {
  const deadline = performance.now() + timeoutMs;
  let el = findComponentElement(index);
  while (!el) {
    if (performance.now() > deadline) return false;
    requestRevealComponent(index);
    await wait(POLL_MS);
    el = findComponentElement(index);
  }
  // Let a fold that has just opened finish growing, then scroll.
  await settled(el);
  scrollToElement(el);
  await settled(el);
  // A tile above it that sized itself to its content meanwhile (a text tile,
  // a card) can push it back down: one more pass corrects for that.
  if (!topInView(el)) {
    scrollToElement(el);
    await settled(el);
  }
  ringElements([el], { scroll: false, durationMs: RING_MS, className: 'is-spotlight' });
  return true;
}

/** `href` with the component to land on, for a link to another tab. */
export function hrefWithComponent(href: string, index: string): string {
  const url = new URL(href, window.location.origin);
  url.searchParams.set(COMPONENT_PARAM, index);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * The component the address bar asks to land on, taken out of it: the page
 * lands once, and a reload or a copied link afterwards opens the tab as usual.
 */
export function takeComponentParam(): string | null {
  const url = new URL(window.location.href);
  const index = url.searchParams.get(COMPONENT_PARAM);
  if (!index) return null;
  url.searchParams.delete(COMPONENT_PARAM);
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  return index;
}

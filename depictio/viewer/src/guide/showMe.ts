/**
 * "Show me": point at the part of a Guide demo that its explanation is about.
 *
 * Inside the Guide only. The ring lands on the demo under the button — the
 * tab you are on, the header that folds a section, the filter to pick from,
 * a tile's hover-only actions, the step to take next — so the reader never
 * leaves the page to look for it, and nothing on the dashboard behind is
 * touched. No overlay, no step sequence, nothing to dismiss: the element gets
 * a pulsing ring for about two seconds, then the ring goes away on its own.
 *
 * The ring is a separate fixed element on <body> rather than a style on the
 * target: most targets sit inside a tile with `overflow: hidden` that would
 * clip an outline, and a ring we own cannot disturb the target's own styles.
 * It follows the target for its lifetime, so a smooth scroll into view
 * carries the ring with it.
 */

export type GuideTarget = 'tabs' | 'sections' | 'filters' | 'actions' | 'analysis' | 'settings';

const RING_MS = 2200;
const RING_PAD = 4;

function hasBox(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function first(root: ParentNode, selector: string): HTMLElement | null {
  for (const el of root.querySelectorAll<HTMLElement>(selector)) {
    if (hasBox(el)) return el;
  }
  return null;
}

/** A section's header row: the part that folds it. The whole item can be
 *  taller than the screen, which no ring reads well on. */
function sectionHeader(item: HTMLElement | null): HTMLElement | null {
  return item ? (item.querySelector<HTMLElement>(':scope > *') ?? item) : null;
}

/** The demo tile's action row: the first one with any action. */
function actionRow(root: ParentNode): { row: HTMLElement; chrome: HTMLElement } | null {
  for (const chrome of root.querySelectorAll<HTMLElement>('.depictio-component-chrome')) {
    const row = chrome.querySelector<HTMLElement>(':scope > .depictio-component-actions');
    if (row && row.children.length > 0 && hasBox(chrome)) return { row, chrome };
  }
  return null;
}

/**
 * The elements `target` points at in `demo`, the demo of the Guide part that
 * offers it; empty while the demo has none (it may still be loading).
 */
export function findDemoTargets(target: GuideTarget, demo: ParentNode): HTMLElement[] {
  const one = (el: HTMLElement | null) => (el ? [el] : []);
  switch (target) {
    case 'tabs':
      return one(first(demo, '[aria-current="page"]'));
    case 'sections':
      // A folding section first: a heading-only one has nothing to click.
      return one(
        sectionHeader(
          first(demo, '.depictio-section-item:not(.is-plain)') ??
            first(demo, '.depictio-section-item'),
        ),
      );
    case 'filters':
      return one(first(demo, '[data-testid="guide-filter-demo-control"]'));
    case 'actions':
      return one(actionRow(demo)?.row ?? null);
    case 'analysis':
      // The step to take now, which the demo lights.
      return one(first(demo, '[data-testid^="guide-analysis-step-"][data-active]'));
    case 'settings':
      return [...demo.querySelectorAll<HTMLElement>('[data-guide-show]')].filter(hasBox);
  }
}

let active: (() => void) | null = null;

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

/**
 * Ring `els` for a couple of seconds, scrolling the first into view (unless
 * `scroll` is false: a ring that answers a hover must not move the page under
 * the pointer). `reveal` gets a class for the same time — the tile chrome uses
 * it to keep its hover-only action row on screen.
 */
export function ringElements(
  els: HTMLElement[],
  opts: { reveal?: HTMLElement | null; scroll?: ScrollLogicalPosition | false } = {},
): void {
  active?.();
  if (els.length === 0) return;
  const reduced = prefersReducedMotion();
  const lead = els[0];

  if (opts.scroll !== false) {
    // Centring something taller than the screen would scroll its top away.
    const tall = lead.getBoundingClientRect().height > window.innerHeight * 0.6;
    lead.scrollIntoView({
      block: tall ? 'start' : (opts.scroll ?? 'nearest'),
      inline: 'nearest',
      behavior: reduced ? 'auto' : 'smooth',
    });
  }
  opts.reveal?.classList.add('depictio-guide-reveal');

  const rings = els.map((el) => {
    const ring = document.createElement('div');
    ring.className = 'depictio-guide-ring';
    ring.setAttribute('aria-hidden', 'true');
    // The ring takes the colour of the element's own scope: the dashboard's
    // primary under a brand, the app's otherwise.
    const color =
      getComputedStyle(el).getPropertyValue('--mantine-primary-color-filled').trim() ||
      'var(--mantine-primary-color-filled)';
    ring.style.setProperty('--depictio-guide-ring', color);
    document.body.appendChild(ring);
    return { el, ring };
  });

  const place = () => {
    for (const { el, ring } of rings) {
      const r = el.getBoundingClientRect();
      ring.style.left = `${r.left - RING_PAD}px`;
      ring.style.top = `${r.top - RING_PAD}px`;
      ring.style.width = `${r.width + RING_PAD * 2}px`;
      ring.style.height = `${r.height + RING_PAD * 2}px`;
    }
  };

  let frame = 0;
  let fade = 0;
  const start = performance.now();
  const cleanup = () => {
    cancelAnimationFrame(frame);
    window.clearTimeout(fade);
    for (const { ring } of rings) ring.remove();
    opts.reveal?.classList.remove('depictio-guide-reveal');
    if (active === cleanup) active = null;
  };
  const tick = (now: number) => {
    place();
    if (now - start < RING_MS) {
      frame = requestAnimationFrame(tick);
    } else {
      for (const { ring } of rings) ring.classList.add('is-leaving');
      fade = window.setTimeout(cleanup, 300);
    }
  };
  place();
  frame = requestAnimationFrame(tick);
  active = cleanup;
}

/** Find `target` in `demo` and ring it. False when the demo has nothing to show. */
export function showDemoTarget(target: GuideTarget, demo: ParentNode): boolean {
  const els = findDemoTargets(target, demo);
  if (els.length === 0) return false;
  // A tile's actions only show on hover: keep them on screen while ringed.
  const reveal = target === 'actions' ? els[0].closest<HTMLElement>('.depictio-component-chrome') : null;
  ringElements(els, { reveal, scroll: 'nearest' });
  return true;
}

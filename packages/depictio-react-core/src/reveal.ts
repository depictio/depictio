import { useEffect, useRef } from 'react';

/**
 * "Bring this component into view": a request, sent to whatever draws a
 * component, to make it visible — unfold the section it sits in, open its
 * filter group, expand the filter panel it lives on.
 *
 * An event on `window` rather than a prop threaded through the layout: the
 * request comes from the dashboard search in the app's chrome, and what has to
 * act on it sits several levels down in this package (the grid's sections, the
 * filter panel, the sections pinned from sibling tabs). Each surface answers
 * for the components it draws and ignores the rest, so the one asking never
 * needs to know where a component lives, and a surface added later only has
 * to listen.
 *
 * Opening is all a surface does. Scrolling to the component and pointing at it
 * is the requester's job, once the component is on the page. Answering twice
 * must be harmless: the requester repeats the request until the component
 * shows up, since a section that has never been opened mounts its tiles a
 * render after it opens.
 */
export const REVEAL_COMPONENT_EVENT = 'depictio:reveal-component';

export interface RevealComponentDetail {
  /** The component's `index`. */
  index: string;
}

/** Ask every surface on the page to bring component `index` into view. */
export function requestRevealComponent(index: string): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent<RevealComponentDetail>(REVEAL_COMPONENT_EVENT, { detail: { index } }),
  );
}

/**
 * Answer reveal requests for the components this surface draws. `onReveal` is
 * called with every requested index; it opens whatever hides that component
 * and does nothing for one it does not draw.
 */
export function useRevealComponent(onReveal: (index: string) => void): void {
  // The latest handler, so the listener is attached once rather than on every
  // render of the grid or panel that owns it.
  const handlerRef = useRef(onReveal);
  handlerRef.current = onReveal;
  useEffect(() => {
    const listener = (event: Event) => {
      const index = (event as CustomEvent<RevealComponentDetail>).detail?.index;
      if (typeof index === 'string' && index) handlerRef.current(index);
    };
    window.addEventListener(REVEAL_COMPONENT_EVENT, listener);
    return () => window.removeEventListener(REVEAL_COMPONENT_EVENT, listener);
  }, []);
}

/**
 * The same request for a whole section, by its name: a text tile's
 * `[label](section:Sample sheet)` link. Names compare without case or outer
 * spaces, as authors write them.
 */
export const REVEAL_SECTION_EVENT = 'depictio:reveal-section';

export const sameSectionName = (a: string | null | undefined, b: string): boolean =>
  typeof a === 'string' && a.trim().toLowerCase() === b.trim().toLowerCase();

/** Answer section requests: `onReveal` unfolds the named section if it draws one. */
export function useRevealSection(onReveal: (name: string) => void): void {
  const handlerRef = useRef(onReveal);
  handlerRef.current = onReveal;
  useEffect(() => {
    const listener = (event: Event) => {
      const name = (event as CustomEvent<{ name: string }>).detail?.name;
      if (typeof name === 'string' && name.trim()) handlerRef.current(name);
    };
    window.addEventListener(REVEAL_SECTION_EVENT, listener);
    return () => window.removeEventListener(REVEAL_SECTION_EVENT, listener);
  }, []);
}

/**
 * Unfold section `name` wherever it is drawn (the tab's grid, or the sections
 * pinned from a sibling tab) and scroll to its top. Resolves to whether it was
 * found on the page.
 */
export async function revealSection(name: string): Promise<boolean> {
  if (typeof window === 'undefined') return false;
  window.dispatchEvent(new CustomEvent(REVEAL_SECTION_EVENT, { detail: { name } }));
  const find = () =>
    Array.from(document.querySelectorAll<HTMLElement>('[data-section-name]')).find((el) =>
      sameSectionName(el.dataset.sectionName, name),
    );
  // A fold that has just opened mounts its tiles a render later, and they grow
  // as their data lands: scroll once the section has held its height for a quarter second
  // (at most 1.5 s), or the page is still too short to bring it up.
  const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));
  await frame();
  const el = find();
  if (!el) return false;
  const until = performance.now() + 1500;
  let last = el.offsetHeight;
  let still = 0;
  while (performance.now() < until && still < 15) {
    await frame();
    still = el.offsetHeight === last ? still + 1 : 0;
    last = el.offsetHeight;
  }
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' });
  return true;
}

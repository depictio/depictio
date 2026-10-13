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

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Whether a scrolling list has more content above or below its visible part.
 *
 * The sidebar's tab list hides its scrollbar (it only draws on hover, or never),
 * so a family with more tabs than fit looked complete: nothing told a reader the
 * list went on. This hook gives the two flags a fade and a chevron at the edge
 * that has more, and a `scrollBy` that pages the list.
 *
 * The list grows after the first paint (pills, icons and fonts land late) and
 * again when a group opens or the window is resized, so it watches the viewport
 * and its content rather than measuring once. `deps` re-arms the watch when the
 * content element is replaced.
 */
export function useScrollOverflow<T extends HTMLElement>(deps: readonly unknown[] = []) {
  const ref = useRef<T>(null);
  const [above, setAbove] = useState(false);
  const [below, setBelow] = useState(false);

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setAbove(el.scrollTop > 1);
    setBelow(el.scrollHeight - el.clientHeight - el.scrollTop > 1);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    el.addEventListener('scroll', measure, { passive: true });
    return () => {
      observer.disconnect();
      el.removeEventListener('scroll', measure);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measure, ...deps]);

  const scrollBy = useCallback((direction: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    el.scrollBy({ top: direction * el.clientHeight * 0.6, behavior: 'smooth' });
  }, []);

  return { ref, above, below, measure, scrollBy };
}

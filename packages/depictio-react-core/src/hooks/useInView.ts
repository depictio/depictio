import { useEffect, useRef, useState } from 'react';

/**
 * Once-only IntersectionObserver: flips to `true` the first time the ref'd
 * element enters the viewport (within `rootMargin`), then stops observing.
 *
 * Used to defer expensive work — fetching figure JSON, mounting Plotly —
 * until a component is actually visible. Plotly.newPlot is synchronous and
 * blocks the main thread for ~200–500ms per figure; with N off-screen plots
 * all firing on dashboard mount the cumulative block swallows clicks. Gating
 * on visibility means only on-screen figures contend for the main thread.
 *
 * `rootMargin` lets us pre-warm just before scroll arrives — '200px' is a
 * sensible default for above-the-fold panels.
 */

/** How long to wait before the fallback rect probe runs. Long enough for
 *  react-grid-layout to measure its container and position the panels (it does
 *  so within the first frames), short enough that a throttled-observer
 *  environment isn't left staring at loaders. */
const PROBE_DELAY_MS = 400;
export function useInView<T extends Element>(
  rootMargin: string = '200px',
): [React.MutableRefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    if (inView) return;
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return;
    }

    // The observer is the authority. It is attached first and left to fire on
    // its own schedule, which is *after* layout — so it sees where the panel
    // actually ended up.
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          obs.disconnect();
        }
      },
      { rootMargin },
    );
    obs.observe(node);

    // Safety net for environments (background tabs, embedded iframes, headless
    // automation) that throttle IntersectionObserver so the initial entry never
    // fires, leaving the panel stuck in its loader.
    //
    // Deliberately deferred rather than synchronous: react-grid-layout has to
    // measure the container before it can position anything, so on the first
    // commit every panel still sits at the grid origin and a rect probe there
    // reports the whole dashboard as on-screen. That flipped ~20 of 30 panels
    // in-view at once, defeating the deferral this hook exists for and inflating
    // the load indicator's denominator to near the full component count.
    const probe = () => {
      const el = ref.current;
      if (!el) return;
      const margin = parseInt(rootMargin, 10) || 0;
      const rect = el.getBoundingClientRect();
      // An element with no area is not on screen, whatever its coordinates say.
      // A collapsed container (`height: 0` + `overflow: hidden`, which is what
      // Mantine's Collapse and Accordion.Panel render) gives its children a
      // zero-height rect parked at the container's own y — inside the viewport
      // by every test below, so the probe declared them visible and started
      // their fetch. The observer, which measures actual intersection, is left
      // attached and still fires if the element is later revealed.
      if (rect.width === 0 && rect.height === 0) return;
      if (
        rect.bottom > -margin &&
        rect.top < window.innerHeight + margin &&
        rect.right > -margin &&
        rect.left < window.innerWidth + margin
      ) {
        setInView(true);
        obs.disconnect();
      }
    };
    const timer = window.setTimeout(probe, PROBE_DELAY_MS);

    return () => {
      obs.disconnect();
      window.clearTimeout(timer);
    };
  }, [inView, rootMargin]);

  return [ref, inView];
}

export default useInView;

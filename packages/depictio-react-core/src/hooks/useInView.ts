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
    return () => obs.disconnect();
  }, [inView, rootMargin]);

  return [ref, inView];
}

export default useInView;

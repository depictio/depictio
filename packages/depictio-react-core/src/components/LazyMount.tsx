import React, { Suspense } from 'react';

import { useInView } from '../hooks/useInView';
import ComponentSkeleton, { SkeletonVariant } from './ComponentSkeleton';

/** Full-cell skeleton — the placeholder shown both while the component is
 *  off-screen and while its lazy chunk is loading (also used as the `Suspense`
 *  fallback for the renderers ComponentRenderer lazy-loads without a viewport
 *  gate). A skeleton (not a spinner) so the deferred → chunk-loading →
 *  renderer-mounted → data-loaded sequence shows one continuous shimmer instead
 *  of a spinner that then swaps to the renderer's own skeleton. */
export const CellPlaceholder: React.FC<{ variant?: SkeletonVariant }> = ({ variant = 'block' }) => (
  <div style={{ display: 'flex', height: '100%', width: '100%' }}>
    <ComponentSkeleton variant={variant} />
  </div>
);

interface LazyMountProps {
  /** Pre-warm distance before the element scrolls into view. */
  rootMargin?: string;
  children: React.ReactNode;
}

/**
 * Viewport gate + Suspense boundary in one wrapper.
 *
 * Renders only a placeholder until the element scrolls within `rootMargin` of
 * the viewport (via the once-only `useInView`), then mounts `children` inside a
 * `Suspense` so a lazily-imported renderer can stream in its chunk.
 *
 * Used for the component branches whose renderer fires a data fetch on mount
 * (advanced_viz, jbrowse). Without the gate, a 25–30 component dashboard mounts
 * every one of them at once and each fetch enqueues immediately — including for
 * components far below the fold the user may never scroll to. Deferring the
 * mount defers both the chunk load and the fetch until the component is nearly
 * visible.
 *
 * `inView` flips exactly once and then stays true (the observer disconnects), so
 * the subtree mounts a single time — no remount churn that could re-trigger a
 * child's render loop.
 */
const LazyMount: React.FC<LazyMountProps> = ({ rootMargin = '200px', children }) => {
  const [ref, inView] = useInView<HTMLDivElement>(rootMargin);
  return (
    // `depictio-fill` so that when this div is the direct child of
    // `.depictio-component-chrome` (the multiqc branch wraps chrome *around*
    // LazyMount) the chrome flex chain still matches it — otherwise the cell
    // sizes only by the inline height:100% resolving against a definite parent.
    <div
      ref={ref}
      className="depictio-fill"
      style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}
    >
      {inView ? <Suspense fallback={<CellPlaceholder />}>{children}</Suspense> : <CellPlaceholder />}
    </div>
  );
};

export default LazyMount;

import { useCallback, useRef } from 'react';

import { findGuideTargets, isUnderGuide, showGuideTarget, type GuideTarget } from './showMe';

/** AppShell's navbar slide (`transitionDuration` in App / EditorApp). */
const SIDEBAR_SLIDE_MS = 320;
/** One frame for the canvas to come back from under the Guide. */
const SETTLE_MS = 60;

export interface GuideShowMeDeps {
  closeGuide: () => void;
  /** Below `sm`: the sidebar is the mobile overlay. */
  isNarrow: boolean;
  desktopOpened: boolean;
  mobileOpened: boolean;
  toggleDesktop: () => void;
  toggleMobile: () => void;
  /** Components a selection can be made on, for the 'selection' target. */
  selectionIds: readonly string[];
}

/**
 * The Guide's "Show me": ring the real element, closing the Guide only when
 * the element is under it.
 *
 * The sidebar, the header and the filter panel stay on screen beside the
 * Guide, so pointing at them leaves the Guide open: the reader sees the
 * control and reads on. Only the canvas — sections, tiles — is covered; there
 * the Guide closes, which shows the same tab again (it never left it), and the
 * ring follows a frame later.
 *
 * The sidebar is the one target that may need opening first: folded away on a
 * wide screen, off canvas on a phone, where it slides in over the Guide.
 */
export function useGuideShowMe(deps: GuideShowMeDeps): (target: GuideTarget) => void {
  // Read at call time: the handler is handed to the Guide once per render and
  // the sidebar state may have moved since.
  const ref = useRef(deps);
  ref.current = deps;

  return useCallback((target: GuideTarget) => {
    const d = ref.current;
    const opts = { selectionIds: d.selectionIds };
    const found = findGuideTargets(target, opts);
    const underGuide = target === 'actions' || found.some(isUnderGuide);
    let delay = 0;
    if (underGuide) {
      d.closeGuide();
      delay = SETTLE_MS;
    }
    // The tab list sits in the sidebar; on the Guide's own entry, so does the
    // second ring.
    if (target === 'tabs' || target === 'guide') {
      if (d.isNarrow && !d.mobileOpened) {
        d.toggleMobile();
        delay = SIDEBAR_SLIDE_MS;
      } else if (!d.isNarrow && !d.desktopOpened) {
        d.toggleDesktop();
        delay = SIDEBAR_SLIDE_MS;
      }
    }
    const ring = () => showGuideTarget(target, opts);
    if (delay > 0) window.setTimeout(ring, delay);
    else ring();
  }, []);
}

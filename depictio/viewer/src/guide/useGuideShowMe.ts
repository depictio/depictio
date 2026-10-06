import { useCallback, useRef } from 'react';

import { showGuideTarget, type GuideTarget } from './showMe';

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
 * The Guide's "Show me": close the Guide, make the target reachable, ring it.
 *
 * Only the sidebar needs preparing — it can be folded away (desktop) or off
 * canvas (phone), and the tab list is what the Tabs part points at. Everything
 * else is on the page already; the ring scrolls it into view.
 */
export function useGuideShowMe(deps: GuideShowMeDeps): (target: GuideTarget) => void {
  // Read at call time: the handler is handed to the Guide once per render and
  // the sidebar state may have moved since.
  const ref = useRef(deps);
  ref.current = deps;

  return useCallback((target: GuideTarget) => {
    const d = ref.current;
    d.closeGuide();
    let delay = SETTLE_MS;
    if (target === 'tabs') {
      if (d.isNarrow && !d.mobileOpened) {
        d.toggleMobile();
        delay = SIDEBAR_SLIDE_MS;
      } else if (!d.isNarrow && !d.desktopOpened) {
        d.toggleDesktop();
        delay = SIDEBAR_SLIDE_MS;
      }
    }
    window.setTimeout(() => showGuideTarget(target, { selectionIds: d.selectionIds }), delay);
  }, []);
}

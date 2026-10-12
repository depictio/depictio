/**
 * Where the dock sits (one of a few anchors, remembered per browser) and the
 * first-visit introduction that points it out. Storage is a convenience: with
 * it blocked the dock sits at the foot and the introduction plays once per
 * page session.
 */
import React from 'react';

export type DockAnchor = 'bottom-center' | 'bottom-left' | 'bottom-right' | 'top-center';

export const DOCK_HOME: DockAnchor = 'bottom-center';
export const DOCK_ANCHORS: DockAnchor[] = [
  'bottom-center',
  'bottom-left',
  'bottom-right',
  'top-center',
];
/** For the live region that says where the dock went. */
export const ANCHOR_NAME: Record<DockAnchor, string> = {
  'bottom-center': 'bottom centre',
  'bottom-left': 'bottom left',
  'bottom-right': 'bottom right',
  'top-center': 'top centre',
};

/** Arrow keys walk the anchors as they sit on the page: the foot has three,
 *  the head one, so a direction with nowhere to go stays put. */
type Arrow = 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown';
export const ANCHOR_STEP: Record<DockAnchor, Partial<Record<Arrow, DockAnchor>>> = {
  'bottom-center': { ArrowLeft: 'bottom-left', ArrowRight: 'bottom-right', ArrowUp: 'top-center' },
  'bottom-left': { ArrowRight: 'bottom-center', ArrowUp: 'top-center' },
  'bottom-right': { ArrowLeft: 'bottom-center', ArrowUp: 'top-center' },
  'top-center': { ArrowDown: 'bottom-center' },
};

const ANCHOR_KEY = 'depictio-dock-anchor';
const INTRO_KEY = 'depictio-dock-intro-seen';
/** How long the introduction lasts when the reader does nothing. */
const INTRO_MS = 8000;

function readAnchor(): DockAnchor {
  try {
    const v = localStorage.getItem(ANCHOR_KEY);
    if (DOCK_ANCHORS.includes(v as DockAnchor)) return v as DockAnchor;
  } catch {
    // Storage blocked: the default.
  }
  return DOCK_HOME;
}

export function useDockAnchor(): [DockAnchor, (next: DockAnchor) => void] {
  const [anchor, setAnchor] = React.useState<DockAnchor>(readAnchor);
  const set = React.useCallback((next: DockAnchor) => {
    setAnchor(next);
    try {
      if (next === DOCK_HOME) localStorage.removeItem(ANCHOR_KEY);
      else localStorage.setItem(ANCHOR_KEY, next);
    } catch {
      // The choice lasts for this page only.
    }
  }, []);
  return [anchor, set];
}

/** Set once the introduction has run, so a remount (a tab switch) or blocked
 *  storage does not play it again. */
let introPlayed = false;

function introWanted(): boolean {
  if (introPlayed) return false;
  // Automated browsers start from an empty profile every time: no show.
  if (typeof navigator !== 'undefined' && navigator.webdriver) return false;
  try {
    return localStorage.getItem(INTRO_KEY) !== '1';
  } catch {
    return true;
  }
}

/** True until the introduction is over: after a few seconds, or when the
 *  reader uses the dock (`end`). Ending it sets the flag for good. */
export function useDockIntro(): { on: boolean; end: () => void } {
  const [on, setOn] = React.useState(introWanted);
  const end = React.useCallback(() => {
    introPlayed = true;
    try {
      localStorage.setItem(INTRO_KEY, '1');
    } catch {
      // Plays again on the next visit.
    }
    setOn(false);
  }, []);
  React.useEffect(() => {
    if (!on) return;
    const id = window.setTimeout(end, INTRO_MS);
    return () => window.clearTimeout(id);
  }, [on, end]);
  return { on, end };
}

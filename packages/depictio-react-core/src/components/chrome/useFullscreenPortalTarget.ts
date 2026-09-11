import { useEffect, useState } from 'react';

/**
 * Where a Mantine dropdown must be portaled so it is visible over a component
 * that is in native fullscreen: the fullscreen element itself, or `undefined`
 * for Mantine's default (a fresh div on `document.body`).
 *
 * A fullscreen element is painted in the browser's top layer, and the top layer
 * shows that element's subtree and nothing else. Everything Mantine portals —
 * Popover and Combobox dropdowns, Tooltips — lands on `document.body`, outside
 * that subtree, so it is never painted. The dropdown opens, holds focus and
 * swallows clicks, and the user sees nothing: the Settings popover of a
 * fullscreen figure was unusable for exactly this reason.
 *
 * No z-index will fix that, because the top layer is above every stacking
 * context. Portaling into the fullscreen element is the fix.
 *
 * Reading `document.fullscreenElement` rather than taking the element as a prop
 * keeps this a drop-in for any dropdown anywhere under the chrome: only one
 * element can be fullscreen, and while one is, it is the only thing on screen.
 */
export function useFullscreenPortalTarget(): HTMLElement | undefined {
  const [target, setTarget] = useState<HTMLElement | undefined>(undefined);
  useEffect(() => {
    const sync = () => setTarget((document.fullscreenElement as HTMLElement | null) ?? undefined);
    sync();
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);
  return target;
}

export default useFullscreenPortalTarget;

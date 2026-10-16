/**
 * The 3D model's side of zoom sync (highlight/zoomSync.ts): it follows the
 * residue window the synced tiles show by framing those residues. It never
 * sends one: a camera shows no residue range a sequence could be fitted to.
 */
import { useEffect, useRef, type MutableRefObject } from 'react';

import { followsWindow, type ZoomSyncHandle, type ZoomWindow } from '../../../highlight/zoomSync';
import { spanKey, type ResidueSpan, type StructureViewer } from './viewer';

/** The residues the camera can frame: one chain's numbered range. */
export interface FollowBounds {
  first: number;
  last: number;
  /** The chain framed on a complex, null for a single chain. */
  chain: string | null;
}

/**
 * The span the camera frames for window `w`: null for the whole model (a
 * source that fits its axis, or a window covering every residue), undefined
 * when the window misses the model. Residue `p` spans `[p, p + 1)`, so a
 * window shows every residue it touches.
 */
export function windowSpan(w: ZoomWindow, bounds: FollowBounds): ResidueSpan | null | undefined {
  if (w.fit) return null;
  const start = Math.max(bounds.first, Math.floor(w.start + 1e-6));
  const end = Math.min(bounds.last, Math.ceil(w.end - 1e-6) - 1);
  if (end < start) return undefined;
  if (start <= bounds.first && end >= bounds.last) return null;
  return { chain: bounds.chain, start, end };
}

/** Camera move per window, and the least time between two: a scroll sends a
 *  window per frame, and a camera restarted that often never settles. */
export const FOLLOW_MS = 250;

/**
 * Frame the synced tiles' window while this tile is a member: on joining, on
 * each new window, and when the model or its bounds change.
 */
export function useStructureZoomFollow(
  handle: ZoomSyncHandle | null,
  viewerRef: MutableRefObject<StructureViewer | null>,
  ready: boolean,
  bounds: FollowBounds | null,
): void {
  const boundsRef = useRef(bounds);
  boundsRef.current = bounds;
  const boundsKey = bounds ? `${bounds.chain ?? ''}:${bounds.first}-${bounds.last}` : '';
  useEffect(() => {
    if (!handle || !ready || !boundsKey) return undefined;
    const { store, peer } = handle;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastAt = -Infinity;
    // What the camera was last sent to: the same span again moves nothing.
    let lastKey: string | null = null;
    let pending: ResidueSpan | null = null;
    const fire = () => {
      timer = null;
      lastAt = Date.now();
      viewerRef.current?.focus(pending, FOLLOW_MS);
    };
    const follow = () => {
      if (!store.isMember(peer.index)) {
        // Left: the next join frames the window again.
        lastKey = null;
        return;
      }
      const w = store.current();
      const b = boundsRef.current;
      if (!b || !followsWindow(w, peer)) return;
      const span = windowSpan(w, b);
      if (span === undefined) return;
      const key = span ? spanKey(span) : '*';
      if (key === lastKey) return;
      lastKey = key;
      pending = span;
      if (timer) return;
      timer = setTimeout(fire, Math.max(0, lastAt + FOLLOW_MS - Date.now()));
    };
    follow();
    const off = store.subscribe(follow);
    return () => {
      off();
      if (timer) clearTimeout(timer);
    };
  }, [handle, viewerRef, ready, boundsKey]);
}

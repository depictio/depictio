import { useEffect, useState } from 'react';
import { comparer, reaction } from 'mobx';
import { isAlive } from '@jbrowse/mobx-state-tree';

import { collectViewTracks } from './fitToContent';
import { anyFittable } from './fitTracks';

/** What the open tracks of a view allow, for the toolbar to enable its actions. */
export interface TrackKinds {
  /** A track is open (in the view or a nested linear view): "Fit every track" has work. */
  hasTracks: boolean;
  /** A track is a signal track, which "Fit tracks to the tile" can stretch. */
  hasFittable: boolean;
}

const NONE: TrackKinds = { hasTracks: false, hasFittable: false };

const alive = (node: unknown): boolean => {
  try {
    return !!node && isAlive(node as Parameters<typeof isAlive>[0]);
  } catch {
    return false;
  }
};

function kindsOf(view: unknown): TrackKinds {
  if (!alive(view)) return NONE;
  const tracks = (view as { tracks?: Array<{ displays?: Array<{ type?: unknown }> }> }).tracks ?? [];
  const types = tracks.map((t) => t.displays?.[0]?.type);
  return { hasTracks: collectViewTracks(view).length > 0, hasFittable: anyFittable(types) };
}

/** Re-evaluated whenever a track opens, closes or swaps its display. */
export function useTrackKinds(view: unknown): TrackKinds {
  const [kinds, setKinds] = useState<TrackKinds>(NONE);
  useEffect(() => {
    if (!view) {
      setKinds(NONE);
      return undefined;
    }
    return reaction(() => kindsOf(view), setKinds, {
      equals: comparer.structural,
      fireImmediately: true,
    });
  }, [view]);
  return kinds;
}

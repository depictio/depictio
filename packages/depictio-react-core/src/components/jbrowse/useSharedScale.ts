import { useEffect } from 'react';
import { reaction } from 'mobx';
import { isAlive } from '@jbrowse/mobx-state-tree';

import { displayKey, displaysOf, entryFor, type Model } from './displaySettings';
import { scaleFamily, setBounds, sharedBounds, type YScaleMode } from './sharedScale';

/** ``isAlive`` throws on anything that is not a state-tree node. */
const alive = (node: unknown): boolean => {
  try {
    return !!node && isAlive(node as Parameters<typeof isAlive>[0]);
  } catch {
    return false;
  }
};

/**
 * Keep every quantitative track of `view` on one y scale while `mode` is
 * `shared` (see `sharedScale.ts`). The reaction watches the tracks' stats, so a
 * pan, a zoom or a track opened later re-unites them; leaving the mode lifts
 * the bounds it wrote, and each track goes back to its own scale.
 */
export function useSharedScale(view: unknown, mode: YScaleMode | undefined): void {
  useEffect(() => {
    const entry = entryFor('y_scale');
    if (mode !== 'shared' || !entry || !view || !alive(view)) return undefined;
    const touched = new Set<Model>();
    const quantitative = () => (alive(view) ? displaysOf(view, entry) : []);
    const dispose = reaction(
      // A string, so the effect runs only when a key or a range moves.
      () => {
        const displays = quantitative();
        const bounds = sharedBounds(displays);
        return JSON.stringify(
          displays.map((d) => {
            const family = scaleFamily(d.type);
            return [displayKey(d), family ? (bounds.get(family) ?? null) : null];
          }),
        );
      },
      () => {
        const displays = quantitative();
        const bounds = sharedBounds(displays);
        for (const d of displays) {
          const family = scaleFamily(d.type);
          const range = family ? bounds.get(family) : undefined;
          if (range) {
            setBounds(d, range);
            touched.add(d);
          } else if (touched.has(d)) {
            setBounds(d, undefined);
            touched.delete(d);
          }
        }
      },
      { fireImmediately: true },
    );
    return () => {
      dispose();
      for (const d of touched) if (alive(d)) setBounds(d, undefined);
    };
  }, [view, mode]);
}

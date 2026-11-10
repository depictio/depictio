import { useEffect, useRef } from 'react';
import { useMediaQuery } from '@mantine/hooks';

/** One left-hand surface that can fold for a while: its state now, and how to
 *  change it without remembering the change. */
export interface FoldableSurface {
  opened: boolean;
  fold?: (open: boolean) => void;
}

/** Longer than the swap between the two right panels (Analysis, Metadata), so
 *  going from one to the other does not unfold the left side in between. */
const RESTORE_DELAY_MS = 400;

/**
 * While a right-hand panel (Analysis, Metadata) is open, the tab sidebar and the
 * filter panel fold away to give it the room, and unfold when it closes. Only
 * what this folded comes back: a surface the reader had already closed stays
 * closed, and nothing is written to their stored choice. Not on a phone, where
 * the panels overlay the page instead of pushing it.
 */
export function usePanelRoom(
  open: boolean,
  surfaces: { nav?: FoldableSurface; filters?: FoldableSurface },
): void {
  const narrow = useMediaQuery('(max-width: 48em)', false, { getInitialValueInEffect: false });
  const live = useRef(surfaces);
  live.current = surfaces;
  const folded = useRef({ nav: false, filters: false });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (open && !narrow) {
      const { nav, filters } = live.current;
      if (nav?.fold && nav.opened && !folded.current.nav) {
        folded.current.nav = true;
        nav.fold(false);
      }
      if (filters?.fold && filters.opened && !folded.current.filters) {
        folded.current.filters = true;
        filters.fold(false);
      }
      return;
    }
    timer.current = setTimeout(() => {
      timer.current = null;
      if (folded.current.nav) {
        folded.current.nav = false;
        live.current.nav?.fold?.(true);
      }
      if (folded.current.filters) {
        folded.current.filters = false;
        live.current.filters?.fold?.(true);
      }
    }, RESTORE_DELAY_MS);
  }, [open, narrow]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
}

import { useEffect, useRef } from 'react';

import type { ColorByState } from '../selectionGroups';

/** What the hook needs of `useSelectionGroups`. */
interface AnalysisControls {
  setAnalysisArmed: (on: boolean) => void;
  setColorBy: (next: ColorByState) => void;
}

/**
 * Whether a change of the picked label column asks for the comparison:
 * `before` is `undefined` until the first loaded value (the state the
 * dashboard was left in, which is not a request), and unpicking asks nothing.
 */
export function armsOnPick(before: string | null | undefined, active: string | null): boolean {
  return before !== undefined && active != null && active !== before;
}

/**
 * "Compare in the charts" on a label column of the Metadata panel opens the
 * comparison in one step: Analysis mode is armed and the figures are coloured
 * by the groups the labels make ("My groups"). Picking the column is the
 * reader asking to compare, so a second trip to the Analysis panel would only
 * repeat it.
 *
 * Fires on a change of the picked column once the annotations are loaded, not
 * on the load itself: a dashboard reopened with a column still picked keeps
 * the Analysis state it was left in. Unpicking a column changes nothing here.
 */
export function useArmAnalysisOnCompare(
  activeColumnId: string | null | undefined,
  loaded: boolean,
  controls: AnalysisControls,
): void {
  const previous = useRef<string | null | undefined>(undefined);
  const latest = useRef(controls);
  latest.current = controls;
  useEffect(() => {
    if (!loaded) return;
    const active = activeColumnId ?? null;
    const before = previous.current;
    previous.current = active;
    if (armsOnPick(before, active)) {
      latest.current.setAnalysisArmed(true);
      latest.current.setColorBy({ kind: 'groups' });
    }
  }, [activeColumnId, loaded]);
}

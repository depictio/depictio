import { useLayoutEffect, useRef, useState } from 'react';

/** How long a stepper's primary button ignores clicks after a step change:
 *  longer than the gap between the two clicks of a double click. */
export const STEP_SETTLE_MS = 500;

/**
 * True for a moment after `step` changes, false otherwise.
 *
 * A stepper whose one primary button reads "Next" on the early steps and
 * "Create" on the last one lets the second click of a double click on Next
 * land on Create, so the user never stops on the confirm step. While this is
 * true, mark that button `aria-disabled` and ignore its clicks: the button
 * does not change look, and a test that clicks it waits until it is enabled.
 *
 * The layout effect runs before the browser handles the next click, so that
 * click already sees `true`.
 */
export function useStepSettling(step: string | number, ms: number = STEP_SETTLE_MS): boolean {
  const [settling, setSettling] = useState(false);
  const previous = useRef(step);
  useLayoutEffect(() => {
    if (previous.current === step) return undefined;
    previous.current = step;
    setSettling(true);
    const timer = window.setTimeout(() => setSettling(false), ms);
    return () => {
      window.clearTimeout(timer);
      setSettling(false);
    };
  }, [step, ms]);
  return settling;
}

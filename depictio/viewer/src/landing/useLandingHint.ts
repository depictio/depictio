import { useCallback, useState } from 'react';

const STORAGE_KEY = 'depictio:landing-hint:v1';

function readDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export interface LandingHintState {
  /** Eligible and not dismissed: the hint is up. */
  visible: boolean;
  dismiss: () => void;
}

/**
 * Whether the landing hint is up, and the visitor's say over it.
 *
 * Dismissal is remembered once per browser. Storage can be missing (private
 * window, blocked site data): the hint then simply comes back on every load.
 *
 * @param eligible - the caller's verdict on who sees the hint and where (a guest
 *   on the Overview of a public instance, the Guide closed).
 */
export function useLandingHint(eligible: boolean): LandingHintState {
  const [dismissed, setDismissed] = useState(readDismissed);

  const dismiss = useCallback(() => {
    setDismissed(true);
    try {
      localStorage.setItem(STORAGE_KEY, '1');
    } catch {
      /* storage unavailable: dismissed for this page load only */
    }
  }, []);

  return { visible: eligible && !dismissed, dismiss };
}

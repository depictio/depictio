import { useCallback, useEffect, useState } from 'react';

const PREFIX = 'depictio:landing-hint:v2:';

interface Stored {
  /** The introduction has been answered on this dashboard. */
  seen: boolean;
  /** The "What's new" mark (`since`) the news line was last answered for. */
  news: string | null;
}

const NONE: Stored = { seen: false, news: null };

function read(familyId: string | null): Stored {
  if (!familyId) return NONE;
  try {
    const raw = localStorage.getItem(PREFIX + familyId);
    if (!raw) return NONE;
    const parsed = JSON.parse(raw) as Partial<Stored>;
    return { seen: Boolean(parsed.seen), news: typeof parsed.news === 'string' ? parsed.news : null };
  } catch {
    return NONE;
  }
}

export interface LandingHintState {
  /** Something to say and not answered yet: the card is up. */
  visible: boolean;
  /** The card introduces the dashboard (a first visit). */
  intro: boolean;
  /** The card carries the "What's new" line. */
  news: boolean;
  dismiss: () => void;
}

/**
 * Whether the landing card is up on this dashboard, and the visitor's say
 * over it. Remembered per dashboard family, in this browser: a reader meets
 * each dashboard once, and hears again only when something changed since
 * their last visit. Storage can be missing (private window, blocked site
 * data): the card then simply comes back on every load.
 *
 * @param familyId - the dashboard family (its main tab id); null while loading.
 * @param introEligible - the caller's verdict on who is introduced and where
 *   (a reader who does not own the dashboard, on its main tab, the Guide closed).
 * @param newsSince - the mark of the reader's "What's new" when there is news
 *   to announce, else null.
 */
export function useLandingHint(
  familyId: string | null,
  introEligible: boolean,
  newsSince: string | null,
): LandingHintState {
  const [stored, setStored] = useState<Stored>(() => read(familyId));
  useEffect(() => setStored(read(familyId)), [familyId]);

  const intro = introEligible && !stored.seen;
  const news = newsSince !== null && stored.news !== newsSince;

  const dismiss = useCallback(() => {
    const next: Stored = { seen: stored.seen || introEligible, news: newsSince ?? stored.news };
    setStored(next);
    if (!familyId) return;
    try {
      localStorage.setItem(PREFIX + familyId, JSON.stringify(next));
    } catch {
      /* storage unavailable: dismissed for this page load only */
    }
  }, [familyId, introEligible, newsSince, stored]);

  return { visible: Boolean(familyId) && (intro || news), intro, news, dismiss };
}

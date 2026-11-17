import React, { useEffect } from 'react';

import { openChangesPanel, useChangesSince } from '../changes/ChangesSinceContext';
import { changeCounts, hasChanges, newsByRun } from '../changes/describe';
import { useRunningChapter } from '../coach/store';
import { formatRelativeTime } from '../lib/datetime';
import LandingHint, { type LandingNews } from './LandingHint';
import { useLandingHint } from './useLandingHint';

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

interface LandingHostProps {
  /** The dashboard family (its main tab id); null while loading. */
  familyId: string | null;
  /** Who is introduced and where: see `App.tsx`. */
  introEligible: boolean;
  audience: 'guest' | 'reader';
  description: string | null;
  guideOpen: boolean;
  onOpenGuide: () => void;
}

/**
 * The landing card, fed by the "What's new" change set. Rendered inside
 * `ChangeMarksProvider`, which the viewer mounts below itself: the news is
 * only readable from there.
 */
const LandingHost: React.FC<LandingHostProps> = ({
  familyId,
  introEligible,
  audience,
  description,
  guideOpen,
  onOpenGuide,
}) => {
  const ctx = useChangesSince();
  const cs = ctx && !ctx.readOnly && hasChanges(ctx.changeSet) ? ctx.changeSet : null;
  const newsSince = cs ? (cs.since ?? 'first') : null;
  const coachRunning = useRunningChapter() !== null;
  const landing = useLandingHint(familyId, introEligible && !guideOpen, guideOpen ? null : newsSince);

  // Opening the Guide, by the card or the sidebar, answers the introduction.
  const { dismiss, intro } = landing;
  useEffect(() => {
    if (guideOpen && intro) dismiss();
  }, [guideOpen, intro, dismiss]);

  // A coach chapter on screen (the welcome card's "Explore") speaks first.
  if (!landing.visible || guideOpen || coachRunning) return null;

  let news: LandingNews | null = null;
  if (landing.news && cs) {
    const counts = changeCounts(cs);
    // Runs are how data arrives: name them, newest first, then what no new
    // run explains.
    const byRun = newsByRun(cs.data);
    const runs = byRun.runs.map((r) => r.run);
    const otherData = counts.data - runs.length;
    const parts = [
      runs.length > 0 &&
        `${runs.length === 1 ? 'New run' : 'New runs'}: ${runs.slice(0, 3).join(', ')}${
          runs.length > 3 ? ` and ${runs.length - 3} more` : ''
        }`,
      otherData > 0 && plural(otherData, 'data update'),
      counts.dashboard > 0 && plural(counts.dashboard, 'dashboard edit'),
      counts.comments > 0 && plural(counts.comments, 'comment'),
    ].filter(Boolean) as string[];
    news = {
      headline: `${plural(counts.total, 'change')} since ${cs.since ? formatRelativeTime(cs.since) : 'your last visit'}`,
      detail: parts.join(' · '),
    };
  }

  return (
    <LandingHint
      description={description}
      audience={audience}
      intro={landing.intro}
      news={news}
      onOpenGuide={onOpenGuide}
      onOpenNews={() => {
        landing.dismiss();
        openChangesPanel();
      }}
      onDismiss={landing.dismiss}
    />
  );
};

export default LandingHost;

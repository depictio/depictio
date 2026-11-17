import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Anchor, Button, Group, Stack, Text } from '@mantine/core';
import { listDashboards } from 'depictio-react-core';
import { Icon } from '@iconify/react';

import DepictioRose from '../components/rose/DepictioRose';
import { dashboardHref } from '../dashboards/lib/dashboardLinks';
import { canGuestSignIn } from '../auth/guestSignIn';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { shouldSuppressWalkthrough } from './availability';
import { chapterById, chapterFor, formatSessionTtl, WELCOME_ROUTE } from './chapters';
import CoachCard, { CoachDots, renderCoachText } from './CoachCard';
import {
  chapterSeen,
  COACH_START_EVENT,
  markChapter,
  markWelcomeSeen,
  setRunningChapter,
  setTipsOff,
  startChapter,
  startChapterAt,
  takePendingChapter,
  useCoachState,
} from './store';
import type { CoachChapter, CoachContext, CoachPersona, CoachStep } from './types';

/** A guest explores a public or demo instance in a temporary session; anyone
 *  else (single-user admin, a signed-in user, a signed-in user of a public
 *  instance) builds. */
export function usePersona(): { persona: CoachPersona; ctx: CoachContext; loading: boolean } {
  const {
    user,
    ssoProviders,
    isPublicMode,
    isDemoMode,
    temporaryUserExpiryHours,
    temporaryUserExpiryMinutes,
    loading,
  } = useCurrentUser();
  const isGuest = (isPublicMode || isDemoMode) && (!user || Boolean(user.is_temporary));
  const persona: CoachPersona = isGuest ? 'guest' : 'builder';
  const canSignIn = canGuestSignIn({ loading, isPublicMode, isDemoMode, isGuest, providers: ssoProviders });
  const ctx = useMemo<CoachContext>(
    () => ({
      persona,
      sessionTtl: formatSessionTtl(temporaryUserExpiryHours, temporaryUserExpiryMinutes),
      canSignIn,
    }),
    [persona, temporaryUserExpiryHours, temporaryUserExpiryMinutes, canSignIn],
  );
  return { persona, ctx, loading };
}

const ChapterMark: React.FC<{ icon: string }> = ({ icon }) => <Icon icon={icon} width={20} height={20} />;
const RoseMark: React.FC = () => <DepictioRose mode="petals" size={26} label="" />;

// ---------------------------------------------------------------------------
// A running chapter
// ---------------------------------------------------------------------------

const ChapterTour: React.FC<{
  chapter: CoachChapter;
  steps: CoachStep[];
  ctx: CoachContext;
  onEnd: (status: 'done' | 'dismissed') => void;
}> = ({ chapter, steps, ctx, onEnd }) => {
  const [index, setIndex] = useState(0);
  const step = steps[index];
  const last = index === steps.length - 1;

  const next = useCallback(() => {
    if (last) onEnd('done');
    else setIndex((i) => i + 1);
  }, [last, onEnd]);
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  // Arrows step through, Esc closes, wherever the focus is, unless the
  // visitor is typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      if (e.key === 'ArrowRight') next();
      else if (e.key === 'ArrowLeft') back();
      else if (e.key === 'Escape') onEnd('dismissed');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [next, back, onEnd]);

  const body = typeof step.body === 'function' ? step.body(ctx) : step.body;
  return (
    <CoachCard
      key={step.id}
      stepKey={step.id}
      target={step.target}
      ring
      autoFocus
      mark={<ChapterMark icon={chapter.icon} />}
      eyebrow={`${chapter.label} · ${index + 1} of ${steps.length}`}
      title={step.title}
      onClose={() => onEnd('dismissed')}
      closeLabel="End the tour"
      testId="coach-step"
      footer={
        <Group justify="space-between" wrap="nowrap" mt={2}>
          <CoachDots total={steps.length} current={index} />
          <Group gap={6} wrap="nowrap">
            {index > 0 && (
              <Button variant="subtle" color="gray" size="xs" onClick={back}>
                Back
              </Button>
            )}
            <Button
              size="xs"
              onClick={next}
              rightSection={last ? undefined : <Icon icon="mdi:arrow-right" width={14} />}
              data-testid={last ? 'coach-done' : 'coach-next'}
            >
              {last ? 'Done' : 'Next'}
            </Button>
          </Group>
        </Group>
      }
    >
      {renderCoachText(body)}
    </CoachCard>
  );
};

// ---------------------------------------------------------------------------
// The offer made on a first arrival
// ---------------------------------------------------------------------------

const OfferCard: React.FC<{ chapter: CoachChapter; onStart: () => void; onLater: () => void }> = ({
  chapter,
  onStart,
  onLater,
}) => (
  <CoachCard
    target={null}
    mark={<RoseMark />}
    eyebrow={chapter.label}
    title={chapter.offer.title}
    onClose={onLater}
    closeLabel="Not now"
    width={340}
    testId="coach-offer"
    footer={
      <Stack gap={6}>
        <Group gap={6} wrap="nowrap">
          <Button size="xs" onClick={onStart} leftSection={<Icon icon="mdi:compass-outline" width={14} />} data-testid="coach-offer-start">
            Show me around
          </Button>
          <Button size="xs" variant="subtle" color="gray" onClick={onLater}>
            Not now
          </Button>
        </Group>
        <Anchor component="button" type="button" size="xs" c="dimmed" ta="left" onClick={() => setTipsOff(true)} data-testid="coach-tips-off">
          Don&apos;t offer tours again
        </Anchor>
      </Stack>
    }
  >
    {chapter.offer.body}
  </CoachCard>
);

// ---------------------------------------------------------------------------
// The welcome, once per browser
// ---------------------------------------------------------------------------

interface Journey {
  id: string;
  icon: string;
  title: string;
  detail: string;
  go: () => void;
  disabled?: boolean;
}

/** The dashboard "Explore" opens: the most recently changed one, main tab.
 *  Undefined while the list loads, null when there is none. */
function useExploreTarget(enabled: boolean): string | null | undefined {
  const [href, setHref] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    listDashboards(false)
      .then((list) => {
        const main = list.filter((d) => !d.parent_dashboard_id && d.dashboard_id);
        const stamp = (d: (typeof main)[number]) => String(d.last_saved_ts ?? '');
        main.sort((a, b) => stamp(b).localeCompare(stamp(a)));
        if (!cancelled) setHref(main[0] ? dashboardHref(String(main[0].dashboard_id)) : null);
      })
      .catch(() => {
        if (!cancelled) setHref(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return href;
}

const WelcomeCard: React.FC<{
  persona: CoachPersona;
  ctx: CoachContext;
  chapter: CoachChapter;
  onStart: () => void;
  onClose: () => void;
}> = ({ persona, ctx, chapter, onStart, onClose }) => {
  const here = window.location.pathname.replace(/\/$/, '');
  const goTo = (id: string, href: string) => {
    markWelcomeSeen();
    if (here === href) startChapter(id);
    else startChapterAt(id, href);
  };
  const explore = useExploreTarget(persona === 'builder');
  const journeys: Journey[] =
    persona === 'builder'
      ? [
          {
            id: 'explore',
            icon: 'mdi:view-dashboard-outline',
            title: 'Explore a dashboard',
            detail:
              explore === null
                ? "None yet: bring in a pipeline's results first."
                : 'Opens the latest one and shows you around it.',
            disabled: !explore,
            go: () => {
              if (explore) goTo('dashboard-explore', explore);
            },
          },
          {
            id: 'data',
            icon: 'mdi:folder-arrow-up-outline',
            title: "Bring in a pipeline's results",
            detail: 'A project reads a run folder and works out each file.',
            go: () => goTo('projects', '/projects'),
          },
          {
            id: 'build',
            icon: 'mdi:view-grid-plus-outline',
            title: 'Build a dashboard',
            detail: "On a project's data, from an empty canvas or an export.",
            go: () => goTo('dashboards-build', '/dashboards'),
          },
        ]
      : [];

  return (
    <CoachCard
      target={null}
      mark={<RoseMark />}
      eyebrow="Welcome"
      title="Depictio turns a pipeline's results into interactive dashboards."
      onClose={onClose}
      closeLabel="Close the welcome"
      width={400}
      testId="coach-welcome"
      footer={
        <Group gap={6} wrap="nowrap" mt={2}>
          <Button size="xs" onClick={onStart} leftSection={<Icon icon="mdi:compass-outline" width={14} />} data-testid="coach-welcome-start">
            Show me {chapter.label}
          </Button>
          <Button size="xs" variant="subtle" color="gray" onClick={onClose}>
            I&apos;ll explore on my own
          </Button>
        </Group>
      }
    >
      {persona === 'guest' ? (
        <Stack gap={6}>
          <Text inherit>
            The dashboards on this instance are open to explore. Duplicate one to get your own copy for this
            session ({ctx.sessionTtl}).
          </Text>
          {ctx.canSignIn && (
            <Text inherit c="dimmed">
              Signing in, from the avatar, lets you comment and keep your work.
            </Text>
          )}
        </Stack>
      ) : (
        <Stack gap="xs">
          <Text inherit c="dimmed">
            Where would you like to start?
          </Text>
          <div className="depictio-coach-journeys">
          {journeys.map((j) => (
            <button
              key={j.id}
              type="button"
              className="depictio-coach-journey"
              onClick={j.go}
              disabled={j.disabled}
              data-testid={`coach-journey-${j.id}`}
            >
              <span className="depictio-coach-mark" aria-hidden>
                <Icon icon={j.icon} width={18} height={18} />
              </span>
              <span style={{ minWidth: 0 }}>
                <Text fw={600} size="sm" lh={1.3}>
                  {j.title}
                </Text>
                <Text size="xs" c="dimmed" lh={1.4}>
                  {j.detail}
                </Text>
              </span>
            </button>
          ))}
          </div>
        </Stack>
      )}
    </CoachCard>
  );
};

// ---------------------------------------------------------------------------
// Host
// ---------------------------------------------------------------------------

/**
 * Decides what the coach shows on this page, if anything:
 *
 *  1. a chapter the visitor started (the compass, Account settings, a
 *     journey of the welcome card, or the offer below);
 *  2. on a first visit to the dashboards or projects list, the welcome;
 *  3. on a first arrival on a page with a chapter, the offer of it.
 *
 * Nothing is ever started without the visitor asking, and nothing shows on a
 * dashboard opened for reading: the landing card speaks there. The hard gates
 * (`/auth`, dev mode, the kill switch, `?no-walkthrough=1`) live in
 * `availability.ts`, shared with the manual triggers.
 */
const CoachHost: React.FC = () => {
  const { isDevMode, walkthroughDisabled } = useCurrentUser();
  const { persona, ctx, loading } = usePersona();
  const state = useCoachState();
  const pathname = window.location.pathname;
  const chapter = loading ? null : chapterFor(pathname, persona);
  const [running, setRunning] = useState<CoachChapter | null>(null);
  const [pending] = useState(() => takePendingChapter());
  useEffect(() => {
    setRunningChapter(running?.id ?? null);
    return () => setRunningChapter(null);
  }, [running]);

  useEffect(() => {
    if (loading || !pending) return;
    const asked = chapterById(pending);
    if (asked && asked.route.test(pathname)) setRunning(asked);
  }, [loading, pending, pathname]);

  useEffect(() => {
    const onStart = (e: Event) => {
      const id = (e as CustomEvent<{ id?: string }>).detail?.id;
      const asked = id ? chapterById(id) : chapter;
      if (asked) {
        markWelcomeSeen();
        setRunning(asked);
      }
    };
    window.addEventListener(COACH_START_EVENT, onStart);
    return () => window.removeEventListener(COACH_START_EVENT, onStart);
  }, [chapter]);

  const endRunning = useCallback(
    (status: 'done' | 'dismissed') => {
      if (running) markChapter(running.id, running.version, status);
      setRunning(null);
    },
    [running],
  );

  if (loading || shouldSuppressWalkthrough(isDevMode, walkthroughDisabled)) return null;

  if (running) {
    const steps = running.steps.filter((s) => !s.when || s.when(ctx));
    if (steps.length === 0) return null;
    return <ChapterTour key={running.id} chapter={running} steps={steps} ctx={ctx} onEnd={endRunning} />;
  }

  if (!chapter) return null;

  if (!state.welcomeSeen && WELCOME_ROUTE.test(pathname)) {
    return (
      <WelcomeCard
        persona={persona}
        ctx={ctx}
        chapter={chapter}
        onStart={() => {
          markWelcomeSeen();
          setRunning(chapter);
        }}
        onClose={() => {
          markWelcomeSeen();
          // Closing the welcome answers this page's offer too.
          markChapter(chapter.id, chapter.version, 'dismissed');
        }}
      />
    );
  }

  if (state.tipsOff || chapterSeen(state, chapter.id, chapter.version)) return null;
  return (
    <OfferCard
      chapter={chapter}
      onStart={() => setRunning(chapter)}
      onLater={() => markChapter(chapter.id, chapter.version, 'dismissed')}
    />
  );
};

export default CoachHost;

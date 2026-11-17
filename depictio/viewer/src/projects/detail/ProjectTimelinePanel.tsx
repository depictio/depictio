/**
 * The project's timeline (#1397), the History view of the Activity tab:
 * ingestions, dashboard versions and comments in one newest-first list, so
 * "what happened around that run" reads in one place. Items newer than the
 * reader's mark carry a "new" dot; an ingestion opens its details (each
 * collection's outcome) and offers "Compare" (what it changed in a
 * dashboard), a version links to its read-only preview. Rows look like the
 * What's new lists (`changes/feed`), grouped by day.
 *
 * It stands in for the ingestion history, so it keeps what that list did: a
 * run's steps and error, and a quiet refresh every few seconds while one is
 * still running.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Center, Chip, Group, Loader, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectIngestionRuns, fetchProjectTimeline } from 'depictio-react-core';
import type { MonitoringIngestionRun, TimelineEvent } from 'depictio-react-core';

import { FeedItem, FeedSection, NewDot, facts, nameList } from '../../changes/feed';
import { parseServerTimestamp } from '../../lib/datetime';
import { compactCount } from '../../monitoring/format';
import { IngestionRunDetails } from './ProjectIngestionHistoryPanel';
import { CompareMenu } from './RunDashboardActions';
import { isNewerThan, versionHref } from './projectChanges';

const PAGE = 25;
/** While an ingestion runs, the list refreshes this often. */
const RUNNING_POLL_MS = 3000;

type EventType = TimelineEvent['type'];

const FILTERS: Array<{ value: EventType; label: string }> = [
  { value: 'ingestion', label: 'Ingestions' },
  { value: 'version', label: 'Dashboard versions' },
  { value: 'comment', label: 'Comments' },
];

/** An ingestion's outcome: a word for the title and the colour of its icon. */
const OUTCOME: Record<string, { word: string; color: string }> = {
  success: { word: 'Ingested', color: 'teal' },
  partial: { word: 'Partly ingested', color: 'orange' },
  failed: { word: 'Ingestion failed', color: 'red' },
  interrupted: { word: 'Ingestion interrupted', color: 'orange' },
  abandoned: { word: 'Ingestion abandoned', color: 'gray' },
  running: { word: 'Ingesting', color: 'blue' },
};

const TRIGGER: Record<string, string> = { ui: 'from Add data', watch: 'by the watcher', cli: 'from the CLI' };

/** "Today", "Yesterday", or the date: the heading a day's events sit under. */
function dayOf(at: string): string {
  const d = parseServerTimestamp(at);
  if (!d) return 'Earlier';
  const today = new Date();
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(today) - start(d)) / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  return d.toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    ...(d.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}),
  });
}

/** A run's details, below its ingestion. */
interface DetailsToggle {
  open: boolean;
  /** undefined while loading; null when the run is past the loaded history. */
  run: MonitoringIngestionRun | null | undefined;
  onToggle: () => void;
}

const Title: React.FC<{ text: string; isNew: boolean }> = ({ text, isNew }) => (
  <>
    {text}
    {isNew && (
      <>
        {' '}
        <NewDot testId="timeline-new-badge" />
      </>
    )}
  </>
);

const IngestionItem: React.FC<{
  projectId: string;
  event: TimelineEvent;
  isNew: boolean;
  onShowRuns?: (run: string) => void;
  details: DetailsToggle;
}> = ({ projectId, event, isNew, onShowRuns, details }) => {
  const outcome = OUTCOME[event.status ?? ''] ?? { word: `Ingestion ${event.status ?? ''}`.trim(), color: 'gray' };
  const runs = event.run_tags ?? [];
  const collections = event.collections ?? [];
  return (
    <FeedItem
      kind="data"
      color={outcome.color}
      title={<Title text={runs.length ? `${outcome.word}: ${nameList(runs)}` : outcome.word} isNew={isNew} />}
      summary={facts(
        collections.length ? `${collections.length} collection${collections.length === 1 ? '' : 's'}` : null,
        event.rows_written ? `${compactCount(event.rows_written)} rows written` : null,
        event.trigger ? TRIGGER[event.trigger] ?? null : null,
      )}
      by={event.by ? [event.by] : undefined}
      at={event.at}
      data-testid="timeline-item"
      data-type="ingestion"
    >
      <Group gap={4} mt={4}>
        {runs.length === 1 && onShowRuns && (
          <Button
            size="compact-xs"
            variant="subtle"
            leftSection={<Icon icon="tabler:folder-open" width={14} />}
            onClick={() => onShowRuns(runs[0])}
          >
            Open the run
          </Button>
        )}
        <CompareMenu projectId={projectId} ingestionRunId={event.id} testId={`timeline-compare-${event.id}`} />
        <Button
          size="compact-xs"
          variant="subtle"
          color="gray"
          rightSection={<Icon icon={details.open ? 'tabler:chevron-up' : 'tabler:chevron-down'} width={14} />}
          onClick={details.onToggle}
          aria-expanded={details.open}
          data-testid={`timeline-steps-${event.id}`}
        >
          Details
        </Button>
      </Group>
      {details.open && (
        <Stack mt="xs" p="sm" style={{ borderRadius: 'var(--mantine-radius-md)', background: 'var(--mantine-color-default-hover)' }}>
          {details.run === undefined ? (
            <Loader size="xs" />
          ) : details.run === null ? (
            <Text size="xs" c="dimmed">
              This run is older than the loaded ingestion history.
            </Text>
          ) : (
            <IngestionRunDetails run={details.run} />
          )}
        </Stack>
      )}
    </FeedItem>
  );
};

const VersionItem: React.FC<{ event: TimelineEvent; isNew: boolean }> = ({ event, isNew }) => (
  <FeedItem
    kind="dashboard"
    title={<Title text={`${event.dashboard_title || 'Dashboard'} · version ${event.seq ?? '?'}`} isNew={isNew} />}
    summary={facts(
      event.kind ? event.kind[0].toUpperCase() + event.kind.slice(1) : null,
      event.label ? `\u201c${event.label}\u201d` : null,
      event.component_count != null
        ? `${event.component_count} component${event.component_count === 1 ? '' : 's'}`
        : null,
    )}
    by={event.by ? [event.by] : undefined}
    at={event.at}
    action={
      event.family_id
        ? { label: 'Open this version', href: versionHref(event.family_id, event.id), testId: `timeline-version-link-${event.id}` }
        : undefined
    }
    data-testid="timeline-item"
    data-type="version"
  />
);

const CommentItem: React.FC<{ event: TimelineEvent; isNew: boolean }> = ({ event, isNew }) => (
  <FeedItem
    kind="comment"
    title={
      <Title
        text={`${event.by ?? 'Someone'} commented${event.component_title ? ` on ${event.component_title}` : ''}`}
        isNew={isNew}
      />
    }
    detail={event.excerpt || undefined}
    at={event.at}
    action={event.family_id ? { label: 'Open the dashboard', href: `/dashboard/${event.family_id}` } : undefined}
    data-testid="timeline-item"
    data-type="comment"
  />
);

/** Events under their day, newest day first (the events come newest first). */
function groupByDay(events: TimelineEvent[]): Array<[string, TimelineEvent[]]> {
  const groups: Array<[string, TimelineEvent[]]> = [];
  for (const e of events) {
    const day = dayOf(e.at);
    const last = groups[groups.length - 1];
    if (last && last[0] === day) last[1].push(e);
    else groups.push([day, [e]]);
  }
  return groups;
}

export const ProjectTimelinePanel: React.FC<{
  projectId: string;
  /** The reader's mark (the change set's `since`): newer items are "new". */
  since: string | null;
  onShowRuns?: (run: string) => void;
  /** Bumped by the parent when an ingestion it started finishes. */
  refreshSignal?: number;
}> = ({ projectId, since, onShowRuns, refreshSignal = 0 }) => {
  const [types, setTypes] = useState<EventType[]>(FILTERS.map((f) => f.value));
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const generation = useRef(0);
  // Steps of the ingestions the reader opened, from the project's run history.
  const [openSteps, setOpenSteps] = useState<string[]>([]);
  const [runs, setRuns] = useState<Map<string, MonitoringIngestionRun>>(new Map());
  const [runsLoading, setRunsLoading] = useState(false);

  const loadRuns = useCallback(() => {
    setRunsLoading(true);
    fetchProjectIngestionRuns(projectId, { limit: 50 })
      .then((r) => setRuns(new Map(r.runs.map((run) => [run.run_id, run]))))
      .catch(() => {
        /* the steps say the run is not in the loaded history */
      })
      .finally(() => setRunsLoading(false));
  }, [projectId]);

  const toggleSteps = (id: string) => {
    setOpenSteps((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    if (!runs.has(id)) loadRuns();
  };

  // Newest page again, keeping the older pages already loaded: a run that
  // started or finished shows without the list flashing back to a loader.
  const refreshHead = useCallback(() => {
    if (types.length === 0) return;
    const gen = generation.current;
    fetchProjectTimeline(projectId, { types, limit: PAGE })
      .then((r) => {
        if (gen !== generation.current) return;
        setEvents((prev) => {
          const head = new Set(r.events.map((e) => `${e.type}-${e.id}`));
          const oldest = r.events.length ? r.events[r.events.length - 1].at : null;
          const older = (prev ?? []).filter(
            (e) => !head.has(`${e.type}-${e.id}`) && oldest != null && e.at < oldest,
          );
          return [...r.events, ...older];
        });
      })
      .catch(() => {
        /* the next refresh tries again */
      });
    if (openSteps.length) loadRuns();
  }, [projectId, types, openSteps.length, loadRuns]);

  useEffect(() => {
    const gen = ++generation.current;
    setEvents(null);
    setNext(null);
    setError(null);
    if (types.length === 0) {
      setEvents([]);
      return;
    }
    fetchProjectTimeline(projectId, { types, limit: PAGE })
      .then((r) => {
        if (gen !== generation.current) return;
        setEvents(r.events);
        setNext(r.next_before);
      })
      .catch((e: Error) => {
        if (gen === generation.current) setError(e.message || 'The timeline could not be loaded.');
      });
  }, [projectId, types]);

  const firstSignal = useRef(refreshSignal);
  useEffect(() => {
    if (refreshSignal === firstSignal.current) return;
    refreshHead();
    // Only a new signal refreshes; refreshHead changing alone does not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  const running = (events ?? []).some((e) => e.type === 'ingestion' && e.status === 'running');
  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(refreshHead, RUNNING_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [running, events, refreshHead]);

  const loadOlder = useCallback(async () => {
    if (!next) return;
    const gen = generation.current;
    setLoadingMore(true);
    try {
      const r = await fetchProjectTimeline(projectId, { types, limit: PAGE, before: next });
      if (gen !== generation.current) return;
      setEvents((prev) => [...(prev ?? []), ...r.events]);
      setNext(r.next_before);
    } catch (e) {
      if (gen === generation.current) setError((e as Error).message || 'Older events could not be loaded.');
    } finally {
      setLoadingMore(false);
    }
  }, [projectId, types, next]);

  return (
    <Stack gap="md" data-testid="project-timeline">
      <Chip.Group multiple value={types} onChange={(v) => setTypes(v as EventType[])}>
        <Group gap="xs">
          {FILTERS.map((f) => (
            <Chip key={f.value} value={f.value} size="xs" variant="outline" data-testid={`timeline-filter-${f.value}`}>
              {f.label}
            </Chip>
          ))}
        </Group>
      </Chip.Group>
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      {events === null && !error ? (
        <Center py="lg">
          <Loader size="sm" />
        </Center>
      ) : events && events.length === 0 ? (
        <Text size="sm" c="dimmed" data-testid="project-timeline-empty">
          {types.length === 0 ? 'Pick at least one kind of event.' : 'Nothing has happened in this project yet.'}
        </Text>
      ) : (
        events && (
          <Stack gap="md">
            {groupByDay(events).map(([day, items]) => (
              <FeedSection key={day} title={day}>
                {items.map((e) => {
                  const isNew = isNewerThan(e.at, since);
                  const key = `${e.type}-${e.id}`;
                  if (e.type === 'ingestion') {
                    return (
                      <IngestionItem
                        key={key}
                        projectId={projectId}
                        event={e}
                        isNew={isNew}
                        onShowRuns={onShowRuns}
                        details={{
                          open: openSteps.includes(e.id),
                          run: runs.get(e.id) ?? (runsLoading ? undefined : null),
                          onToggle: () => toggleSteps(e.id),
                        }}
                      />
                    );
                  }
                  if (e.type === 'version') return <VersionItem key={key} event={e} isNew={isNew} />;
                  return <CommentItem key={key} event={e} isNew={isNew} />;
                })}
              </FeedSection>
            ))}
          </Stack>
        )
      )}
      {next && (
        <Group>
          <Button
            variant="default"
            size="xs"
            loading={loadingMore}
            onClick={loadOlder}
            data-testid="timeline-load-older"
          >
            Load older
          </Button>
        </Group>
      )}
    </Stack>
  );
};

export default ProjectTimelinePanel;

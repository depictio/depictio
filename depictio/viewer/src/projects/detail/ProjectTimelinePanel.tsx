/**
 * The project's timeline (#1397), the History view of the Activity tab:
 * ingestions, dashboard versions and comments in one newest-first list, so
 * "what happened around that run" reads in one place. Items newer than the
 * reader's mark carry a "new" dot; an ingestion opens its steps and offers
 * "Compare" (what it changed in a dashboard), a version links to its
 * read-only preview.
 *
 * It stands in for the ingestion history, so it keeps what that list did: a
 * run's steps and error, and a quiet refresh every few seconds while one is
 * still running.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Anchor, Button, Center, Chip, Group, Loader, Stack, Text, Timeline } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectIngestionRuns, fetchProjectTimeline } from 'depictio-react-core';
import type { MonitoringIngestionRun, TimelineEvent } from 'depictio-react-core';

import { NewDot } from '../../changes/feed';
import { absTime, compactCount } from '../../monitoring/format';
import { CHECK_STATUS } from '../checkStatus';
import { IngestionRunDetails } from './ProjectIngestionHistoryPanel';
import { CompareMenu } from './RunDashboardActions';
import { ingestionOutcome, isNewerThan, versionHref } from './projectChanges';

const PAGE = 25;
/** While an ingestion runs, the list refreshes this often. */
const RUNNING_POLL_MS = 3000;
const COLLECTIONS_SHOWN = 4;

type EventType = TimelineEvent['type'];

const FILTERS: Array<{ value: EventType; label: string }> = [
  { value: 'ingestion', label: 'Ingestions' },
  { value: 'version', label: 'Dashboard versions' },
  { value: 'comment', label: 'Comments' },
];

const Bullet: React.FC<{ event: TimelineEvent }> = ({ event }) => {
  if (event.type === 'ingestion') {
    const mark = CHECK_STATUS[ingestionOutcome(event.status)];
    return <Icon icon={mark.icon} width={16} color={`var(--mantine-color-${mark.color}-6)`} />;
  }
  return <Icon icon={event.type === 'version' ? 'mdi:history' : 'mdi:comment-text-outline'} width={14} />;
};

/** A run's steps, below its ingestion event. */
interface StepsToggle {
  open: boolean;
  /** undefined while loading; null when the run is past the loaded history. */
  run: MonitoringIngestionRun | null | undefined;
  onToggle: () => void;
}

const EventBody: React.FC<{
  projectId: string;
  event: TimelineEvent;
  onShowRuns?: (run: string) => void;
  steps?: StepsToggle;
}> = ({ projectId, event, onShowRuns, steps }) => {
  if (event.type === 'ingestion') {
    const collections = event.collections ?? [];
    return (
      <Stack gap={6}>
        {((event.run_tags ?? []).length > 0 || Boolean(event.rows_written)) && (
          <Text size="xs" c="dimmed">
            {(event.run_tags ?? []).map((t, i) => (
              <React.Fragment key={t}>
                {i > 0 && ', '}
                <Anchor
                  href={`/projects/${projectId}?tab=runs&run=${encodeURIComponent(t)}`}
                  onClick={(e: React.MouseEvent) => {
                    if (!onShowRuns) return;
                    e.preventDefault();
                    onShowRuns(t);
                  }}
                  size="xs"
                  fw={500}
                >
                  {t}
                </Anchor>
              </React.Fragment>
            ))}
            {(event.run_tags ?? []).length > 0 && event.rows_written ? ' \u00b7 ' : null}
            {event.rows_written ? `${compactCount(event.rows_written)} rows written` : null}
          </Text>
        )}
        {collections.length > 0 && (
          <Text size="xs" c="dimmed">
            {collections.slice(0, COLLECTIONS_SHOWN).join(', ')}
            {collections.length > COLLECTIONS_SHOWN ? ` and ${collections.length - COLLECTIONS_SHOWN} more` : ''}
          </Text>
        )}
        <Group gap="xs">
          <CompareMenu
            projectId={projectId}
            ingestionRunId={event.id}
            testId={`timeline-compare-${event.id}`}
          />
          {steps && (
            <Button
              size="compact-xs"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon={steps.open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={14} />}
              onClick={steps.onToggle}
              data-testid={`timeline-steps-${event.id}`}
            >
              {steps.open ? 'Hide steps' : 'Steps'}
            </Button>
          )}
        </Group>
        {steps?.open &&
          (steps.run === undefined ? (
            <Loader size="xs" />
          ) : steps.run === null ? (
            <Text size="xs" c="dimmed">
              This run is older than the loaded ingestion history.
            </Text>
          ) : (
            <IngestionRunDetails run={steps.run} />
          ))}
      </Stack>
    );
  }
  if (event.type === 'version') {
    return (
      <Group gap={8} wrap="wrap">
        {event.kind && (
          <Text size="xs" c="dimmed" tt="capitalize">
            {event.kind}
          </Text>
        )}
        {event.label && (
          <Text size="xs" c="dimmed">
            “{event.label}”
          </Text>
        )}
        {event.component_count != null && (
          <Text size="xs" c="dimmed">
            {event.component_count} component{event.component_count === 1 ? '' : 's'}
          </Text>
        )}
        {event.family_id && (
          <Anchor
            href={versionHref(event.family_id, event.id)}
            size="xs"
            data-testid={`timeline-version-link-${event.id}`}
          >
            Open this version
          </Anchor>
        )}
      </Group>
    );
  }
  return (
    <Stack gap={2}>
      {event.excerpt && (
        <Text size="sm" style={{ overflowWrap: 'anywhere' }}>
          {event.excerpt}
        </Text>
      )}
      <Group gap={8}>
        {event.component_title && (
          <Text size="xs" c="dimmed">
            on {event.component_title}
          </Text>
        )}
        {event.family_id && (
          <Anchor href={`/dashboard/${event.family_id}`} size="xs">
            Open the dashboard
          </Anchor>
        )}
      </Group>
    </Stack>
  );
};

const titleOf = (e: TimelineEvent): string => {
  if (e.type === 'ingestion') return `Ingestion ${e.status ?? ''}${e.trigger ? ` (${e.trigger})` : ''}`.trim();
  if (e.type === 'version') return `${e.dashboard_title || 'Dashboard'} · v${e.seq ?? '?'}`;
  return 'Comment';
};

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
          <Timeline active={-1} bulletSize={26} lineWidth={2}>
            {events.map((e) => (
              <Timeline.Item
                key={`${e.type}-${e.id}`}
                bullet={<Bullet event={e} />}
                title={
                  <Group gap={8} wrap="wrap">
                    <Text size="sm" fw={600}>
                      {titleOf(e)}
                    </Text>
                    {isNewerThan(e.at, since) && <NewDot testId="timeline-new-badge" />}
                  </Group>
                }
                data-testid="timeline-item"
                data-type={e.type}
              >
                <Text size="xs" c="dimmed" mb={4}>
                  {absTime(e.at)}
                  {e.by ? ` · ${e.by}` : ''}
                </Text>
                <EventBody
                  projectId={projectId}
                  event={e}
                  onShowRuns={onShowRuns}
                  steps={
                    e.type === 'ingestion'
                      ? {
                          open: openSteps.includes(e.id),
                          run: runs.get(e.id) ?? (runsLoading ? undefined : null),
                          onToggle: () => toggleSteps(e.id),
                        }
                      : undefined
                  }
                />
              </Timeline.Item>
            ))}
          </Timeline>
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

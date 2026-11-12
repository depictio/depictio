/**
 * The project's timeline (#1397): ingestions, dashboard versions and comments
 * in one newest-first list, so "what happened around that run" reads in one
 * place. Items newer than the reader's mark carry a "new" badge; an ingestion
 * offers "Compare" (what it changed in a dashboard), a version links to its
 * read-only preview.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Anchor, Button, Center, Chip, Group, Loader, Stack, Text, Timeline } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectTimeline } from 'depictio-react-core';
import type { TimelineEvent } from 'depictio-react-core';

import { absTime, compactCount } from '../../monitoring/format';
import { FactBadge, NameChip, StatusBadge } from '../badges';
import { CHECK_STATUS } from '../checkStatus';
import { CompareMenu } from './RunDashboardActions';
import { ingestionOutcome, isNewerThan, versionHref } from './projectChanges';

const PAGE = 25;
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

const NewBadge: React.FC = () => (
  <StatusBadge size="xs" color="blue" data-testid="timeline-new-badge">
    new
  </StatusBadge>
);

const EventBody: React.FC<{
  projectId: string;
  event: TimelineEvent;
  onShowRuns?: (run: string) => void;
}> = ({ projectId, event, onShowRuns }) => {
  if (event.type === 'ingestion') {
    const collections = event.collections ?? [];
    return (
      <Stack gap={6}>
        <Group gap={6} wrap="wrap">
          {(event.run_tags ?? []).map((t) => (
            <Anchor
              key={t}
              href={`/projects/${projectId}?tab=runs&run=${encodeURIComponent(t)}`}
              onClick={(e: React.MouseEvent) => {
                if (!onShowRuns) return;
                e.preventDefault();
                onShowRuns(t);
              }}
              underline="never"
            >
              <NameChip size="xs" style={{ cursor: 'pointer' }}>
                {t}
              </NameChip>
            </Anchor>
          ))}
          {event.rows_written ? (
            <Text size="xs" c="dimmed">
              {compactCount(event.rows_written)} rows written
            </Text>
          ) : null}
        </Group>
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
        </Group>
      </Stack>
    );
  }
  if (event.type === 'version') {
    return (
      <Group gap={8} wrap="wrap">
        {event.kind && <FactBadge size="xs">{event.kind}</FactBadge>}
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
}> = ({ projectId, since, onShowRuns }) => {
  const [types, setTypes] = useState<EventType[]>(FILTERS.map((f) => f.value));
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const generation = useRef(0);

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
                    {isNewerThan(e.at, since) && <NewBadge />}
                  </Group>
                }
                data-testid="timeline-item"
                data-type={e.type}
              >
                <Text size="xs" c="dimmed" mb={4}>
                  {absTime(e.at)}
                  {e.by ? ` · ${e.by}` : ''}
                </Text>
                <EventBody projectId={projectId} event={e} onShowRuns={onShowRuns} />
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

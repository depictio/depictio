import React, { useEffect, useState } from 'react';
import {
  Anchor,
  Badge,
  Card,
  Divider,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchGenerations } from '../api';
import type { GenerationCounts, GenerationSummary } from '../types';
import { formatGeneratedAt } from './AIDraftBanner';

export interface GenerationHistoryProps {
  /** Project whose runs are listed. Null clears the list and fetches
   *  nothing, which is the state before a project is picked. */
  projectId: string | null;
  /** Server clamps its own maximum; 20 matches the route's default. */
  limit?: number;
  /** Navigate to a run's draft. Omitted, the row still links, as a plain
   *  href to the editor. */
  onOpen?: (dashboardId: string) => void;
  /** Bump to refetch — e.g. after a run finishes in the panel beside this. */
  refreshKey?: number;
}

// Keyed loosely: the server types `status` as a plain string, so a value
// this UI has not heard of falls back to the neutral badge instead of an
// undefined colour.
const STATUS_COLOR: Record<string, string> = {
  running: 'blue',
  complete: 'teal',
  failed: 'red',
  cancelled: 'yellow',
};

/** ok / repaired / dropped, in that order and only when non-zero: a run
 *  where nothing was repaired should not spend a badge saying so. */
const COUNT_COLOR: Record<keyof GenerationCounts, string> = {
  ok: 'teal',
  repaired: 'yellow',
  dropped: 'red',
};

/** The row spells its tally out flat; a nested `counts`, were one ever to
 *  arrive, wins over it. */
function countsOf(run: GenerationSummary): GenerationCounts {
  return {
    ok: run.counts?.ok ?? run.ok ?? 0,
    repaired: run.counts?.repaired ?? run.repaired ?? 0,
    dropped: run.counts?.dropped ?? run.dropped ?? 0,
  };
}

/**
 * "Previous generations" for one project: what has been run before, newest
 * first, beside the panel that runs the next one.
 *
 * Follows the side column of `AIAnalysisModal` — the same card per run with
 * the prompt, the model, a status badge and the date — plus what is specific
 * to generation: how many components came out ok, repaired or dropped, the
 * warnings the run collected, and a way back into the draft it saved. A run
 * that saved nothing (cancelled, or failed before the draft landed) is
 * listed too, without the link.
 */
const GenerationHistory: React.FC<GenerationHistoryProps> = ({
  projectId,
  limit = 20,
  onOpen,
  refreshKey = 0,
}) => {
  const [runs, setRuns] = useState<GenerationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRuns([]);
    setError(null);
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    fetchGenerations(projectId, limit)
      .then((list) => {
        if (!cancelled) setRuns(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, limit, refreshKey]);

  const openDraft = (event: React.MouseEvent, dashboardId: string) => {
    if (!onOpen) return;
    event.preventDefault();
    onOpen(dashboardId);
  };

  return (
    <Stack gap="xs" data-testid="generation-history">
      <Group gap="xs">
        <Icon icon="material-symbols:history" width={16} />
        <Title order={6}>Previous generations</Title>
        {loading && <Loader size="xs" />}
      </Group>
      <Divider />
      {!projectId && (
        <Text size="xs" c="dimmed">
          Select a project to see what it has generated before.
        </Text>
      )}
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
      {projectId && !loading && !error && runs.length === 0 && (
        <Text size="xs" c="dimmed" data-testid="generation-history-empty">
          No generation runs yet for this project.
        </Text>
      )}
      <ScrollArea.Autosize mah={420} offsetScrollbars>
        <Stack gap="xs">
          {runs.map((run) => {
            // Pulled out of the JSX so the link's callback closes over a
            // narrowed id rather than re-reading a nullable property.
            const draftId = run.dashboard_id;
            const counts = countsOf(run);
            return (
              <Card
                key={run.id}
                withBorder
                radius="md"
                p="sm"
                data-testid="generation-history-item"
                data-generation-id={run.id}
                data-status={run.status}
              >
                <Stack gap={4}>
                  <Text size="sm" fw={500} lineClamp={1}>
                    {run.title || 'Untitled run'}
                  </Text>
                  {run.prompt && (
                    <Text size="xs" c="dimmed" lineClamp={2} title={run.prompt}>
                      {run.prompt}
                    </Text>
                  )}
                  <Group gap="xs">
                    <Badge
                      size="xs"
                      variant="light"
                      color={STATUS_COLOR[run.status] ?? 'gray'}
                    >
                      {run.status}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {run.model}
                    </Text>
                    <Text size="xs" c="dimmed" ml="auto">
                      {formatGeneratedAt(run.created_at)}
                    </Text>
                  </Group>
                  <Group gap={4}>
                    {(['ok', 'repaired', 'dropped'] as const).map((kind) => {
                      const n = counts[kind];
                      if (!n) return null;
                      return (
                        <Badge
                          key={kind}
                          size="xs"
                          variant="outline"
                          color={COUNT_COLOR[kind]}
                          data-testid={`generation-history-count-${kind}`}
                        >
                          {n} {kind}
                        </Badge>
                      );
                    })}
                  </Group>
                  {run.warnings?.map((w, i) => (
                    <Text key={i} size="xs" c="dimmed" lineClamp={2}>
                      {w}
                    </Text>
                  ))}
                  {draftId && (
                    <Anchor
                      size="xs"
                      href={`/dashboard-edit/${draftId}`}
                      onClick={(e) => openDraft(e, draftId)}
                      data-testid="generation-history-open"
                    >
                      Open dashboard
                    </Anchor>
                  )}
                </Stack>
              </Card>
            );
          })}
        </Stack>
      </ScrollArea.Autosize>
    </Stack>
  );
};

export default GenerationHistory;

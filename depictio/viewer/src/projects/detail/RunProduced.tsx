/**
 * What a run produced: the ingestions that brought it in, the Delta commits
 * and MultiQC reports it wrote per collection, and the two ways to look at the
 * dashboards around it. Mounted when the run's row is first opened, so the
 * requests (one history read per collection that found files in the run) never
 * happen for a run nobody looks at.
 */
import React, { useEffect, useState } from 'react';
import { Group, Loader, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDeltaHistory, fetchMultiQCByDataCollection } from 'depictio-react-core';
import type {
  DeltaVersionEntry,
  MonitoringIngestionRun,
  ProjectRun,
} from 'depictio-react-core';

import { absTime, compactCount } from '../../monitoring/format';
import { NameChip } from '../badges';
import { CHECK_STATUS } from '../checkStatus';
import { BeforeRunMenu, CompareMenu } from './RunDashboardActions';
import {
  commitsForRun,
  firstIngestionOf,
  ingestionOutcome,
  ingestionsForRun,
  reportsForRun,
  sampleCount,
  type ReportLike,
} from './projectChanges';

/** Collections read per run; the rest are counted, not fetched. */
const MAX_COLLECTIONS = 12;
const HISTORY_WINDOW = 50;
const REPORT_WINDOW = 100;

const DELTA_TYPES = new Set(['table', 'genomic_tracks', 'image']);

type Written =
  | { tag: string; dcId: string; kind: 'commits'; commits: DeltaVersionEntry[] }
  | { tag: string; dcId: string; kind: 'reports'; reports: number; samples: number }
  | { tag: string; dcId: string; kind: 'unreadable' };

interface Produced {
  ingestions: MonitoringIngestionRun[];
  written: Written[];
  skipped: number;
}

export const RunProduced: React.FC<{
  projectId: string;
  run: ProjectRun;
  dcIdByTag: Record<string, string>;
  dcTypeByTag: Record<string, string>;
  loadIngestions: () => Promise<{ runs: MonitoringIngestionRun[]; redacted: boolean }>;
  onOpenDc?: (dcId: string) => void;
}> = ({ projectId, run, dcIdByTag, dcTypeByTag, loadIngestions, onOpenDc }) => {
  const [produced, setProduced] = useState<Produced | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setProduced(null);
    setError(null);
    (async () => {
      const { runs } = await loadIngestions();
      const ingestions = ingestionsForRun(runs, run.run_tag);
      const ids = ingestions.map((i) => i.run_id);
      const withFiles = Object.entries(run.dc_files)
        .filter(([, n]) => n > 0)
        .map(([tag]) => tag)
        .filter((tag) => dcIdByTag[tag]);
      const shown = withFiles.slice(0, MAX_COLLECTIONS);
      const written = await Promise.all(
        shown.map(async (tag): Promise<Written | null> => {
          const dcId = dcIdByTag[tag];
          const type = (dcTypeByTag[tag] ?? 'table').toLowerCase();
          try {
            if (type === 'multiqc') {
              const list = await fetchMultiQCByDataCollection(dcId, REPORT_WINDOW);
              const reports = reportsForRun(
                list.reports.map((r) => (r.report ?? {}) as ReportLike),
                run.run_tag,
                ids,
              );
              return { tag, dcId, kind: 'reports', reports: reports.length, samples: sampleCount(reports) };
            }
            if (DELTA_TYPES.has(type)) {
              const history = await fetchDeltaHistory(dcId, HISTORY_WINDOW);
              return { tag, dcId, kind: 'commits', commits: commitsForRun(history.versions, run.run_tag, ids) };
            }
            return null;
          } catch {
            return { tag, dcId, kind: 'unreadable' };
          }
        }),
      );
      if (!live) return;
      setProduced({
        ingestions,
        written: written.filter((w): w is Written => w !== null),
        skipped: withFiles.length - shown.length,
      });
    })().catch((e: Error) => {
      if (live) setError(e.message || 'What this run produced could not be loaded.');
    });
    return () => {
      live = false;
    };
  }, [run, dcIdByTag, dcTypeByTag, loadIngestions]);

  const first = produced ? firstIngestionOf(produced.ingestions) : null;

  return (
    <Stack gap="xs" data-testid={`run-produced-${run.run_tag}`}>
      <Group gap={6} wrap="nowrap">
        <Icon icon="mdi:package-variant-closed" width={14} style={{ opacity: 0.6 }} />
        <Text size="xs" c="dimmed" fw={600} tt="uppercase">
          Produced
        </Text>
      </Group>
      {error ? (
        <Text size="sm" c="dimmed">
          {error}
        </Text>
      ) : !produced ? (
        <Loader size="xs" />
      ) : (
        <>
          <Stack gap={4} data-testid={`run-produced-ingestions-${run.run_tag}`}>
            {produced.ingestions.length === 0 ? (
              <Text size="sm" c="dimmed">
                No ingestion is recorded for this run.
              </Text>
            ) : (
              produced.ingestions.map((ing) => {
                const mark = CHECK_STATUS[ingestionOutcome(ing.status)];
                return (
                  <Group key={ing.run_id} gap={8} wrap="wrap">
                    <Icon
                      icon={mark.icon}
                      width={16}
                      color={`var(--mantine-color-${mark.color}-6)`}
                      aria-label={ing.status}
                    />
                    <Text size="sm">Ingestion {ing.status}</Text>
                    <Text size="sm" c="dimmed">
                      {absTime(ing.started_at)}
                    </Text>
                    {ing.trigger && (
                      <Text size="sm" c="dimmed">
                        · {ing.trigger}
                      </Text>
                    )}
                    {!ing.redacted && ing.email && (
                      <Text size="sm" c="dimmed">
                        · {ing.email}
                      </Text>
                    )}
                    <NameChip size="xs" dimmed>
                      {ing.run_id.slice(0, 8)}
                    </NameChip>
                  </Group>
                );
              })
            )}
          </Stack>
          {produced.written.length > 0 && (
            <Stack gap={4} data-testid={`run-produced-written-${run.run_tag}`}>
              {produced.written.map((w) => (
                <Group key={w.tag} gap={8} wrap="wrap" align="baseline">
                  {onOpenDc ? (
                    <Text
                      size="sm"
                      fw={500}
                      style={{ cursor: 'pointer' }}
                      onClick={() => onOpenDc(w.dcId)}
                    >
                      {w.tag}
                    </Text>
                  ) : (
                    <Text size="sm" fw={500}>
                      {w.tag}
                    </Text>
                  )}
                  {w.kind === 'unreadable' && (
                    <Text size="sm" c="dimmed">
                      history unavailable
                    </Text>
                  )}
                  {w.kind === 'reports' && (
                    <Text size="sm" c="dimmed">
                      {w.reports === 0
                        ? 'no report recorded for this run'
                        : `${w.reports === 1 ? '1 report' : `${w.reports} reports`} · ${
                            w.samples === 1 ? '1 sample' : `${compactCount(w.samples)} samples`
                          }`}
                    </Text>
                  )}
                  {w.kind === 'commits' && w.commits.length === 0 && (
                    <Text size="sm" c="dimmed">
                      no commit recorded for this run
                    </Text>
                  )}
                  {w.kind === 'commits' &&
                    w.commits.map((c, i) => (
                      <Text key={`${c.version ?? 'x'}-${i}`} size="sm" c="dimmed">
                        {c.version != null ? `v${c.version}` : 'commit'}
                        {c.rows_added != null ? ` · +${compactCount(c.rows_added)} rows` : ''}
                        {c.operation ? ` · ${c.operation.toLowerCase()}` : ''}
                      </Text>
                    ))}
                </Group>
              ))}
              {produced.skipped > 0 && (
                <Text size="xs" c="dimmed">
                  and {produced.skipped} more collection{produced.skipped === 1 ? '' : 's'}
                </Text>
              )}
            </Stack>
          )}
          <Group gap="xs" wrap="wrap" mt={4}>
            <BeforeRunMenu
              projectId={projectId}
              runTag={run.run_tag}
              startedAt={first?.started_at}
              testId={`run-before-${run.run_tag}`}
            />
            <CompareMenu
              projectId={projectId}
              ingestionRunId={first?.run_id}
              testId={`run-compare-${run.run_tag}`}
            />
          </Group>
        </>
      )}
    </Stack>
  );
};

export default RunProduced;

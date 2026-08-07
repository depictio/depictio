/**
 * Section-summary UI: the sparkle trigger (slotted into a section
 * header's `trailing` area) and the dismissible summary panel rendered
 * above the section's grid content.
 *
 * State handling lives in the host via `useSectionSummaries` — this file
 * is presentation only, so DashboardGrid stays AI-free and the host
 * decides where each piece mounts.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { getSummaries } from '../api';
import { useSummarizeSection } from '../hooks';
import { AI_ICON } from '../icons';
import type {
  SummarizeSectionResponse,
  SummaryComponentPayload,
  SummaryEntry,
} from '../types';

export interface SectionSummaryState {
  summary_md: string;
  generated_at: string;
  model: string;
  context_hash: string;
  /** True when the stored hash no longer matches what's on screen. */
  stale: boolean;
  pending: boolean;
  error: string | null;
}

/** Client-side digest trimming, mirroring the server's caps (which still
 *  apply — this just keeps multi-megabyte Plotly traces off the wire).
 *  Long lists keep head+tail with a marker; long strings keep a prefix. */
export function trimDigest(value: unknown, maxList = 60, maxStr = 400): unknown {
  if (typeof value === 'string') {
    return value.length > maxStr ? `${value.slice(0, maxStr)}… [trimmed]` : value;
  }
  if (Array.isArray(value)) {
    if (value.length > maxList) {
      const head = Math.floor(maxList / 2);
      const tail = maxList - head;
      return [
        ...value.slice(0, head).map((v) => trimDigest(v, maxList, maxStr)),
        `… [${value.length - maxList} items trimmed]`,
        ...value.slice(value.length - tail).map((v) => trimDigest(v, maxList, maxStr)),
      ];
    }
    return value.map((v) => trimDigest(v, maxList, maxStr));
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = trimDigest(v, maxList, maxStr);
    }
    return out;
  }
  return value;
}

/** Host-facing hook: cached summaries on load + per-section generation.
 *
 *  `buildContext(section)` must return the current filters + component
 *  digests for that section — the host owns rendering state, so only it
 *  can assemble what the user actually sees. May be async (e.g. when the
 *  host refetches figure/table data at summarize time).
 */
export function useSectionSummaries(
  dashboardId: string,
  enabled: boolean,
  buildContext: (section: string | null) =>
    | { filters: unknown[]; components: SummaryComponentPayload[] }
    | Promise<{ filters: unknown[]; components: SummaryComponentPayload[] }>,
) {
  const [entries, setEntries] = useState<Record<string, SummaryEntry>>({});
  const [pendingSection, setPendingSection] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { run } = useSummarizeSection(dashboardId);

  const keyOf = (section: string | null) => section ?? '';

  useEffect(() => {
    if (!enabled || !dashboardId) return;
    let cancelled = false;
    getSummaries(dashboardId)
      .then((res) => {
        if (cancelled) return;
        const map: Record<string, SummaryEntry> = {};
        for (const e of res.summaries) map[keyOf(e.section)] = e;
        setEntries(map);
      })
      .catch(() => {
        /* no cached summaries is fine */
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, enabled]);

  const generate = useCallback(
    async (section: string | null, force = false): Promise<SummarizeSectionResponse | null> => {
      setPendingSection(keyOf(section));
      setError(null);
      let filters: unknown[];
      let components: SummaryComponentPayload[];
      try {
        ({ filters, components } = await buildContext(section));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPendingSection(null);
        return null;
      }
      if (components.length === 0) {
        setPendingSection(null);
        return null;
      }
      try {
        const res = await run({ section, filters, components, force });
        setEntries((prev) => ({
          ...prev,
          [keyOf(section)]: {
            section,
            summary_md: res.summary_md,
            generated_at: res.generated_at,
            model: res.model,
            context_hash: res.context_hash,
          },
        }));
        return res;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        setPendingSection(null);
      }
    },
    [buildContext, run],
  );

  const dismiss = useCallback((section: string | null) => {
    setEntries((prev) => {
      const next = { ...prev };
      delete next[keyOf(section)];
      return next;
    });
  }, []);

  return useMemo(
    () => ({ entries, generate, dismiss, pendingSection, error }),
    [entries, generate, dismiss, pendingSection, error],
  );
}

interface ButtonProps {
  section: string | null;
  hasSummary: boolean;
  pending: boolean;
  onGenerate: (section: string | null, force?: boolean) => void;
}

/** Sparkle affordance for a section header's `trailing` slot. */
export const SummarizeSectionButton: React.FC<ButtonProps> = ({
  section,
  hasSummary,
  pending,
  onGenerate,
}) => (
  <Tooltip label={hasSummary ? 'Regenerate AI summary' : 'Summarize this section with AI'}>
    <ActionIcon
      size="sm"
      variant="subtle"
      color="violet"
      loading={pending}
      onClick={(e) => {
        e.stopPropagation();
        onGenerate(section, hasSummary);
      }}
      aria-label="Summarize section"
      data-testid={`ai-summarize-${section ?? 'dashboard'}`}
    >
      <Icon icon={AI_ICON} width={16} />
    </ActionIcon>
  </Tooltip>
);

interface PanelProps {
  entry: SummaryEntry;
  stale: boolean;
  pending: boolean;
  error?: string | null;
  onRegenerate: (section: string | null, force?: boolean) => void;
  onDismiss: (section: string | null) => void;
}

/** Markdown-ish summary panel rendered at the top of a section.
 *
 *  The summary is short prose — render paragraphs and simple `- ` bullet
 *  lines without pulling in a full Markdown dependency.
 */
export const SectionSummaryPanel: React.FC<PanelProps> = ({
  entry,
  stale,
  pending,
  error,
  onRegenerate,
  onDismiss,
}) => {
  const lines = entry.summary_md.split('\n');
  return (
    <Paper
      withBorder
      radius="md"
      p="sm"
      mb="xs"
      style={{ borderColor: 'var(--mantine-color-violet-3)' }}
      data-testid={`ai-summary-panel-${entry.section ?? 'dashboard'}`}
    >
      <Stack gap={6}>
        <Group gap="xs" align="center">
          <Icon
            icon={AI_ICON}
            width={16}
            color="var(--mantine-color-violet-6)"
          />
          <Text size="sm" fw={600}>
            AI summary
          </Text>
          {stale && (
            <Tooltip label="The data or filters changed since this summary was generated">
              <Badge size="xs" variant="light" color="yellow">
                stale
              </Badge>
            </Tooltip>
          )}
          <Group gap={4} ml="auto">
            {stale && (
              <Button
                size="compact-xs"
                variant="light"
                color="violet"
                loading={pending}
                onClick={() => onRegenerate(entry.section, true)}
              >
                Regenerate
              </Button>
            )}
            <ActionIcon
              size="sm"
              variant="subtle"
              color="gray"
              onClick={() => onDismiss(entry.section)}
              aria-label="Dismiss summary"
            >
              <Icon icon="material-symbols:close" width={14} />
            </ActionIcon>
          </Group>
        </Group>
        {error && (
          <Alert color="red" variant="light" p="xs">
            <Text size="xs">{error}</Text>
          </Alert>
        )}
        <Stack gap={2}>
          {lines.map((line, i) =>
            line.trim().startsWith('- ') ? (
              <Text key={i} size="sm" pl="sm">
                • {line.trim().slice(2)}
              </Text>
            ) : line.trim() ? (
              <Text key={i} size="sm">
                {line}
              </Text>
            ) : null,
          )}
        </Stack>
        <Text size="xs" c="dimmed">
          Generated {entry.generated_at ? new Date(entry.generated_at).toLocaleString() : ''}
          {entry.model ? ` · ${entry.model.split('/').pop()}` : ''}
        </Text>
      </Stack>
    </Paper>
  );
};

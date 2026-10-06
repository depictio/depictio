import React, { useEffect, useMemo, useState } from 'react';
import { Anchor, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { fetchDashboard } from '../api';
import type { DashboardData, FigureStyleRequest, StoredMetadata } from '../api';
import { wrapWithChrome } from './chrome';
import ComponentSkeleton from './ComponentSkeleton';
import { useReportLoadStatus } from './DashboardLoadingProvider';
import {
  findHighlightSource,
  highlightMetadata,
  highlightStyleRequest,
  resolveHighlightTab,
} from './highlightTile';
import { useTabLinkResolver } from './tabLinks';
import type { TabLinkTarget } from './tabLinks';

/** What the host renders once the figure is found. */
export interface ResolvedHighlight {
  /** The source's metadata under the highlight's index, section and look. */
  metadata: StoredMetadata;
  /** Where the server finds the figure: its own tab and index. */
  renderSource: { dashboardId: string; componentId: string };
  styleRequest: FigureStyleRequest;
  /** The tab the figure comes from, when the family knows it. */
  sourceLink: TabLinkTarget | null;
}

/**
 * The source tabs' documents, shared by every highlight on the page and kept
 * a short while: a landing page with six highlights of one tab fetches it
 * once, and an edit made there shows up on the next visit.
 */
const SOURCE_TTL_MS = 30_000;
const sourceCache = new Map<string, { at: number; promise: Promise<DashboardData> }>();

function fetchSourceTab(dashboardId: string): Promise<DashboardData> {
  const hit = sourceCache.get(dashboardId);
  if (hit && Date.now() - hit.at < SOURCE_TTL_MS) return hit.promise;
  const promise = fetchDashboard(dashboardId);
  sourceCache.set(dashboardId, { at: Date.now(), promise });
  promise.catch(() => sourceCache.delete(dashboardId));
  return promise;
}

type State =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; source: StoredMetadata; dashboardId: string };

/** Stands in for the figure while it is looked up, or when it cannot be, and
 *  reports that to the dashboard's load bar under the highlight's index. */
const Placeholder: React.FC<{
  index: string;
  error?: string;
  link: TabLinkTarget | null;
}> = ({ index, error, link }) => {
  useReportLoadStatus(index, error ? 'error' : 'loading');
  if (!error) return <ComponentSkeleton variant="block" />;
  return (
    <Paper p="md" radius="md" withBorder style={{ height: '100%' }}>
      <Stack gap={6} justify="center" align="center" style={{ height: '100%' }}>
        <Icon icon="mdi:link-variant-off" width={22} color="var(--mantine-color-dimmed)" />
        <Text size="sm" c="dimmed" ta="center" data-testid="highlight-error">
          {error}
        </Text>
        {link && (
          <Anchor href={link.href} size="xs">
            Open {link.label}
          </Anchor>
        )}
      </Stack>
    </Paper>
  );
};

/**
 * A highlight tile: looks its figure up on the tab it lives on, then hands
 * the host what to render it with. The host (ComponentRenderer) draws it with
 * the same blocks as a figure or an advanced visualisation of this tab, so
 * filters, chrome and loading behave the same.
 */
const HighlightBlock: React.FC<{
  metadata: StoredMetadata;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
  children: (resolved: ResolvedHighlight) => React.ReactNode;
}> = ({ metadata, extraActions, showDragHandle, children }) => {
  const resolve = useTabLinkResolver();
  const { dashboardId, link } = resolveHighlightTab(metadata, resolve);
  const ref = metadata.source_component;
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    if (!dashboardId) {
      const tab = metadata.source_tab || metadata.source_dashboard_id;
      setState({
        status: 'error',
        message: tab ? `No tab “${tab}” in this dashboard.` : 'This highlight names no tab.',
      });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    fetchSourceTab(dashboardId)
      .then((dash) => {
        if (cancelled) return;
        const found = findHighlightSource(dash.stored_metadata, ref);
        const where = link?.label ?? dash.title ?? 'its tab';
        if (found.ok) {
          setState({ status: 'ready', source: found.component, dashboardId });
        } else if (found.reason === 'unsupported') {
          setState({
            status: 'error',
            message: `“${ref}” on ${where} is a ${found.component?.component_type} component; a highlight shows figures.`,
          });
        } else {
          setState({ status: 'error', message: `No figure “${ref ?? ''}” on ${where}.` });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setState({
            status: 'error',
            message: `The tab this figure comes from could not be loaded (${
              err instanceof Error ? err.message : String(err)
            }).`,
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // `link` is derived from the same inputs as `dashboardId`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, ref]);

  const resolved = useMemo<ResolvedHighlight | null>(() => {
    if (state.status !== 'ready') return null;
    const merged = highlightMetadata(metadata, state.source);
    return {
      metadata: merged,
      renderSource: { dashboardId: state.dashboardId, componentId: String(state.source.index) },
      styleRequest: highlightStyleRequest(merged),
      sourceLink: link,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, metadata, link?.href, link?.label]);

  if (resolved) return <>{children(resolved)}</>;
  return wrapWithChrome(
    'highlight',
    metadata,
    undefined,
    <Placeholder
      index={metadata.index}
      error={state.status === 'error' ? state.message : undefined}
      link={link}
    />,
    { extraActions, showDragHandle },
  );
};

export default HighlightBlock;

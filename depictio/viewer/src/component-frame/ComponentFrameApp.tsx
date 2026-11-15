/**
 * One dashboard component, standalone, at `/embed/{dashboardId}/{componentIndex}`.
 *
 * The analysis state travels in the URL hash (`#state=<base64url JSON>&theme=dark`)
 * so no server-side injection is needed: the real `ComponentRenderer` fetches
 * its data through the ordinary API with the caller's session, exactly as the
 * dashboard does. Two consumers:
 *
 * - the worker's headless Chromium, which loads this page to extract the Plotly
 *   figure of a React-rendered component (`services/embed/extract.py`);
 * - `depictio.notebook`'s `.html`, an iframe onto this page for readers who
 *   are logged into the instance.
 *
 * `data-embed-status` on the root reports `loading | ready | error | unsupported`
 * so a headless caller knows when to read the figure and when to give up. It
 * is the *renderer's* status, not the page's: `ready` only once the component
 * reported itself drawn (the same load registry the dashboard's progress bar
 * reads), `error` as soon as it reported a failure or threw, with the reason
 * in `data-embed-reason`. A headless caller can therefore screenshot an SVG,
 * canvas or WebGL renderer the moment it is done, instead of waiting for a
 * Plotly div that never comes.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Box, Center, Loader, useMantineColorScheme } from '@mantine/core';
import {
  ComponentRenderer,
  DashboardLoadingProvider,
  DataVersionProvider,
  TRACKED_LOAD_TYPES,
  bulkComputeCards,
  fetchDashboard,
  groupsRenderPayload,
  resolveGroupRender,
  type DashboardData,
  type GroupRenderState,
  type InteractiveFilter,
  type SelectionGroup,
  type StoredMetadata,
  useDashboardLoadSummary,
} from 'depictio-react-core';

interface EmbedState {
  filters?: InteractiveFilter[];
  groups?: SelectionGroup[];
  color_by?: { kind: 'none' | 'groups' | 'column'; column_name?: string | null };
  display_mode?: 'color' | 'facet';
  show_other?: boolean;
  compare_in_cards?: boolean;
  show_overall?: boolean;
  /** Time travel, as the render bodies spell it (`AnalysisState.pins`). */
  pins?: {
    as_of_version?: string | null;
    data_versions?: Record<string, number | null>;
    definition_version?: string | null;
  };
}

/** The pins as the renderers' context reads them, and as a request body. */
function pinsFromState(state: EmbedState) {
  const p = state.pins ?? {};
  const pins = p.data_versions && Object.keys(p.data_versions).length ? p.data_versions : undefined;
  const body: Record<string, unknown> = {};
  if (p.as_of_version) body.as_of_version = p.as_of_version;
  if (pins) body.data_versions = pins;
  if (p.definition_version) body.definition_version = p.definition_version;
  return {
    context: {
      asOfVersionId: p.as_of_version ?? null,
      pins,
      definitionVersionId: p.definition_version ?? null,
    },
    body,
  };
}

export function parseEmbedRoute(pathname: string): { dashboardId: string; componentId: string } | null {
  const m = pathname.match(/^\/embed\/([^/]+)\/([^/?#]+)/);
  return m ? { dashboardId: decodeURIComponent(m[1]), componentId: decodeURIComponent(m[2]) } : null;
}

export function decodeEmbedState(hash: string): { state: EmbedState; theme: 'light' | 'dark' | null } {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const theme = params.get('theme');
  const raw = params.get('state');
  let state: EmbedState = {};
  if (raw) {
    try {
      const b64 = raw.replace(/-/g, '+').replace(/_/g, '/');
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      state = JSON.parse(new TextDecoder().decode(bytes)) as EmbedState;
    } catch (err) {
      console.error('embed: cannot decode #state', err);
    }
  }
  return { state, theme: theme === 'dark' ? 'dark' : theme === 'light' ? 'light' : null };
}

function groupRenderFromState(state: EmbedState): GroupRenderState | undefined {
  const kind = state.color_by?.kind ?? 'none';
  if (kind === 'none') return undefined;
  const renderGroups = groupsRenderPayload(state.groups ?? []);
  const column = state.color_by?.column_name ? { columnName: state.color_by.column_name } : undefined;
  return resolveGroupRender(
    kind === 'groups' ? { kind: 'groups' } : { kind: 'column', columnName: column?.columnName ?? '' },
    renderGroups,
    column,
    state.display_mode ?? 'color',
    state.show_other ?? true,
  );
}

type Status = 'loading' | 'ready' | 'error' | 'unsupported';

/** The renderer's own verdict, read off the load registry it reports to. */
const RenderStatusProbe: React.FC<{
  meta: StoredMetadata;
  onStatus: (status: 'ready' | 'error') => void;
}> = ({ meta, onStatus }) => {
  const list = useMemo(() => [meta], [meta]);
  const summary = useDashboardLoadSummary(list, false);
  useEffect(() => {
    if (summary.error > 0) onStatus('error');
    else if (summary.ready > 0 && summary.loading === 0) onStatus('ready');
  }, [summary.error, summary.ready, summary.loading, onStatus]);
  return null;
};

/** A renderer that throws reports `error` rather than leaving the page loading. */
class FrameErrorBoundary extends React.Component<
  { children: React.ReactNode; onError: (message: string) => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    this.props.onError(error?.message || String(error));
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

const ComponentFrameApp: React.FC = () => {
  const route = useMemo(() => parseEmbedRoute(window.location.pathname), []);
  const { state, theme } = useMemo(() => decodeEmbedState(window.location.hash), []);
  const { setColorScheme } = useMantineColorScheme();
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);
  const [cardValue, setCardValue] = useState<unknown>(undefined);
  const [cardSecondary, setCardSecondary] = useState<Record<string, unknown> | undefined>();
  // The page is ready to draw (dashboard read, card values in hand); the
  // renderer then decides `status` itself through the load registry.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    if (theme) setColorScheme(theme);
  }, [theme, setColorScheme]);

  const filters = useMemo(() => state.filters ?? [], [state]);
  const groupRender = useMemo(() => groupRenderFromState(state), [state]);
  const versions = useMemo(() => pinsFromState(state), [state]);

  useEffect(() => {
    if (!route) {
      setError('Expected /embed/{dashboardId}/{componentIndex}');
      setStatus('error');
      return;
    }
    let cancelled = false;
    fetchDashboard(route.dashboardId)
      .then(async (d) => {
        if (cancelled) return;
        const meta = (d.stored_metadata ?? []).find((m) => String(m.index) === route.componentId);
        if (!meta) {
          setError(`No component ${route.componentId} in dashboard ${route.dashboardId}`);
          setStatus('error');
          return;
        }
        setDashboard(d);
        if (meta.component_type === 'card') {
          const res = await bulkComputeCards(
            route.dashboardId,
            filters,
            [String(meta.index)],
            {
              groups: groupRender?.groups,
              compareGroups: Boolean(state.compare_in_cards),
              showOther: state.show_other,
              showOverall: state.show_overall,
            },
            undefined,
            versions.body,
          );
          if (cancelled) return;
          setCardValue(res.values?.[String(meta.index)]);
          setCardSecondary(res.secondary_values?.[String(meta.index)]);
        }
        setMounted(true);
        // A type that reports no load lifecycle (a card already computed, a
        // text tile, a filter control) is drawn as soon as it mounts.
        if (!TRACKED_LOAD_TYPES.has(String(meta.component_type))) setStatus('ready');
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
    // filters/groupRender derive from the immutable hash state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route]);

  const meta: StoredMetadata | undefined = useMemo(() => {
    if (!dashboard || !route) return undefined;
    return (dashboard.stored_metadata ?? []).find((m) => String(m.index) === route.componentId);
  }, [dashboard, route]);

  const onRenderStatus = React.useCallback((next: 'ready' | 'error') => {
    // Terminal once decided: a renderer that re-reports `loading` for a
    // background refetch must not flip a page a headless caller already read.
    setStatus((prev) => (prev === 'loading' ? next : prev));
    if (next === 'error') setError((prev) => prev ?? 'The component reported an error.');
  }, []);
  const onRenderError = React.useCallback((message: string) => {
    setError(message);
    setStatus('error');
  }, []);

  return (
    <Box
      data-embed-status={status}
      data-embed-reason={status === 'error' ? (error ?? '') : undefined}
      data-component-type={meta?.component_type ?? ''}
      style={{ height: '100vh', width: '100%', padding: 8, boxSizing: 'border-box' }}
    >
      {status === 'error' && !mounted && (
        <Alert color="red" title="Cannot embed this component">
          {error}
        </Alert>
      )}
      {!mounted && status === 'loading' && (
        <Center h="100%">
          <Loader />
        </Center>
      )}
      {mounted && meta && route && (
        <DataVersionProvider {...versions.context} dashboardId={route.dashboardId}>
        <DashboardLoadingProvider>
          <RenderStatusProbe meta={meta} onStatus={onRenderStatus} />
          <Box className="react-grid-item" style={{ height: '100%', width: '100%' }}>
            <FrameErrorBoundary onError={onRenderError}>
              <ComponentRenderer
                metadata={meta}
                filters={filters}
                dashboardId={route.dashboardId}
                cardValue={cardValue}
                cardSecondaryValues={cardSecondary}
                cardLoading={false}
                groupRender={groupRender}
              />
            </FrameErrorBoundary>
          </Box>
        </DashboardLoadingProvider>
        </DataVersionProvider>
      )}
    </Box>
  );
};

export default ComponentFrameApp;

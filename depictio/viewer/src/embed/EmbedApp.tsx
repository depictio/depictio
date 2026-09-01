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
 * so a headless caller knows when to read the figure and when to give up.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Box, Center, Loader, useMantineColorScheme } from '@mantine/core';
import {
  ComponentRenderer,
  bulkComputeCards,
  fetchDashboard,
  groupsRenderPayload,
  resolveGroupRender,
  type DashboardData,
  type GroupRenderState,
  type InteractiveFilter,
  type SelectionGroup,
  type StoredMetadata,
} from 'depictio-react-core';

interface EmbedState {
  filters?: InteractiveFilter[];
  groups?: SelectionGroup[];
  color_by?: { kind: 'none' | 'groups' | 'column'; column_name?: string | null };
  display_mode?: 'color' | 'facet';
  show_other?: boolean;
  compare_in_cards?: boolean;
  show_overall?: boolean;
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

const EmbedApp: React.FC = () => {
  const route = useMemo(() => parseEmbedRoute(window.location.pathname), []);
  const { state, theme } = useMemo(() => decodeEmbedState(window.location.hash), []);
  const { setColorScheme } = useMantineColorScheme();
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);
  const [cardValue, setCardValue] = useState<unknown>(undefined);
  const [cardSecondary, setCardSecondary] = useState<Record<string, unknown> | undefined>();

  useEffect(() => {
    if (theme) setColorScheme(theme);
  }, [theme, setColorScheme]);

  const filters = useMemo(() => state.filters ?? [], [state]);
  const groupRender = useMemo(() => groupRenderFromState(state), [state]);

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
          const res = await bulkComputeCards(route.dashboardId, filters, [String(meta.index)], {
            groups: groupRender?.groups,
            compareGroups: Boolean(state.compare_in_cards),
            showOther: state.show_other,
            showOverall: state.show_overall,
          });
          if (cancelled) return;
          setCardValue(res.values?.[String(meta.index)]);
          setCardSecondary(res.secondary_values?.[String(meta.index)]);
        }
        setStatus('ready');
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

  return (
    <Box
      data-embed-status={status}
      data-component-type={meta?.component_type ?? ''}
      style={{ height: '100vh', width: '100%', padding: 8, boxSizing: 'border-box' }}
    >
      {status === 'error' && (
        <Alert color="red" title="Cannot embed this component">
          {error}
        </Alert>
      )}
      {status === 'loading' && (
        <Center h="100%">
          <Loader />
        </Center>
      )}
      {status === 'ready' && meta && route && (
        <Box className="react-grid-item" style={{ height: '100%', width: '100%' }}>
          <ComponentRenderer
            metadata={meta}
            filters={filters}
            dashboardId={route.dashboardId}
            cardValue={cardValue}
            cardSecondaryValues={cardSecondary}
            cardLoading={false}
            groupRender={groupRender}
          />
        </Box>
      )}
    </Box>
  );
};

export default EmbedApp;

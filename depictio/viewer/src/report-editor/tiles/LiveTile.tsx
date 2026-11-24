/**
 * One component of the dashboard drawn by the app's own renderer, the way
 * `component-frame/ComponentFrameApp.tsx` draws it standalone: the same
 * providers, the same bulk compute for cards, the same load registry for its
 * verdict. Nothing of its own around it: no padding, border or background.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ComponentRenderer,
  DashboardLoadingProvider,
  DataVersionProvider,
  TRACKED_LOAD_TYPES,
  groupsRenderPayload,
  hasLiveValues,
  resolveGroupRender,
  useDashboardLoadSummary,
} from 'depictio-react-core';
import type {
  AnalysisState,
  GroupRenderState,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';
import { Box } from '@mantine/core';

import { stateFilters } from '../model';
import { computeCardValue } from './cardValues';
import type { CardValue } from './cardValues';

/** State changes (a filter typed, a group edited) redraw once they settle. */
const DEBOUNCE_MS = 400;

export type LiveStatus = 'ready' | 'error';

function useDebounced<T>(value: T, key: string): T {
  const [out, setOut] = useState(value);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const timer = window.setTimeout(() => setOut(value), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
    // The key stands for the value: the object is rebuilt on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return out;
}

/** The colour-by of the report's state as the renderers take it. */
function groupRenderOf(state: AnalysisState | null): GroupRenderState | undefined {
  const kind = state?.color_by?.kind ?? 'none';
  if (!state || kind === 'none') return undefined;
  const defs = groupsRenderPayload(
    (state.groups ?? []).map((g) => ({
      id: g.id,
      name: g.name,
      color: g.color,
      dcId: g.dc_id ?? undefined,
      columnName: g.column_name,
      values: g.values,
      createdAt: g.created_at,
      filterActive: g.filter_active,
    })),
  );
  const column = state.color_by.column_name ? { columnName: state.color_by.column_name } : undefined;
  return resolveGroupRender(
    kind === 'groups' ? { kind: 'groups' } : { kind: 'column', columnName: column?.columnName ?? '' },
    defs,
    column,
    state.display_mode ?? 'color',
    state.show_other ?? true,
  );
}

/** The renderer's own verdict, read off the load registry it reports to. */
const StatusProbe: React.FC<{ meta: StoredMetadata; onStatus: (s: LiveStatus) => void }> = ({
  meta,
  onStatus,
}) => {
  const list = useMemo(() => [meta], [meta]);
  const summary = useDashboardLoadSummary(list, false);
  useEffect(() => {
    if (summary.error > 0) onStatus('error');
    else if (summary.ready > 0 && summary.loading === 0) onStatus('ready');
  }, [summary.error, summary.ready, summary.loading, onStatus]);
  return null;
};

/** A renderer that throws is a failed tile, not a broken page. */
class TileBoundary extends React.Component<
  { children: React.ReactNode; onError: () => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

interface LiveTileProps {
  /** The tab's dashboard id: what the render endpoints are asked against. */
  tabId: string;
  metadata: StoredMetadata;
  /** The report's analysis state (filters, groups, pins); none = unfiltered. */
  state: AnalysisState | null;
  /** The report's own dashboard, for the chrome's source. */
  rootDashboardId?: string;
  /** Called once, when the component is drawn or has failed. */
  onStatus?: (status: LiveStatus) => void;
}

const LiveTile: React.FC<LiveTileProps> = ({ tabId, metadata, state, onStatus }) => {
  const filtersNow = useMemo(() => stateFilters(state), [state]);
  const stateKey = useMemo(() => JSON.stringify(state ?? null), [state]);
  const filters: InteractiveFilter[] = useDebounced(filtersNow, stateKey);
  const groupRender = useDebounced(useMemo(() => groupRenderOf(state), [state]), stateKey);
  const pins = state?.pins;
  const pinKey = JSON.stringify(pins ?? null);
  const versions = useMemo(
    () => ({
      asOfVersionId: pins?.as_of_version ?? null,
      pins: pins && Object.keys(pins.data_versions ?? {}).length ? pins.data_versions : undefined,
      definitionVersionId: pins?.definition_version ?? null,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pinKey],
  );

  // Cards, and text tiles with live values (`{{name}}`), take their values
  // from the tab's bulk compute, as on the dashboard.
  const isCard = metadata.component_type === 'card' || hasLiveValues(metadata);
  // A thumbnail shows the figure, not its controls: an advanced
  // visualisation keeps them behind its settings icon here.
  const drawn = useMemo<StoredMetadata>(
    () =>
      metadata.component_type === 'advanced_viz'
        ? ({
            ...metadata,
            // The dock, and the placement the dashboard may have set
            // (a phylogeny's controls under its title).
            controls_placement: 'popover',
            config: {
              ...((metadata.config as Record<string, unknown> | undefined) ?? {}),
              controls_placement: 'popover',
            },
          } as StoredMetadata)
        : metadata,
    [metadata],
  );
  const [card, setCard] = useState<CardValue | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const settled = useRef(false);

  const report = React.useCallback(
    (status: LiveStatus) => {
      // The first verdict stands: a later refetch error must not blank a drawn tile.
      if (settled.current) return;
      settled.current = true;
      if (status === 'error') setFailed(true);
      onStatus?.(status);
    },
    [onStatus],
  );

  // Cards take their value from the tab's bulk compute, as on the dashboard.
  useEffect(() => {
    if (!isCard) return;
    let cancelled = false;
    computeCardValue(tabId, String(metadata.index), filters, {
      groups: groupRender?.groups,
      compareGroups: Boolean(state?.compare_in_cards),
      showOther: state?.show_other,
      showOverall: state?.show_overall,
    })
      .then((v) => {
        if (cancelled) return;
        setCard(v);
        // A card reports no load lifecycle: it is drawn once its value is in.
        report('ready');
      })
      .catch(() => {
        if (!cancelled) report('error');
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCard, tabId, metadata.index, filters, groupRender]);

  // A type that reports no load lifecycle and is not a card (text, a filter
  // control) is drawn as soon as it mounts.
  useEffect(() => {
    if (!isCard && !TRACKED_LOAD_TYPES.has(String(metadata.component_type))) report('ready');
  }, [isCard, metadata.component_type, report]);

  if (failed) return null;
  return (
    <DataVersionProvider {...versions} dashboardId={tabId}>
      <DashboardLoadingProvider>
        {TRACKED_LOAD_TYPES.has(String(metadata.component_type)) && (
          <StatusProbe meta={metadata} onStatus={report} />
        )}
        <Box className="react-grid-item" style={{ height: '100%', width: '100%' }}>
          <TileBoundary onError={() => report('error')}>
            <ComponentRenderer
              metadata={drawn}
              filters={filters}
              dashboardId={tabId}
              cardValue={card?.value}
              cardSecondaryValues={card?.secondary}
              cardLoading={isCard && card === undefined}
              groupRender={groupRender}
            />
          </TileBoundary>
        </Box>
      </DashboardLoadingProvider>
    </DataVersionProvider>
  );
};

export default LiveTile;

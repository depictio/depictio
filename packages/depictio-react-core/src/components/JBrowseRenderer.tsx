import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Group,
  Text,
  Tooltip,
  useComputedColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { createViewState } from '@jbrowse/react-linear-genome-view2';
import { readConfObject } from '@jbrowse/core/configuration';
import { LoadingEllipses, createJBrowseTheme } from '@jbrowse/core/ui';
import { useWidthSetter } from '@jbrowse/core/util';
import { ModalWidget } from '@jbrowse/embedded-core';
import { getEnv } from '@jbrowse/mobx-state-tree';
import GtfPlugin from '@jbrowse/plugin-gtf';
import { Paper, ScopedCssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { reaction } from 'mobx';
import { observer } from 'mobx-react';

import {
  fetchJBrowseSession,
  InteractiveFilter,
  JBrowseSessionResponse,
  StoredMetadata,
} from '../api';
import { filtersExcludingOwn } from '../selection';
import ComponentSkeleton from './ComponentSkeleton';
import RefetchOverlay from './RefetchOverlay';
import { useReportLoadStatus } from './DashboardLoadingProvider';
import {
  jbrowseSelectionFilter,
  planTrackSync,
  selectionValuesFor,
  toggleValue,
} from './jbrowse/trackSync';

type ViewState = ReturnType<typeof createViewState>;

/** Signed track URLs live `url_ttl_s` (6 h by default) server-side; rebuild the
 *  view well before that so a long-open dashboard never reads with a stale one. */
const VIEW_MAX_AGE_MS = 3 * 60 * 60 * 1000;

export interface JBrowseToolbarState {
  showHeader: boolean;
  showOverview: boolean;
  showStatus: boolean;
  clickFilters: boolean;
}

interface JBrowseRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** Receives ``source="jbrowse_selection"`` filters (``value: []`` clears). */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
  /** Hands the header/overview/status toggles up to the chrome action row. */
  onToolbarNode?: (node: React.ReactNode) => void;
}

function readToggle(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v == null ? fallback : v === '1';
  } catch {
    return fallback;
  }
}

function writeToggle(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // Private mode / blocked storage: the toggle just won't persist.
  }
}

/** Absolute URLs for every ``UriLocation``: JBrowse resolves relative ones
 *  against its own config base, not the page, so the API paths the backend
 *  returns are anchored on the page origin here. */
function absolutize<T>(node: T): T {
  if (Array.isArray(node)) return node.map(absolutize) as unknown as T;
  if (node && typeof node === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      out[k] =
        k === 'uri' && typeof v === 'string' && v.startsWith('/')
          ? new URL(v, window.location.origin).toString()
          : absolutize(v);
    }
    return out as T;
  }
  return node;
}

/** MUI renders JBrowse's dialogs and menus in portals on ``document.body``;
 *  while the tile is in native fullscreen only the fullscreen element's
 *  subtree is painted, so point every portal at it instead. */
const portalContainer = (): HTMLElement =>
  (document.fullscreenElement as HTMLElement | null) ?? document.body;

/**
 * The linear genome view without JBrowse's own title bar (hamburger, view
 * name, logo): Depictio's chrome already frames the tile. Mirrors
 * `EmbeddedViewContainer` + `JBrowseLinearGenomeView` from the LGV package.
 */
const EmbeddedLGV = observer(function EmbeddedLGV({
  viewState,
  muiThemeOverrides,
}: {
  viewState: ViewState;
  muiThemeOverrides: Record<string, unknown>;
}) {
  const { session } = viewState;
  const { view } = session;
  const { pluginManager } = getEnv(session);
  const { ReactComponent } = pluginManager.getViewType(view.type);
  const theme = useMemo(
    () =>
      createTheme(
        createJBrowseTheme(readConfObject(viewState.config.configuration, 'theme')),
        muiThemeOverrides,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(readConfObject(viewState.config.configuration, 'theme')), muiThemeOverrides],
  );
  const widthRef = useWidthSetter(view, '0px');
  return (
    <ThemeProvider theme={theme}>
      <div style={{ all: 'initial', display: 'block' }}>
        <ScopedCssBaseline>
          <Paper
            ref={widthRef as React.RefObject<HTMLDivElement>}
            elevation={0}
            square
            style={{ overflow: 'hidden' }}
          >
            {session.DialogComponent ? (
              <Suspense fallback={null}>
                <session.DialogComponent {...session.DialogProps} />
              </Suspense>
            ) : null}
            <Suspense fallback={<LoadingEllipses />}>
              <ReactComponent model={view} session={session} />
            </Suspense>
          </Paper>
        </ScopedCssBaseline>
      </div>
      <ModalWidget session={session} />
    </ThemeProvider>
  );
});

/**
 * Genome browser tile (``component_type: jbrowse``).
 *
 * The backend (``POST /dashboards/render_jbrowse``) turns the dashboard filters
 * into the list of tracks to show; this component keeps ONE JBrowse view alive
 * and diffs it towards that list (show / hide / lazily add track configs), so
 * a filter change never reloads the browser or loses the user's locus.
 *
 * Inverse direction: clicking a feature (``selection_mode: feature_click``) or
 * changing the open tracks (``visible_tracks``) emits a ``jbrowse_selection``
 * filter on the manifest's selection column, which link resolution carries to
 * the rest of the dashboard — the same round trip as the image gallery.
 */
const JBrowseRenderer: React.FC<JBrowseRendererProps> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  onToolbarNode,
}) => {
  const mantineTheme = useMantineTheme();
  const colorScheme = useComputedColorScheme('light');
  const [payload, setPayload] = useState<JBrowseSessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewState, setViewState] = useState<ViewState | null>(null);
  const viewMeta = useRef<{ assembly: string; createdAt: number; location: string | null }>({
    assembly: '',
    createdAt: 0,
    location: null,
  });
  // Track ids this component manages (the manifest's): user-opened tracks
  // outside this set (annotation, from the track selector) are never hidden.
  const managedIds = useRef<Set<string>>(new Set());

  const selectionEnabled = Boolean(metadata.selection_enabled) && !!onFilterChange;
  const selectionMode = (metadata.selection_mode as string) || 'feature_click';

  // ---- toggles (defaults from the YAML, then per-viewer localStorage) ------
  const storageKey = `depictio.jbrowse.${metadata.index}`;
  const [toolbar, setToolbar] = useState<JBrowseToolbarState>(() => ({
    showHeader: readToggle(`${storageKey}.header`, metadata.show_header !== false),
    showOverview: readToggle(`${storageKey}.overview`, metadata.show_overview !== false),
    showStatus: readToggle(`${storageKey}.status`, true),
    clickFilters: readToggle(`${storageKey}.clickFilters`, true),
  }));
  const setToggle = useCallback(
    (key: keyof JBrowseToolbarState, suffix: string) => {
      setToolbar((prev) => {
        const next = { ...prev, [key]: !prev[key] };
        writeToggle(`${storageKey}.${suffix}`, next[key]);
        return next;
      });
    },
    [storageKey],
  );

  // ---- fetch -----------------------------------------------------------------
  const fetchFilters = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'jbrowse_selection'),
    [filters, metadata.index],
  );
  const filtersKey = JSON.stringify(fetchFilters);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchJBrowseSession(dashboardId, metadata.index, fetchFilters)
      .then((res) => {
        if (!cancelled) setPayload(res);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, filtersKey, refreshTick]);

  useReportLoadStatus(
    metadata.index,
    payload != null ? 'ready' : error ? 'error' : 'loading',
  );

  // ---- JBrowse theme from Mantine ------------------------------------------
  const jbTheme = useMemo(() => {
    const primary = mantineTheme.colors[mantineTheme.primaryColor] ?? mantineTheme.colors.blue;
    const dark = colorScheme === 'dark';
    return {
      palette: {
        mode: dark ? 'dark' : 'light',
        primary: { main: primary[dark ? 4 : 7] },
        secondary: { main: primary[dark ? 3 : 6] },
        tertiary: { main: mantineTheme.colors.teal[dark ? 4 : 7] },
        quaternary: { main: mantineTheme.colors.orange[dark ? 4 : 7] },
      },
    };
  }, [mantineTheme, colorScheme]);

  const muiThemeOverrides = useMemo(
    () => ({
      components: {
        MuiModal: { defaultProps: { container: portalContainer } },
        MuiPopper: { defaultProps: { container: portalContainer } },
        MuiPopover: { defaultProps: { container: portalContainer } },
      },
    }),
    [],
  );

  // ---- create / sync the view ----------------------------------------------
  useEffect(() => {
    if (!payload) return;
    const assemblyName = String(payload.assembly.name ?? '');
    const tracks = absolutize(payload.tracks);
    for (const row of payload.track_rows) managedIds.current.add(row.track_id);

    const stale = Date.now() - viewMeta.current.createdAt > VIEW_MAX_AGE_MS;
    if (!viewState || viewMeta.current.assembly !== assemblyName || stale) {
      const state = createViewState({
        assembly: absolutize(payload.assembly),
        tracks,
        plugins: [GtfPlugin],
        configuration: {
          ...payload.configuration,
          theme: jbTheme,
        },
        defaultSession: {
          name: `depictio-${metadata.index}`,
          view: {
            id: `lgv-${metadata.index}`,
            type: 'LinearGenomeView',
            ...payload.view,
            hideHeader: !toolbar.showHeader,
            hideHeaderOverview: !toolbar.showOverview,
            init: {
              assembly: assemblyName,
              loc: payload.location ?? undefined,
              tracks: payload.shown_track_ids,
            },
          },
        },
      } as Parameters<typeof createViewState>[0]);
      viewMeta.current = {
        assembly: assemblyName,
        createdAt: Date.now(),
        location: payload.location,
      };
      setViewState(state);
      return;
    }

    // Same assembly: diff the open tracks towards the payload.
    const { session } = viewState;
    const view = session.view;
    const known = new Set<string>(
      (session.tracks as Array<{ trackId: string }>).map((t) => t.trackId),
    );
    for (const conf of tracks) {
      if (!known.has(conf.trackId)) session.addTrackConf(conf);
    }
    const open = (view.tracks as Array<{ configuration: { trackId: string } }>).map(
      (t) => t.configuration.trackId,
    );
    const plan = planTrackSync(open, payload.shown_track_ids, managedIds.current);
    for (const id of plan.hide) view.hideTrack(id);
    for (const id of plan.show) {
      try {
        view.showTrack(id);
      } catch (err) {
        console.warn(`jbrowse: cannot show track ${id}`, err);
      }
    }
    if (payload.location && payload.location !== viewMeta.current.location) {
      viewMeta.current.location = payload.location;
      view.navToLocString(payload.location).catch((err: unknown) => {
        console.warn('jbrowse: navigation failed', err);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload]);

  // Theme follows the Mantine colour scheme without rebuilding the view.
  useEffect(() => {
    if (!viewState) return;
    try {
      viewState.config.configuration.theme.set(jbTheme);
    } catch {
      // Frozen slot on an older build: the next rebuild picks the theme up.
    }
  }, [viewState, jbTheme]);

  // Header / overview toggles drive the live view model.
  useEffect(() => {
    if (!viewState) return;
    const view = viewState.session.view;
    view.setHideHeader(!toolbar.showHeader);
    view.setHideHeaderOverview(!toolbar.showOverview);
  }, [viewState, toolbar.showHeader, toolbar.showOverview]);

  // Fullscreen / tile resize: JBrowse measures its container, but a synthetic
  // resize after a fullscreen flip lets it pick the new width up immediately.
  useEffect(() => {
    const onFs = () => window.requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, []);

  // ---- inverse direction: JBrowse → dashboard filter ------------------------
  const rowsRef = useRef(payload?.track_rows ?? []);
  rowsRef.current = payload?.track_rows ?? [];
  const selectedRef = useRef<string[]>([]);
  const ownFilter = filters.find(
    (f) => f.index === metadata.index && f.source === 'jbrowse_selection',
  );
  useEffect(() => {
    // Cleared from outside (reset icon, "reset all"): drop the local set too.
    selectedRef.current = Array.isArray(ownFilter?.value) ? (ownFilter!.value as string[]) : [];
  }, [ownFilter]);

  const emit = useCallback(
    (values: string[]) => {
      if (!onFilterChange || !payload?.selection_column) return;
      selectedRef.current = values;
      onFilterChange(
        jbrowseSelectionFilter(
          metadata.index,
          payload.selection_column,
          payload.tracks_dc_id,
          values,
        ),
      );
    },
    [onFilterChange, payload?.selection_column, payload?.tracks_dc_id, metadata.index],
  );

  useEffect(() => {
    if (!viewState || !selectionEnabled || !payload?.selection_column) return;
    const { session } = viewState;
    if (selectionMode === 'visible_tracks') {
      let timer: number | undefined;
      const dispose = reaction(
        () =>
          (session.view.tracks as Array<{ configuration: { trackId: string } }>).map(
            (t) => t.configuration.trackId,
          ),
        (ids) => {
          window.clearTimeout(timer);
          timer = window.setTimeout(() => emit(selectionValuesFor(ids, rowsRef.current)), 400);
        },
      );
      return () => {
        window.clearTimeout(timer);
        dispose();
      };
    }
    // feature_click: JBrowse opens a BaseFeatureWidget for the clicked feature;
    // read the track off it, turn it into a filter, and (unless the user
    // switched click-to-filter off) close the details dialog it would show.
    return reaction(
      () => session.visibleWidget,
      (widget: { type?: string; track?: { configuration?: { trackId?: string } } } | undefined) => {
        if (!widget || widget.type !== 'BaseFeatureWidget' || !toolbarRef.current.clickFilters)
          return;
        const trackId = widget.track?.configuration?.trackId;
        const [value] = trackId ? selectionValuesFor([trackId], rowsRef.current) : [];
        session.hideAllWidgets();
        if (value == null) return;
        emit(toggleValue(selectedRef.current, value));
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewState, selectionEnabled, selectionMode, payload?.selection_column, emit]);
  const toolbarRef = useRef(toolbar);
  toolbarRef.current = toolbar;

  // ---- chrome toggles -------------------------------------------------------
  useEffect(() => {
    if (!onToolbarNode) return;
    const item = (
      key: string,
      label: string,
      icon: string,
      active: boolean,
      onClick: () => void,
    ) => (
      <Tooltip key={key} label={label} withinPortal={false}>
        <ActionIcon
          variant={active ? 'light' : 'subtle'}
          size="sm"
          aria-pressed={active}
          aria-label={label}
          data-testid={`jbrowse-toggle-${key}`}
          onClick={onClick}
        >
          <Icon icon={icon} width={16} />
        </ActionIcon>
      </Tooltip>
    );
    onToolbarNode(
      <React.Fragment key="jbrowse-toolbar">
        {item(
          'header',
          toolbar.showHeader ? 'Hide navigation header' : 'Show navigation header',
          'mdi:dock-top',
          toolbar.showHeader,
          () => setToggle('showHeader', 'header'),
        )}
        {item(
          'overview',
          toolbar.showOverview ? 'Hide overview ruler' : 'Show overview ruler',
          'mdi:ruler',
          toolbar.showOverview,
          () => setToggle('showOverview', 'overview'),
        )}
        {item(
          'status',
          toolbar.showStatus ? 'Hide status bar' : 'Show status bar',
          'mdi:dock-bottom',
          toolbar.showStatus,
          () => setToggle('showStatus', 'status'),
        )}
        {selectionEnabled && selectionMode === 'feature_click'
          ? item(
              'click',
              toolbar.clickFilters
                ? 'Clicking a feature filters the dashboard (click to show details instead)'
                : 'Clicking a feature shows its details (click to filter instead)',
              toolbar.clickFilters ? 'mdi:filter-outline' : 'mdi:information-outline',
              toolbar.clickFilters,
              () => setToggle('clickFilters', 'clickFilters'),
            )
          : null}
      </React.Fragment>,
    );
  }, [onToolbarNode, toolbar, setToggle, selectionEnabled, selectionMode]);
  useEffect(() => () => onToolbarNode?.(null), [onToolbarNode]);

  // ---- render ----------------------------------------------------------------
  const statusText = payload
    ? `${payload.shown_track_ids.length} shown · ${payload.matched_tracks}/${payload.total_tracks} tracks${
        payload.filter_applied ? ' match the filters' : ''
      }${payload.truncated ? ` (first ${metadata.max_tracks ?? 20})` : ''}`
    : '';
  const selectedCount = Array.isArray(ownFilter?.value) ? (ownFilter!.value as unknown[]).length : 0;

  return (
    <Box
      data-testid="jbrowse-component"
      data-jbrowse-ready={viewState ? 'true' : 'false'}
      style={{
        position: 'relative',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
    >
      {metadata.title && (
        <Group gap="xs" px="xs" pt={6} pb={4} wrap="nowrap" style={{ flexShrink: 0, minWidth: 0 }}>
          <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>
            {metadata.title as string}
          </Text>
          {typeof metadata.description === 'string' && metadata.description && (
            <Text c="dimmed" size="xs" truncate style={{ minWidth: 0 }}>
              {metadata.description as string}
            </Text>
          )}
        </Group>
      )}
      {payload === null && loading && <ComponentSkeleton variant="block" />}
      {error && !payload && (
        <Text size="sm" c="red" p="md" className="dashboard-error">
          Genome browser failed: {error}
        </Text>
      )}
      {viewState && (
        <Box style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}>
          <EmbeddedLGV viewState={viewState} muiThemeOverrides={muiThemeOverrides} />
        </Box>
      )}
      {viewState && toolbar.showStatus && payload && (
        <Group
          gap="xs"
          px="xs"
          py={2}
          wrap="nowrap"
          data-testid="jbrowse-status"
          style={{ borderTop: '1px solid var(--mantine-color-default-border)', flexShrink: 0 }}
        >
          <Icon icon="mdi:dna" width={14} />
          <Text size="xs" c="dimmed" truncate>
            {statusText}
          </Text>
          {payload.filter_applied && (
            <Badge size="xs" variant="light">
              filtered
            </Badge>
          )}
          {selectedCount > 0 && (
            <Badge size="xs" variant="filled">
              {selectedCount} selected
            </Badge>
          )}
        </Group>
      )}
      <RefetchOverlay visible={loading && payload !== null} />
    </Box>
  );
};

export default JBrowseRenderer;

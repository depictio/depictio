import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  ColorSwatch,
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
import { getEnv, isAlive } from '@jbrowse/mobx-state-tree';
import GtfPlugin from '@jbrowse/plugin-gtf';
import { Paper, ScopedCssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { comparer, reaction } from 'mobx';
import { observer } from 'mobx-react';

import {
  fetchJBrowseSession,
  InteractiveFilter,
  JBrowseCall,
  JBrowseSessionResponse,
  JBrowseTrackRow,
  StoredMetadata,
} from '../api';
import { useDataVersionRequest } from '../dataVersions';
import { useHighlight, usePublishHighlight } from '../highlight/bus';
import {
  sameViewWindow,
  usePublishViewWindow,
  useViewWindow,
  type ViewWindowEvent,
} from '../highlight/viewWindow';
import { useCategoryColorSource, useCategoryPalette } from '../hooks/useCategoryColors';
import { renderDefinitionKey } from '../renderKey';
import { filtersExcludingOwn, isRegionFilter } from '../selection';
import ComponentSkeleton from './ComponentSkeleton';
import RefetchOverlay from './RefetchOverlay';
import { useReportLoadStatus } from './DashboardLoadingProvider';
import JBrowseDataPopover from './jbrowse/JBrowseDataPopover';
import FeatureDetails from './jbrowse/FeatureDetails';
import type { RegionGridProps } from './jbrowse/RegionPicker';
import VizKindBadge, { AdvancedVizKindContext } from './advanced_viz/VizKindBadge';
import { useDensity } from './density';
import {
  jbrowseSelectionFilter,
  planTrackSync,
  selectionValuesFor,
  toggleValue,
} from './jbrowse/trackSync';
import { hideAllIds, manifestTrackIds, withSectionCategory } from './jbrowse/trackMenuModel';
import CallNavigator from './jbrowse/CallNavigator';
import DensityStrip from './jbrowse/DensityStrip';
import { defaultDensityGroup, type DensityGroup } from './jbrowse/densityBins';
import { useGenomeBrowserTarget } from './jbrowse/browserTarget';
import { naturalChromOrder } from './jbrowse/chromOrder';
import { MAX_FOLLOW_SPAN, followTarget } from './jbrowse/followWindow';
import {
  genomeSelectionRegion,
  genomeSelectionSource,
  regionNavTarget,
  windowLocus,
} from './jbrowse/locusForAction';
import LinkedTileChip from './genomeLink/LinkedTileChip';
import { tileTitle } from './genomeLink/linkedTile';
import { describeFilters, traceGenome } from './genomeLink/genomeDebug';
import { compactRegion } from './advanced_viz/genomespy/overlayRows';
import {
  PENDING_LOCUS_EVENT,
  pendingLocusFor,
  takePendingLocus,
} from './jbrowse/pendingLocus';
import DepictioGeneSearchPlugin, { geneSearchAdapterConfigs } from './jbrowse/geneSearch';
import JBrowseViewsModal, {
  EXTRA_VIEW_TITLE,
  type JBrowseExtraView,
} from './jbrowse/JBrowseViewsModal';
import {
  PERSISTED_LOCUS_SUFFIX,
  initialLocus,
  shouldRenavigate,
  sidesLocus,
  wideRegionTarget,
} from './jbrowse/openingLocus';
import { trackRowsToColumns } from './jbrowse/trackRowsData';
import { alignmentTrackIds, initTrackEntry, pairsDisplaySnapshot } from './jbrowse/readPairs';
import { useCallNavigator } from './jbrowse/useCallNavigator';
import { useCallDensity } from './jbrowse/useCallDensity';
import type { VisibleRegion } from './jbrowse/navigatorSteps';
import { locusSources } from './jbrowse/locusSources';
import { viewLeavesRegion, withAlpha } from './jbrowse/locusHighlight';
import {
  hoverBand,
  hoverEventFromFeature,
  watchFeatureHover,
  type HoverFeature,
} from './jbrowse/featureHover';
import {
  createRegionSelectPlugin,
  isOwnRegion,
  ownRegionOf,
  regionFiltersFor,
  withoutOwnRegion,
  type JBrowseRegion,
  type RegionSelectHandle,
} from './jbrowse/regionSelection';
import {
  setGenomeTracksColours,
  setGenomeTracksLocus,
  setGenomeTracksPayload,
} from './jbrowse/genomeTracksStore';
import { legendRamp, trackLegend } from './jbrowse/trackLegend';
import { categoryColorMap, readColorScale } from '../categoryColors';
import {
  canonicalRefName,
  createAliasLookup,
  cursorLocus,
  visibleWindow,
  type RefNameAliases,
  type VisibleBlock,
} from './jbrowse/viewCursor';
import {
  colourAlignmentTracks,
  colourTracksBy,
  conditionColourMap,
  conditionOf,
  conditionSequentialMap,
  sampleColourColumn,
  sampleColourMap,
  trackColoursBy,
} from './jbrowse/sampleColors';
import {
  hasLiftedLimits,
  liftDisplayLimits,
  planForceLoadReset,
} from './jbrowse/forceLoad';
import TrackMenu from './jbrowse/TrackMenu';
import ViewMenu, { type ViewMenuItem } from './jbrowse/ViewMenu';
import { useDisplaySettings } from './jbrowse/useDisplaySettings';
import { useSharedScale } from './jbrowse/useSharedScale';
import { useFitTracks } from './jbrowse/useFitTracks';
import { useJBrowseAutoHeight } from './jbrowse/useAutoHeight';
import { canScrollBy, wheelIntent, wheelPixels, zoomFactor } from './jbrowse/wheel';
import { attachZoomGate } from './zoomGateDom';

/** Hidden for now: JBrowse's own track selector (the toolbar burger) is the
 *  only track picker, so the two never disagree. Flip to re-enable the menu. */
const SHOW_TRACK_MENU = false;

type ViewState = ReturnType<typeof createViewState>;

/** The slice of the LinearGenomeView model this component reads. */
interface LgvTrack {
  configuration: { trackId: string };
  displays?: unknown[];
}
interface LgvView {
  tracks: LgvTrack[];
  bpPerPx: number;
  /** The visible locus as a string ("chr8:1..2"), or '' before the blocks exist. */
  visibleLocStrings: string;
  showTrack: (
    trackId: string,
    snapshot?: Record<string, unknown>,
    displaySnapshot?: Record<string, unknown>,
  ) => unknown;
  hideTrack: (trackId: string) => unknown;
  /** Clamps to the view's zoom limits; `offset` (px) is the point held still. */
  zoomTo: (bpPerPx: number, offset?: number) => unknown;
  /** Replaces the highlight bands (0-based start, end exclusive). */
  setHighlight: (
    bands: Array<{
      refName: string;
      start: number;
      end: number;
      assemblyName?: string;
      color?: string;
    }>,
  ) => unknown;
  displayedRegions?: Array<{ refName: string }>;
  /** Locus under a pixel offset from the left edge of the tracks area. */
  pxToBp: (px: number) => { refName: string; coord: number; oob?: boolean };
  /** The blocks on screen (0-based start, end exclusive). */
  dynamicBlocks?: { contentBlocks: VisibleBlock[] };
}

/** ``isAlive`` throws on anything that is not a state-tree node. */
const aliveNode = (node: unknown): boolean => {
  try {
    return isAlive(node as Parameters<typeof isAlive>[0]);
  } catch {
    return false;
  }
};

/** The view's visible locus, or '' before it has measured its width (JBrowse
 *  throws "check model.initialized" from a reaction that reads it too early). */
const locStringsOf = (view: LgvView): string => {
  if (!aliveNode(view)) return '';
  try {
    return view.visibleLocStrings;
  } catch {
    return '';
  }
};

/** The regions on screen (0-based, end-exclusive), [] before the view is measured. */
const visibleRegionsOf = (view: LgvView): VisibleRegion[] => {
  if (!aliveNode(view)) return [];
  try {
    const blocks = (view as unknown as {
      dynamicBlocks: { contentBlocks: Array<{ refName: string; start: number; end: number }> };
    }).dynamicBlocks.contentBlocks;
    return blocks.map((b) => ({ refName: b.refName, start: b.start, end: b.end }));
  } catch {
    return [];
  }
};

/** The assembly's regions, in natural order, [] until the assembly has loaded. */
const assemblyRegionsOf = (
  session: unknown,
  name: string,
): { refName: string; length: number }[] => {
  try {
    const asm = (session as {
      assemblyManager?: { get: (n: string) => { regions?: Array<{ refName: string; end: number }> } | undefined };
    }).assemblyManager?.get(name);
    return naturalChromOrder((asm?.regions ?? []).map((r) => ({ refName: r.refName, length: r.end })));
  } catch {
    return [];
  }
};

const openTrackIds = (view: LgvView): string[] =>
  view.tracks.map((t) => t.configuration.trackId);

/** Signed track URLs live `url_ttl_s` (6 h by default) server-side; rebuild the
 *  view well before that so a long-open dashboard never reads with a stale one. */
const VIEW_MAX_AGE_MS = 3 * 60 * 60 * 1000;

const EMPTY_ROWS: JBrowseTrackRow[] = [];

/** Show a track, an alignment track with the tile's read-pairs display (arcs or
 *  cloud, lower panels of its display in JBrowse 4.3.0; the pileup is default). */
function showTrackPaired(
  view: LgvView,
  id: string,
  payload: JBrowseSessionResponse | null | undefined,
  mode: unknown,
): void {
  const snapshot = alignmentTrackIds(payload?.tracks ?? []).has(id)
    ? pairsDisplaySnapshot(mode)
    : {};
  if (Object.keys(snapshot).length) view.showTrack(id, {}, snapshot);
  else view.showTrack(id);
}

/** Hides the menu chip of a highlight band (dismiss / bookmark: the bookmark
 *  entry opens a widget this embedded view does not register). JBrowse's
 *  styles carry no stable class, so the band is matched by what it is: a
 *  translated, coloured div whose child holds the chip button. */
const HIGHLIGHT_CHIP_CSS =
  '[data-testid="jbrowse-component"] [data-testid="tracksContainer"] ' +
  'div[style*="translateX"][style*="background"] > div > button { display: none; }';

/** Alpha of the band drawn over the tile's own region: fainter than a hover
 *  band (`BAND_ALPHA`), since it stays on screen. */
const REGION_BAND_ALPHA = 0.2;

/** Alpha of the band over a region another tile selected: fainter still, as
 *  the view usually sits inside it and the band then tints all of it. */
const SELECTION_BAND_ALPHA = 0.1;

/** How long after a gesture on the browser a move of the view counts as the
 *  reader's own navigation (what gets remembered across visits). */
const USER_NAV_WINDOW_MS = 4000;

/** The label of this tile's kind in a linked view's compact header. */
const GENOME_KIND_LABEL = {
  tag: 'Browser',
  icon: 'tabler:dna',
  description: 'Genome browser: signal and reads of the samples at base resolution',
};

export interface JBrowseToolbarState {
  showHeader: boolean;
  showOverview: boolean;
  showStatus: boolean;
  clickFilters: boolean;
  /** Lift JBrowse's "region too large" limits on every open track. */
  forceLoad: boolean;
  /** Let a plain vertical wheel scroll the tracks (off: it scrolls the page). */
  scrollTracks: boolean;
  /** Show a call and its mate side by side in one multi-region view. */
  bothSides: boolean;
  /** Follow the genomic window of the other genome tiles. */
  followWindow: boolean;
  /** The region density strip under the header. */
  showDensity: boolean;
  /** The colour legend of the open tracks, in the status bar. */
  showLegend: boolean;
  /** Stretch the signal tracks to fill the tile (always on in fullscreen). */
  fitTracks: boolean;
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

/** The locus the user last looked at, per viewer (a string, unlike the toggles). */
function readString(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** The ordered ids of the open tracks, per viewer; [] when nothing is stored. */
function readTrackIds(key: string): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(key) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function writeTrackIds(key: string, ids: string[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    // Private mode / blocked storage: the track choice just won't persist.
  }
}

function writeString(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private mode / blocked storage: the locus just won't persist.
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

/** The nearest ancestor above ``el`` that scrolls vertically: the dashboard
 *  canvas, or the document when the page itself scrolls. */
function pageScroller(el: HTMLElement): Element {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const { overflowY } = window.getComputedStyle(node);
    if (/(auto|scroll|overlay)/.test(overflowY) && node.scrollHeight > node.clientHeight + 1) {
      return node;
    }
  }
  return document.scrollingElement ?? document.documentElement;
}

/** A track's display name off a widget's track reference. */
function trackNameOf(track: { configuration?: unknown } | null | undefined): string | undefined {
  if (!track?.configuration) return undefined;
  const name = readConfObject(track.configuration as never, ['name']);
  return typeof name === 'string' && name ? name : undefined;
}

/**
 * The linear genome view without JBrowse's own title bar (hamburger, view
 * name, logo): Depictio's chrome already frames the tile. Mirrors
 * `EmbeddedViewContainer` + `JBrowseLinearGenomeView` from the LGV package.
 */
const EmbeddedLGV = observer(function EmbeddedLGV({
  viewState,
  muiThemeOverrides,
  leaveFeatureWidget,
}: {
  viewState: ViewState;
  muiThemeOverrides: Record<string, unknown>;
  /** True for a feature widget the click-to-filter reaction already handles. */
  leaveFeatureWidget: (widgetType: string) => boolean;
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
      {/* A clicked feature opens Depictio's panel (Mantine), not JBrowse's
          drawer: the widget is hidden as it appears. Every other widget (track
          config, about-track...) still renders here. */}
      <FeatureDetails
        session={session}
        leaveWidget={leaveFeatureWidget}
        trackNameOf={trackNameOf}
      />
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
  const colorSource = useCategoryColorSource();
  const colorPalette = useCategoryPalette();
  const [payload, setPayload] = useState<JBrowseSessionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewState, setViewState] = useState<ViewState | null>(null);
  const viewMeta = useRef<{
    assembly: string;
    createdAt: number;
    location: string | null;
    filtersKey: string;
    versionKey: string;
  }>({
    assembly: '',
    createdAt: 0,
    location: null,
    filtersKey: '',
    versionKey: '',
  });
  // A locus another tile asked this browser to open on: the family it belongs
  // to (for the page-load hand-over), and one that arrived by event before the
  // view existed. See jbrowse/pendingLocus.ts.
  const browserTarget = useGenomeBrowserTarget();
  const familyIdRef = useRef<string | null>(null);
  familyIdRef.current = browserTarget?.familyId ?? null;
  const eventLocusRef = useRef<string | null>(null);
  // How the rubberband menu reaches this tile's "Use this region" emitter. The
  // plugin is rebuilt with each view; the handle outlives them.
  const regionSelectHandle = useRef<RegionSelectHandle['current']>(null);
  // The genome region in force (a brush elsewhere), and the one the view was
  // last moved to, so the follower below moves only for a new one. The tile's
  // own region ("Use this region") is not one to follow: it came from here.
  const selectionRegion = useMemo(
    () => genomeSelectionRegion(withoutOwnRegion(filters, String(metadata.index))),
    [filters, metadata.index],
  );
  const regionKey = selectionRegion
    ? `${selectionRegion.chrom}:${selectionRegion.start}-${selectionRegion.end}`
    : '';
  const regionKeyRef = useRef(regionKey);
  regionKeyRef.current = regionKey;
  // The tile that selected it, named in the header's link chip.
  const selectionSourceIndex = useMemo(
    () => (selectionRegion ? genomeSelectionSource(withoutOwnRegion(filters, String(metadata.index))) : null),
    [selectionRegion, filters, metadata.index],
  );
  const selectionRegionRef = useRef(selectionRegion);
  selectionRegionRef.current = selectionRegion;
  const followedRegionKey = useRef('');
  // Data time travel: the version body goes into the request, its key into
  // the fetch deps. The key of the request the current payload answered is
  // kept apart: a payload of another data version carries other track URLs
  // (they name the manifest commit) under the same track ids, so the view is
  // rebuilt rather than diffed.
  const {
    body: versionBody,
    key: versionKey,
    definitionVersionId,
  } = useDataVersionRequest();
  const definitionKey = renderDefinitionKey(metadata, definitionVersionId);
  const payloadVersionKey = useRef('');
  // A past version (or a dataset pin) is read-only: it opens on its own
  // tracks and locus, and never writes the viewer's remembered ones, or going
  // back to the live dashboard would reopen what the preview showed.
  const timeTravel = Object.keys(versionBody).length > 0;
  // Track ids this component manages (the manifest's): user-opened tracks
  // outside this set (annotation, UCSC, from the track selector or the track
  // menu) are never hidden by a filter change.
  const managedIds = useRef<Set<string>>(new Set());

  const selectionEnabled = Boolean(metadata.selection_enabled) && !!onFilterChange;
  const selectionMode = (metadata.selection_mode as string) || 'feature_click';

  // ---- toggles (defaults from the YAML, then per-viewer localStorage) ------
  // Per dashboard: a YAML `index` such as `loc-browser` recurs across templates,
  // and one template's open tracks mean nothing to another's.
  const storageKey = `depictio.jbrowse.${dashboardId}.${metadata.index}`;
  // One source or a list (several collections, workflows or omics); the first
  // is primary: it carries the mate and frames the view.
  const sources = useMemo(() => locusSources(metadata.locus_from), [metadata.locus_from]);
  const locusFrom = sources[0] ?? null;
  // A declared mate (the other side of a fusion or SV) makes "Both sides" the
  // default: the call is only half understood with one breakpoint on screen.
  const hasMate = Boolean(locusFrom?.mate);
  // Initial display of the alignment tracks; read from a ref because the track
  // changes below run in callbacks that outlive a render.
  const pairsModeRef = useRef<unknown>(undefined);
  pairsModeRef.current = metadata.read_pairs_display ?? payload?.read_pairs_display;
  // `color_scale` (a sequential ramp over a manifest column) replaces
  // `color_by` (one hue per value) when both are set; either names the column
  // the tracks are grouped and coloured by.
  const colorScale = readColorScale(metadata.color_scale);
  const colorBy = colorScale?.column ?? (typeof metadata.color_by === 'string' ? metadata.color_by : '');
  const [toolbar, setToolbar] = useState<JBrowseToolbarState>(() => ({
    showHeader: readToggle(`${storageKey}.header`, metadata.show_header !== false),
    showOverview: readToggle(`${storageKey}.overview`, metadata.show_overview !== false),
    showStatus: readToggle(`${storageKey}.status`, true),
    clickFilters: readToggle(`${storageKey}.clickFilters`, true),
    forceLoad: readToggle(`${storageKey}.forceLoad`, metadata.force_load === true),
    scrollTracks: readToggle(`${storageKey}.scrollTracks`, false),
    bothSides: readToggle(`${storageKey}.bothSides`, hasMate),
    followWindow: readToggle(`${storageKey}.followWindow`, metadata.follow_window !== false),
    showDensity: readToggle(`${storageKey}.density`, metadata.show_density === true),
    // On by default only when a `color_by` / `color_scale` colours the tracks:
    // the per-sample colours alone barely show on reads, and the legend then
    // reads as noise (the track names say whose track it is).
    showLegend: readToggle(`${storageKey}.legend`, Boolean(colorBy)),
    fitTracks: readToggle(`${storageKey}.fitTracks`, false),
  }));
  const toolbarRef = useRef(toolbar);
  toolbarRef.current = toolbar;
  // With click-to-filter on, a clicked feature's BaseFeatureWidget belongs to
  // the feature_click reaction below (it hides the widget and emits the
  // filter); Depictio's feature panel stands aside for exactly that case.
  const leaveRef = useRef<(type: string) => boolean>(() => false);
  leaveRef.current = (type) =>
    type === 'BaseFeatureWidget' &&
    selectionEnabled &&
    !!payload?.selection_column &&
    selectionMode === 'feature_click' &&
    toolbar.clickFilters;
  const leaveFeatureWidget = useCallback((type: string) => leaveRef.current(type), []);
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
  // A genome region is somewhere to look, not a subset of tracks: the browser
  // follows it (below) and the backend never narrows `locus_from` with it.
  const fetchFilters = useMemo(
    () =>
      filtersExcludingOwn(filters, metadata.index, 'jbrowse_selection').filter(
        (f) => !isRegionFilter(f),
      ),
    [filters, metadata.index],
  );
  const filtersKey = JSON.stringify(fetchFilters);

  // ---- region navigator ------------------------------------------------------
  // Previous / next over the merged regions of `locus_from` (all its sources),
  // next to the view rather than by rank, plus the picker. Reads only: it moves
  // the view, never the filters.
  const stepperEnabled = Boolean(locusFrom) && metadata.call_stepper !== false;
  const callsResetKey = `${filtersKey}|${versionKey}|${refreshTick ?? 0}`;
  const stepper = useCallNavigator({
    dashboardId,
    index: String(metadata.index),
    filters: fetchFilters,
    versionBody,
    enabled: stepperEnabled,
    resetKey: callsResetKey,
    sources,
  });
  const stepperRef = useRef(stepper);
  stepperRef.current = stepper;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchJBrowseSession(dashboardId, metadata.index, fetchFilters, versionBody)
      .then((res) => {
        if (cancelled) return;
        payloadVersionKey.current = versionKey;
        setPayload(res);
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
  }, [dashboardId, metadata.index, filtersKey, refreshTick, versionKey, definitionKey]);

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
    const presetAssembly = payload.assembly_kind === 'preset';
    // Alignment tracks wear their sample's dashboard colour, so a sample is
    // the same colour here as on the filter chips and in every other tile.
    const sampleColours = sampleColourMap(
      colorSource,
      sampleColourColumn(payload.selection_column, payload.track_rows),
      payload.track_rows,
      colorPalette,
    );
    // `color_by`: one colour per value of a manifest column (the condition),
    // applied first; the per-sample colours then only fill what it left bare.
    const confs = absolutize(payload.tracks);
    const conditionColours = colorBy
      ? colorScale
        ? conditionSequentialMap(colorScale, confs)
        : conditionColourMap(colorSource, colorBy, confs, colorPalette)
      : null;
    const byCondition = colorBy && conditionColours ? colourTracksBy(confs, colorBy, conditionColours) : confs;
    // What the colouring above resolved goes to the dashboard's other genome
    // tiles (a genome view's lanes), so one sample is one colour on both.
    setGenomeTracksColours(
      dashboardId,
      metadata.index,
      colorBy && conditionColours
        ? trackColoursBy(confs, payload.track_rows, colorBy, conditionColours)
        : null,
    );
    const tracks = colourAlignmentTracks(
      withSectionCategory(
        byCondition,
        payload.track_rows,
        colorBy ? (conf) => conditionOf(conf, colorBy) : undefined,
      ),
      payload.track_rows,
      sampleColours,
    );
    for (const id of manifestTrackIds(payload.track_rows)) managedIds.current.add(id);

    const stale = Date.now() - viewMeta.current.createdAt > VIEW_MAX_AGE_MS;
    const otherVersion = viewMeta.current.versionKey !== payloadVersionKey.current;
    if (!viewState || viewMeta.current.assembly !== assemblyName || stale || otherVersion) {
      // The open tracks and their order as the user left them (per viewer),
      // restricted to tracks this payload still knows about.
      const savedIds = timeTravel ? [] : readTrackIds(`${storageKey}.tracks`);
      const known = new Set(payload.track_rows.map((r) => r.track_id));
      const savedKnown = savedIds.filter((id) => known.has(id));
      const openAtStart = savedKnown.length ? savedKnown : payload.shown_track_ids;
      // A locus handed over by another tile wins over everything, and is not
      // a navigation of the reader's: `userActedRef` never saw it.
      const pending =
        eventLocusRef.current ??
        takePendingLocus(familyIdRef.current, dashboardId, String(metadata.index));
      eventLocusRef.current = null;
      // The region in force at build is the opening's business, not a move to
      // follow: the follower below starts from it, like the window follower.
      followedRegionKey.current = regionKeyRef.current;
      const state = createViewState({
        assembly: absolutize(payload.assembly),
        tracks,
        plugins: [
          GtfPlugin,
          ...(presetAssembly ? [DepictioGeneSearchPlugin] : []),
          createRegionSelectPlugin(regionSelectHandle),
        ],
        // Gene names resolve through the backend for a preset assembly (the
        // locus box has no text index otherwise).
        ...(presetAssembly
          ? { aggregateTextSearchAdapters: geneSearchAdapterConfigs(assemblyName) }
          : {}),
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
              // Only a locus the reader navigated to is remembered (`.loc.v2`),
              // so the opening the backend chose is never frozen by a visit.
              loc: (() => {
                const persisted = timeTravel
                  ? null
                  : readString(`${storageKey}.${PERSISTED_LOCUS_SUFFIX}`);
                const loc = initialLocus({
                  pending,
                  region: selectionRegionRef.current,
                  regionLocus: windowLocus(selectionRegionRef.current),
                  persisted,
                  location: payload.location,
                  mateLocation: payload.mate_location,
                  bothSides: toolbarRef.current.bothSides,
                });
                traceGenome(String(metadata.index), 'browser opens', {
                  loc,
                  pending,
                  region: windowLocus(selectionRegionRef.current),
                  persisted,
                  location: payload.location,
                  opening: payload.opening,
                });
                return loc;
              })(),
              tracks: openAtStart.map((id) =>
                initTrackEntry(id, alignmentTrackIds(tracks), pairsModeRef.current),
              ),
            },
          },
        },
      } as Parameters<typeof createViewState>[0]);
      viewMeta.current = {
        assembly: assemblyName,
        createdAt: Date.now(),
        location: payload.location,
        filtersKey,
        versionKey: payloadVersionKey.current,
      };
      stepperRef.current.setCurrent(null);
      setViewState(state);
      return;
    }

    // Same assembly: diff the open tracks towards the payload. This is also
    // where choices made in the track menu end: a new payload (filter change,
    // realtime refresh) re-applies the filtered set to the manifest tracks.
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
    // The filtered set is re-applied only when the filters changed: a refetch
    // with the same filters (refresh, the restored set on load) keeps the
    // tracks the user has open, and their order.
    const filtersChanged = viewMeta.current.filtersKey !== filtersKey;
    viewMeta.current.filtersKey = filtersKey;
    if (filtersChanged) {
      const plan = planTrackSync(open, payload.shown_track_ids, managedIds.current);
      for (const id of plan.hide) view.hideTrack(id);
      for (const id of plan.show) {
        try {
          showTrackPaired(view as unknown as LgvView, id, payload, pairsModeRef.current);
        } catch (err) {
          console.warn(`jbrowse: cannot show track ${id}`, err);
        }
      }
      // The regions are another set now: the navigator starts over.
      stepperRef.current.setCurrent(null);
    }
    // Only a location the dashboard asked for (a filter on `locus_from`, the
    // YAML `location`) moves an open view; the opening defaults do not.
    if (shouldRenavigate(payload.opening, payload.location, viewMeta.current.location)) {
      const target = sidesLocus(
        payload.location,
        payload.mate_location,
        toolbarRef.current.bothSides,
      );
      if (target) {
        view.navToLocString(target).catch((err: unknown) => {
          console.warn('jbrowse: navigation failed', err);
        });
      }
    }
    viewMeta.current.location = payload.location;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload]);

  // Remember which tracks are open, in order: a refresh reopens the same set.
  useEffect(() => {
    if (!viewState || timeTravel) return;
    const view = viewState.session.view as unknown as LgvView;
    let timer: number | undefined;
    const dispose = reaction(
      () => (aliveNode(view) ? openTrackIds(view) : null),
      (ids) => {
        if (ids == null) return;
        window.clearTimeout(timer);
        timer = window.setTimeout(() => writeTrackIds(`${storageKey}.tracks`, ids), 400);
      },
      { equals: comparer.structural },
    );
    return () => {
      window.clearTimeout(timer);
      dispose();
    };
  }, [viewState, storageKey, timeTravel]);

  // Remember the locus the reader navigated to, so a refresh (or a rebuilt
  // view) reopens there. Only after a navigation of theirs: the opening the
  // backend picked, the stepper and the window follower move the view too, and
  // writing those down froze an empty view from one visit to the next. A
  // gesture on the browser (pointer, wheel, keys in its locus box, a pick in
  // its search results) marks the next moves as theirs for a few seconds.
  // Debounced: panning fires a lot.
  const lgvBoxRef = useRef<HTMLDivElement>(null);
  const userActedRef = useRef(false);
  useEffect(() => {
    let timer: number | undefined;
    const mark = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const inBrowser =
        lgvBoxRef.current?.contains(target) ||
        // MUI portals the autocomplete list and the results dialog to <body>.
        target.closest('.MuiPopper-root, .MuiPopover-root, .MuiDialog-root, .MuiModal-root');
      if (!inBrowser) return;
      userActedRef.current = true;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        userActedRef.current = false;
      }, USER_NAV_WINDOW_MS);
    };
    const events = ['pointerdown', 'wheel', 'keydown'] as const;
    for (const name of events) document.addEventListener(name, mark, { capture: true, passive: true });
    return () => {
      window.clearTimeout(timer);
      for (const name of events) document.removeEventListener(name, mark, { capture: true });
    };
  }, []);
  useEffect(() => {
    if (!viewState || timeTravel) return;
    const view = viewState.session.view as unknown as LgvView;
    let timer: number | undefined;
    const dispose = reaction(
      () => locStringsOf(view),
      (locus) => {
        if (!locus || !userActedRef.current) return;
        window.clearTimeout(timer);
        timer = window.setTimeout(
          () => writeString(`${storageKey}.${PERSISTED_LOCUS_SUFFIX}`, locus),
          400,
        );
      },
      { equals: comparer.structural },
    );
    return () => {
      window.clearTimeout(timer);
      dispose();
    };
  }, [viewState, storageKey, timeTravel]);

  // The metadata panel lives outside the tile: hand it the payload and the
  // visible locus (debounced like the remembered one). Written in time travel
  // too, the panel then describes what the tile shows.
  useEffect(() => {
    if (payload) setGenomeTracksPayload(dashboardId, metadata.index, payload);
  }, [dashboardId, metadata.index, payload]);

  useEffect(() => {
    if (!viewState) return;
    const view = viewState.session.view as unknown as LgvView;
    let timer: number | undefined;
    const dispose = reaction(
      () => locStringsOf(view),
      (locus) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(
          () => setGenomeTracksLocus(dashboardId, metadata.index, locus || null),
          400,
        );
      },
      { equals: comparer.structural, fireImmediately: true },
    );
    return () => {
      window.clearTimeout(timer);
      dispose();
    };
  }, [viewState, dashboardId, metadata.index]);

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
  // The fullscreen element is also where the track menu's dropdown portals.
  const [fullscreenEl, setFullscreenEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const onFs = () => {
      setFullscreenEl((document.fullscreenElement as HTMLElement | null) ?? null);
      window.requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    };
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, []);

  // ---- wheel: scroll the dashboard, zoom on Cmd/Ctrl + wheel -----------------
  // Capture phase on the tile, so the decision is made before JBrowse's own
  // listener (or a track's scroll box) sees the event. See `jbrowse/wheel.ts`.
  const rootRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<LgvView | null>(null);
  viewRef.current = viewState ? (viewState.session.view as unknown as LgvView) : null;
  // Display settings (Vue, Alignments, Coverage...): local choice, then YAML
  // `display:`, then JBrowse's default. See `jbrowse/displaySettings.ts`.
  const displaySettings = useDisplaySettings(
    viewState ? viewState.session.view : null,
    payload?.display,
    `${dashboardId}.${metadata.index}`,
  );
  useSharedScale(
    viewState ? viewState.session.view : null,
    displaySettings.value('y_scale') === 'shared' ? 'shared' : 'per_track',
  );
  // In fullscreen the tile is the page: the tracks always fill it.
  const inFullscreen = !!fullscreenEl && !!rootRef.current && fullscreenEl.contains(rootRef.current);
  // `auto_height` sizes the tile to the tracks, so the tracks must not stretch
  // to the tile (fullscreen aside, where the tile is the page).
  const autoHeight = metadata.auto_height === true;
  useFitTracks(
    viewState ? viewState.session.view : null,
    lgvBoxRef,
    autoHeight ? inFullscreen : toolbar.fitTracks || inFullscreen,
  );
  useJBrowseAutoHeight(String(metadata.index), lgvBoxRef, autoHeight, !!viewState, inFullscreen);

  // ---- region density strip --------------------------------------------------
  // Where the regions of the enabled sources fall along the genome, one row per
  // source, sample or run. Refetched with the filters, never on a pan.
  const [tileWidth, setTileWidth] = useState(0);
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([entry]) => setTileWidth(Math.round(entry.contentRect.width)));
    ro.observe(root);
    return () => ro.disconnect();
  }, []);
  const [visibleRegions, setVisibleRegions] = useState<VisibleRegion[]>([]);
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return undefined;
    return reaction(
      () => visibleRegionsOf(view),
      (regions) => setVisibleRegions(regions),
      { equals: comparer.structural, fireImmediately: true },
    );
  }, [viewState]);
  const assemblyName = String(payload?.assembly.name ?? '');
  const [assemblyRegions, setAssemblyRegions] = useState<{ refName: string; length: number }[]>([]);
  useEffect(() => {
    if (!viewState) return undefined;
    // The assembly's regions load asynchronously: wait for them.
    return reaction(
      () => assemblyRegionsOf(viewState.session, assemblyName),
      (regions) => setAssemblyRegions(regions),
      { equals: comparer.structural, fireImmediately: true },
    );
  }, [viewState, assemblyName]);
  const enabledSourceSpecs = useMemo(
    () => sources.filter((src) => stepper.enabledSources.includes(src.name)),
    [sources, stepper.enabledSources],
  );
  const [densityGroupChoice, setDensityGroup] = useState<DensityGroup | null>(null);
  const densityGroup = densityGroupChoice ?? defaultDensityGroup(enabledSourceSpecs);
  const densityEnabled =
    Boolean(locusFrom) && metadata.show_density !== false && toolbar.showDensity;
  const density = useCallDensity({
    dashboardId,
    index: String(metadata.index),
    filters: fetchFilters,
    versionBody,
    enabled: densityEnabled && assemblyRegions.length > 0,
    resetKey: callsResetKey,
    sources: stepper.enabledSources,
    regions: assemblyRegions,
    bins: Math.min(2000, Math.max(200, tileWidth)),
    group: densityGroup,
  });

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    let zoomPx = 0;
    let zoomAt = 0;
    let frame = 0;
    const onWheel = (event: WheelEvent) => {
      // In fullscreen the tile is the page: nothing behind it to scroll.
      const fullscreen = !!document.fullscreenElement?.contains(root);
      const intent = wheelIntent(event, !toolbar.scrollTracks && !fullscreen);
      if (intent === 'native') return;
      event.preventDefault();
      event.stopPropagation();
      if (intent === 'page') {
        // The tracks first when there are more than the tile shows, then the
        // page once they reach their edge.
        const dy = wheelPixels(event, window.innerHeight);
        const tracks = root.querySelector<HTMLElement>('.depictio-jbrowse-host');
        if (tracks && canScrollBy(tracks, dy)) tracks.scrollBy({ top: dy });
        else pageScroller(root).scrollBy({ top: dy });
        return;
      }
      zoomPx += wheelPixels(event, root.clientHeight);
      zoomAt = event.clientX - root.getBoundingClientRect().left;
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const view = viewRef.current;
        if (view && aliveNode(view)) view.zoomTo(view.bpPerPx * zoomFactor(zoomPx), zoomAt);
        zoomPx = 0;
      });
    };
    root.addEventListener('wheel', onWheel, { capture: true, passive: false });
    // The figures' "how to zoom" hint, on the browser's first hover: hint only,
    // the handler above owns the wheel.
    const detachZoomHint = attachZoomGate(root, {
      block: false,
      ownHint: { visibleMs: 6000, extra: 'drag to pan' },
    });
    return () => {
      detachZoomHint();
      root.removeEventListener('wheel', onWheel, { capture: true });
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [toolbar.scrollTracks]);

  // ---- open tracks (live) → track menu ---------------------------------------
  // Manual choices made in the menu hold until the next payload: the sync
  // effect above then re-applies the filtered set (to manifest tracks only).
  const payloadRef = useRef(payload);
  payloadRef.current = payload;
  const ownIndex = String(metadata.index);
  const [openIds, setOpenIds] = useState<string[]>([]);
  useEffect(() => {
    if (!viewState) {
      setOpenIds([]);
      return;
    }
    const view = viewState.session.view as unknown as LgvView;
    return reaction(
      () => (aliveNode(view) ? openTrackIds(view) : []),
      (ids) => setOpenIds(ids),
      { fireImmediately: true, equals: comparer.structural },
    );
  }, [viewState]);

  const withView = useCallback(
    (fn: (view: LgvView) => void) => {
      if (!viewState) return;
      const view = viewState.session.view as unknown as LgvView;
      if (!aliveNode(view)) return;
      try {
        fn(view);
      } catch (err) {
        console.warn('jbrowse: track change failed', err);
      }
    },
    [viewState],
  );

  // ---- "Use this region": the browser as a source of a genome_selection ------
  // The span of a rubberband drag, or the window on screen, goes out as the
  // region filter pair on the columns of `locus_from` (see regionSelection.ts).
  // A second press clears it, and so does the tile's Reset. The tile never
  // follows its own region (`withoutOwnRegion` above).
  const locusSource = payload?.locus_source ?? null;
  const locusSourceRef = useRef(locusSource);
  locusSourceRef.current = locusSource;
  const canSelectRegion = !!locusSource && !!onFilterChange && !timeTravel;
  const regionActive = isOwnRegion(filters, ownIndex);
  const emitRegion = useCallback(
    (region: JBrowseRegion | null) => {
      const source = locusSourceRef.current;
      if (!onFilterChange || !source) return;
      const filters = regionFiltersFor(source, { index: metadata.index }, region);
      traceGenome(
        String(metadata.index),
        region ? 'browser region emitted (Use this region)' : 'browser region cleared',
        describeFilters(filters),
      );
      for (const filter of filters) onFilterChange(filter);
    },
    [onFilterChange, metadata.index],
  );
  regionSelectHandle.current = canSelectRegion ? (region) => emitRegion(region) : null;
  const toggleRegion = useCallback(() => {
    if (regionActive) return emitRegion(null);
    withView((view) => {
      const win = visibleWindow(view.dynamicBlocks?.contentBlocks);
      if (win) emitRegion({ refName: win.entity, start: win.start - 1, end: win.end });
    });
  }, [regionActive, emitRegion, withView]);

  // ---- hover bus → highlight bands ------------------------------------------
  // A hover on another tile (a Manhattan point, a table row) draws a band
  // across every open track, and the tile's own region stays drawn as a
  // second one. `setHighlight` replaces the whole list, so both sources are
  // merged here. The view is never moved; only bands this tile set are cleared.
  const hovered = useHighlight(String(metadata.index));
  const bandSet = useRef(false);
  const primaryColour = (jbTheme.palette.primary as { main: string }).main;
  const ownRegionJson = useMemo(
    () => JSON.stringify(ownRegionOf(filters, ownIndex)),
    [filters, ownIndex],
  );
  const ownRegion = useMemo(() => JSON.parse(ownRegionJson) as JBrowseRegion | null, [ownRegionJson]);
  useEffect(() => {
    if (!viewState) return;
    const assemblyName = String(payloadRef.current?.assembly.name ?? '');
    const session = viewState.session as unknown as {
      assemblyManager?: {
        get: (name: string) => { getCanonicalRefName?: (r: string) => string | undefined } | undefined;
      };
    };
    const canonical = (name: string): string | undefined => {
      const viaAssembly = canonicalRefName(session.assemblyManager?.get(assemblyName), name);
      if (viaAssembly) return viaAssembly;
      // The assembly is not loaded yet: fall back to the regions on screen.
      const shown = (viewRef.current?.displayedRegions ?? []).find((r) => r.refName === name);
      return shown?.refName;
    };
    const bands: Parameters<LgvView['setHighlight']>[0] = [];
    if (ownRegion) {
      const color = withAlpha(primaryColour, REGION_BAND_ALPHA);
      bands.push({ ...ownRegion, assemblyName, ...(color ? { color } : {}) });
    }
    // The region another tile selected, once the reader zooms out of it or
    // pans away: its edges show then. Inside it, nothing is drawn.
    const selected = selectionRegionRef.current;
    if (selected && Number.isFinite(selected.end) && selected.end > selected.start) {
      const band = {
        refName: canonical(selected.chrom) ?? selected.chrom,
        start: selected.start,
        end: selected.end,
      };
      if (viewLeavesRegion(visibleRegions, band)) {
        const color = withAlpha(primaryColour, SELECTION_BAND_ALPHA);
        bands.push({ ...band, assemblyName, ...(color ? { color } : {}) });
      }
    }
    const hoverBandNow = hoverBand(
      hovered,
      locusSource,
      canonical,
      assemblyName,
      primaryColour,
      viewRef.current?.bpPerPx,
    );
    if (hoverBandNow) bands.push(hoverBandNow);
    if (bands.length) {
      withView((view) => view.setHighlight(bands));
      bandSet.current = true;
    } else if (bandSet.current) {
      withView((view) => view.setHighlight([]));
      bandSet.current = false;
    }
  }, [hovered, viewState, primaryColour, withView, ownRegion, locusSource, regionKey, visibleRegions]);

  // ---- cursor and window → the other genomic tiles --------------------------
  // The inverse of the band above. The base under the pointer goes out on the
  // hover bus (a cursor line on a coverage track or a Manhattan), the window on
  // screen on the view-window store (a coverage track fits its axis to it).
  // Neither is a filter: nothing any tile fetches changes.
  const publishHighlight = usePublishHighlight(ownIndex);
  const publishViewWindow = usePublishViewWindow(ownIndex);
  // The canonical reference name of the assembly can differ from the one a
  // plot's rows use (NC_045512v2 against MN908947.3), so events also carry the
  // other names the assembly knows the contig by.
  const aliasesOf = useMemo(() => {
    if (!viewState) return null;
    const session = viewState.session as unknown as {
      assemblyManager?: { get: (name: string) => { refNameAliases?: RefNameAliases } | undefined };
    };
    return createAliasLookup(() =>
      session.assemblyManager?.get(String(payloadRef.current?.assembly.name ?? ''))?.refNameAliases,
    );
  }, [viewState]);
  // The feature under the pointer, when there is one: its event is richer than
  // the cursor's (a name, a span, the row), so the cursor stays quiet meanwhile.
  const hoveredFeatureRef = useRef<HoverFeature | null>(null);
  useEffect(() => {
    const root = rootRef.current;
    if (!root || !viewState) return;
    const TRACKS = '[data-testid="tracksContainer"]';
    let pressed = false;
    let shown = false;
    const clear = () => {
      if (!shown) return;
      shown = false;
      publishHighlight(null);
    };
    const onMove = (event: PointerEvent) => {
      // A drag pans the view: the cursor would just flicker along the way.
      if (pressed) return;
      if (hoveredFeatureRef.current) return;
      const tracks = (event.target as Element | null)?.closest?.(TRACKS);
      const view = viewRef.current;
      if (!tracks || !view || !aliveNode(view)) return clear();
      let locus: ReturnType<typeof cursorLocus> = null;
      try {
        locus = cursorLocus(view, event.clientX, tracks.getBoundingClientRect().left);
      } catch {
        // Width not measured yet: no cursor.
      }
      if (!locus) return clear();
      shown = true;
      publishHighlight({
        entity: locus.refName,
        start: locus.coord,
        end: locus.coord,
        positionColumn: '__genome__',
        entityAliases: aliasesOf?.(locus.refName),
      });
    };
    const onDown = () => {
      pressed = true;
      clear();
    };
    const onUp = () => {
      pressed = false;
    };
    root.addEventListener('pointermove', onMove, { passive: true });
    root.addEventListener('pointerleave', clear);
    root.addEventListener('pointerdown', onDown, { capture: true, passive: true });
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      root.removeEventListener('pointermove', onMove);
      root.removeEventListener('pointerleave', clear);
      root.removeEventListener('pointerdown', onDown, { capture: true });
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      clear();
    };
  }, [viewState, publishHighlight, aliasesOf]);

  // The feature under the pointer, on whichever display it is (a variant, a
  // peak, a read, a coverage bin): published with its span, name and the row it
  // stands for in the terms of `locus_from`. One reaction per display, kept in
  // step with the open tracks (see featureHover.ts); rebuilt with the view.
  useEffect(() => {
    if (!viewState) return;
    const view = viewState.session.view as unknown as LgvView;
    const stop = watchFeatureHover(
      view,
      (feature) => {
        hoveredFeatureRef.current = feature;
        if (!feature) return publishHighlight(null);
        publishHighlight(
          hoverEventFromFeature(feature, locusSourceRef.current, aliasesOf?.(feature.refName)),
        );
      },
      aliveNode,
    );
    return () => {
      stop();
      if (hoveredFeatureRef.current) publishHighlight(null);
      hoveredFeatureRef.current = null;
    };
  }, [viewState, publishHighlight, aliasesOf]);

  // The visible window, debounced like the persisted locus: panning fires a lot.
  useEffect(() => {
    if (!viewState) return;
    const view = viewState.session.view as unknown as LgvView;
    let timer: number | undefined;
    const dispose = reaction(
      () => {
        if (!aliveNode(view)) return null;
        try {
          const win = visibleWindow(view.dynamicBlocks?.contentBlocks);
          // Read here, so the window is published again once the aliases load.
          return win ? { ...win, entityAliases: aliasesOf?.(win.entity) } : null;
        } catch {
          // Width not measured yet: nothing on screen to report.
          return null;
        }
      },
      (win) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          traceGenome(
            ownIndex,
            'browser view',
            win ? `${win.entity}:${win.start}-${win.end}` : 'none',
          );
          publishViewWindow(win);
        }, 150);
      },
      { fireImmediately: true, equals: comparer.structural },
    );
    return () => {
      window.clearTimeout(timer);
      dispose();
      publishViewWindow(null);
    };
  }, [viewState, publishViewWindow, aliasesOf]);

  const showTracks = useCallback(
    (ids: string[]) =>
      withView((view) => {
        const open = new Set(openTrackIds(view));
        for (const id of ids) {
          if (open.has(id)) continue;
          try {
            showTrackPaired(view as unknown as LgvView, id, payloadRef.current, pairsModeRef.current);
          } catch (err) {
            console.warn(`jbrowse: cannot show track ${id}`, err);
          }
        }
      }),
    [withView],
  );
  const hideTracks = useCallback(
    (ids: string[]) =>
      withView((view) => {
        for (const id of ids) view.hideTrack(id);
      }),
    [withView],
  );
  const onToggleTrack = useCallback(
    (id: string, show: boolean) => (show ? showTracks([id]) : hideTracks([id])),
    [showTracks, hideTracks],
  );
  const onHideAll = useCallback(
    () =>
      withView((view) => {
        for (const id of hideAllIds(openTrackIds(view), payloadRef.current?.track_rows ?? []))
          view.hideTrack(id);
      }),
    [withView],
  );
  // "Back to filters": the same diff a new payload applies, but over every
  // row of the menu (UCSC / reference too), so the view returns to exactly
  // what the dashboard filters open.
  const onBackToFilters = useCallback(
    () =>
      withView((view) => {
        const p = payloadRef.current;
        if (!p) return;
        const managed = new Set<string>(managedIds.current);
        for (const row of p.track_rows) managed.add(row.track_id);
        const plan = planTrackSync(openTrackIds(view), p.shown_track_ids, managed);
        for (const id of plan.hide) view.hideTrack(id);
        for (const id of plan.show) {
          try {
            showTrackPaired(view as unknown as LgvView, id, payloadRef.current, pairsModeRef.current);
          } catch (err) {
            console.warn(`jbrowse: cannot show track ${id}`, err);
          }
        }
      }),
    [withView],
  );
  // ---- move the view: stepper, both sides, window following ----------------
  const navigate = useCallback(
    (target: string | null) => {
      if (!target) return;
      withView((view) => {
        (view as unknown as { navToLocString: (loc: string) => Promise<unknown> })
          .navToLocString(target)
          .catch((err: unknown) => console.warn('jbrowse: navigation failed', err));
      });
    },
    [withView],
  );
  // The call under the view: the stepper's, else the one the payload opened on.
  const currentSides = (): { locus: string | null; mate: string | null } => {
    const call = stepperRef.current.current;
    if (call) return { locus: call.locus, mate: call.mate_locus };
    const p = payloadRef.current;
    return { locus: p?.location ?? null, mate: p?.mate_location ?? null };
  };
  const goToCall = useCallback(
    (call: JBrowseCall) =>
      navigate(sidesLocus(call.locus, call.mate_locus, toolbarRef.current.bothSides)),
    [navigate],
  );
  // The regions the navigator steps through, for the "Regions" tab of the
  // tile's data table: the picker's grid, and a click moves the view.
  const stepperSelect = stepper.select;
  const enabledSourceNames = stepper.enabledSources;
  const regionGrid = useMemo<RegionGridProps | null>(
    () =>
      stepperEnabled
        ? {
            // Over the picker's dialog threshold: the grid takes its full
            // height. A value, not the constant, so AG Grid stays lazy.
            width: 1000,
            sources,
            enabledSources: enabledSourceNames,
            scoreLabel: locusFrom?.sort_by ?? null,
            dashboardId,
            index: String(metadata.index),
            filters: fetchFilters,
            versionBody,
            onSelect: (call) => {
              stepperSelect(call);
              goToCall(call);
            },
          }
        : null,
    [
      stepperEnabled,
      sources,
      enabledSourceNames,
      locusFrom?.sort_by,
      dashboardId,
      metadata.index,
      fetchFilters,
      versionBody,
      stepperSelect,
      goToCall,
    ],
  );
  const regionsLabel = enabledSourceNames.length === 1 ? enabledSourceNames[0] : 'Regions';
  const goStep = useCallback(
    async (direction: 1 | -1) => {
      const view = viewRef.current;
      if (!view) return;
      const name = String(payloadRef.current?.assembly.name ?? '');
      const order = assemblyRegionsOf(viewState?.session, name).map((r) => r.refName);
      const call = await stepperRef.current.step(direction, visibleRegionsOf(view), order);
      if (call) goToCall(call);
    },
    [goToCall, viewState],
  );
  // "Both sides" flips the view between the call and its two breakpoints. Off
  // keeps the region on screen first, on goes to the call it belongs to.
  const toggleBothSides = useCallback(() => {
    const next = !toolbarRef.current.bothSides;
    setToggle('bothSides', 'bothSides');
    if (next) {
      const { locus, mate } = currentSides();
      if (mate) navigate(sidesLocus(locus, mate, true));
      return;
    }
    withView((view) => {
      const regions = view.visibleLocStrings.split(' ').filter(Boolean);
      if (regions.length > 1) navigate(regions[0]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, setToggle, withView]);

  // Follow the genomic window another tile publishes (a coverage track, another
  // browser). Off while "Both sides" holds two regions: there is no single axis
  // to follow. The window already in force when the view was built is not
  // followed (the opening locus wins on load); later ones are, and the echo of
  // our own window coming back from a tile that follows us is not.
  const followActive =
    metadata.follow_window !== false &&
    toolbar.followWindow &&
    !(toolbar.bothSides && hasMate) &&
    !!viewState;
  const followed = useViewWindow(ownIndex, followActive);
  const lastFollowed = useRef<ViewWindowEvent | null>(null);
  const followBaselined = useRef(false);
  useEffect(() => {
    if (!followActive) {
      lastFollowed.current = null;
      return;
    }
    if (!followed) return;
    if (!followBaselined.current) {
      followBaselined.current = true;
      lastFollowed.current = followed;
      return;
    }
    if (sameViewWindow(lastFollowed.current, followed)) return;
    lastFollowed.current = followed;
    const view = viewRef.current;
    if (!view || !aliveNode(view)) return;
    const session = viewState!.session as unknown as {
      assemblyManager?: {
        get: (name: string) => { getCanonicalRefName?: (r: string) => string | undefined } | undefined;
      };
    };
    const asm = session.assemblyManager?.get(String(payloadRef.current?.assembly.name ?? ''));
    let current: ReturnType<typeof visibleWindow> = null;
    try {
      current = visibleWindow(view.dynamicBlocks?.contentBlocks);
    } catch {
      // Width not measured yet: nothing on screen to compare with.
    }
    navigate(followTarget(followed, current, (name) => canonicalRefName(asm, name)));
  }, [followed, followActive, viewState, navigate]);

  // Follow the genome region another tile brushed (`genome_selection`): the
  // view moves onto it and nothing is filtered, the backend never sees it. The
  // region in force when the view was built is already where it opened (see
  // `initialLocus`); a cleared region leaves the view where it is.
  useEffect(() => {
    if (!followActive || !viewState) return;
    if (!selectionRegion) {
      if (followedRegionKey.current) {
        traceGenome(ownIndex, 'followed region cleared: the view stays where it is');
      }
      followedRegionKey.current = '';
      return;
    }
    if (regionKey === followedRegionKey.current) return;
    followedRegionKey.current = regionKey;
    // A whole contig (a navigator's default region) is no place to read
    // calls: the best row of `locus_from` inside it is.
    const zoomed = wideRegionTarget(selectionRegion, payloadRef.current?.location, MAX_FOLLOW_SPAN);
    if (zoomed) {
      traceGenome(ownIndex, 'region too wide to follow: browser opens on the best row in it', `${regionKey} -> ${zoomed}`);
      navigate(zoomed);
      return;
    }
    traceGenome(ownIndex, 'browser follows a region', regionKey);
    const session = viewState.session as unknown as {
      assemblyManager?: {
        get: (name: string) => { getCanonicalRefName?: (r: string) => string | undefined } | undefined;
      };
    };
    const asm = session.assemblyManager?.get(String(payloadRef.current?.assembly.name ?? ''));
    navigate(regionNavTarget(selectionRegion, (name) => canonicalRefName(asm, name)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [followActive, viewState, regionKey, navigate]);

  // A locus another tile hands over while this page is showing (the "Open in
  // genome browser" action on a tile of the same tab): go there and bring the
  // tile into view. Before the view exists it is kept for the build. It is
  // not a navigation of the reader's, so it is not remembered as one.
  useEffect(() => {
    const onPending = (event: Event) => {
      const detail = pendingLocusFor(event, dashboardId, ownIndex);
      if (!detail) return;
      const view = viewRef.current;
      if (view && aliveNode(view)) navigate(detail.locus);
      else eventLocusRef.current = detail.locus;
      if (detail.scroll !== false) {
        lgvBoxRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
      }
    };
    window.addEventListener(PENDING_LOCUS_EVENT, onPending);
    return () => window.removeEventListener(PENDING_LOCUS_EVENT, onPending);
  }, [dashboardId, ownIndex, navigate]);

  // ---- extra views (breakpoint split view, circular) -------------------------
  const [extraView, setExtraView] = useState<JBrowseExtraView | null>(null);
  const wantedViews = Array.isArray(metadata.views) ? metadata.views : [];

  // ---- force load ------------------------------------------------------------
  // ON: lift the density / byte limits of every display now, of every display
  // created later (a track opened, a display type switched) and again on zoom
  // out (the density lift only covers the zoom it was set at).
  useEffect(() => {
    if (!viewState || !toolbar.forceLoad) return;
    const view = viewState.session.view as unknown as LgvView;
    const displaysOf = (): unknown[] =>
      aliveNode(view) ? view.tracks.flatMap((t) => [...(t.displays ?? [])]) : [];
    const lift = (displays: unknown[], reload: 'always' | 'ifBlocked') => {
      try {
        for (const d of displays) {
          liftDisplayLimits(d, { bpPerPx: view.bpPerPx, reload, alive: aliveNode });
        }
      } catch (err) {
        console.warn('jbrowse: force load failed', err);
      }
    };
    lift(displaysOf(), 'always');
    let seen = new Set(displaysOf());
    const disposeDisplays = reaction(
      displaysOf,
      (displays) => {
        lift(
          displays.filter((d) => !seen.has(d)),
          'ifBlocked',
        );
        seen = new Set(displays);
      },
      { equals: comparer.shallow },
    );
    const disposeZoom = reaction(
      () => (aliveNode(view) ? view.bpPerPx : 0),
      () => lift(displaysOf(), 'ifBlocked'),
    );
    return () => {
      disposeDisplays();
      disposeZoom();
    };
  }, [viewState, toolbar.forceLoad]);

  // OFF (after having been ON): the lifted limits live on the display models
  // and JBrowse has no action to clear them, so re-open the affected tracks —
  // fresh displays come back with the configured limits.
  const prevForceLoad = useRef(toolbar.forceLoad);
  useEffect(() => {
    const wasOn = prevForceLoad.current;
    prevForceLoad.current = toolbar.forceLoad;
    if (!wasOn || toolbar.forceLoad) return;
    withView((view) => {
      const affected = new Set(
        view.tracks
          .filter((t) => (t.displays ?? []).some((d) => hasLiftedLimits(d, aliveNode)))
          .map((t) => t.configuration.trackId),
      );
      const reopen = planForceLoadReset(openTrackIds(view), affected);
      for (const id of reopen) view.hideTrack(id);
      for (const id of reopen) {
        try {
          showTrackPaired(view as unknown as LgvView, id, payloadRef.current, pairsModeRef.current);
        } catch (err) {
          console.warn(`jbrowse: cannot re-open track ${id}`, err);
        }
      }
    });
  }, [toolbar.forceLoad, withView]);

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

  // ---- chrome toggles -------------------------------------------------------
  const trackRows = payload?.track_rows ?? EMPTY_ROWS;
  const trackData = useMemo(() => trackRowsToColumns(trackRows), [trackRows]);
  // The two sides of a call (the breakpoint view's two panes): the stepper's
  // call, else the one the payload opened on.
  const mateOfCall = stepper.current ? stepper.current.mate_locus : (payload?.mate_location ?? null);
  const canBreakpoint = wantedViews.includes('breakpoint') && !!mateOfCall;
  const canCircular = wantedViews.includes('circular') && (payload?.sv_track_ids?.length ?? 0) > 0;
  useEffect(() => {
    if (!onToolbarNode) return;
    const toggles: ViewMenuItem[] = [
      {
        key: 'header',
        group: 'View',
        label: 'Navigation header',
        checked: toolbar.showHeader,
        onChange: () => setToggle('showHeader', 'header'),
      },
      {
        key: 'overview',
        group: 'View',
        label: 'Overview ruler',
        checked: toolbar.showOverview,
        onChange: () => setToggle('showOverview', 'overview'),
      },
      {
        key: 'status',
        group: 'View',
        label: 'Status bar',
        checked: toolbar.showStatus,
        onChange: () => setToggle('showStatus', 'status'),
      },
      {
        key: 'forceload',
        group: 'Loading',
        label: 'Force load',
        description: 'Load tracks past their download limit',
        checked: toolbar.forceLoad,
        onChange: () => setToggle('forceLoad', 'forceLoad'),
      },
      {
        key: 'scrolltracks',
        group: 'Interaction',
        label: 'Wheel scrolls the tracks',
        description: 'Off: the wheel scrolls the tile, then the dashboard. Cmd/Ctrl + wheel zooms',
        checked: toolbar.scrollTracks,
        onChange: () => setToggle('scrollTracks', 'scrollTracks'),
      },
      // Not offered when the tile's height follows its tracks (`auto_height`):
      // the two would chase each other.
      ...(metadata.auto_height === true
        ? []
        : [
            {
              key: 'fittracks',
              group: 'View' as const,
              label: 'Fit tracks to the tile',
              description: 'Signal tracks share the height of the tile. Always on in fullscreen',
              checked: toolbar.fitTracks,
              onChange: () => setToggle('fitTracks', 'fitTracks'),
            },
          ]),
    ];
    toggles.push({
      key: 'legend',
      group: 'View',
      label: 'Colour legend',
      description: 'What the colours of the open tracks stand for, in the status bar',
      checked: toolbar.showLegend,
      onChange: () => setToggle('showLegend', 'legend'),
    });
    if (locusFrom && metadata.show_density !== false) {
      toggles.push({
        key: 'density',
        group: 'View',
        label: 'Region density',
        description: 'Where the regions of the tile fall along the genome',
        checked: toolbar.showDensity,
        onChange: () => setToggle('showDensity', 'density'),
      });
    }
    if (hasMate) {
      toggles.push({
        key: 'bothsides',
        group: 'View',
        label: 'Both sides',
        description: 'Show the call and its mate side by side in one view',
        checked: toolbar.bothSides,
        onChange: toggleBothSides,
      });
    }
    if (metadata.follow_window !== false) {
      toggles.push({
        key: 'followwindow',
        group: 'Interaction',
        label: 'Follow other genome tiles',
        description: 'Move to the region another genome tile shows',
        checked: toolbar.followWindow,
        onChange: () => setToggle('followWindow', 'followWindow'),
      });
    }
    if (selectionEnabled && selectionMode === 'feature_click') {
      toggles.push({
        key: 'click',
        group: 'Interaction',
        label: 'Click filters the dashboard',
        description: "A feature click picks its track's sample",
        checked: toolbar.clickFilters,
        onChange: () => setToggle('clickFilters', 'clickFilters'),
      });
    }
    onToolbarNode(
      <React.Fragment key="jbrowse-toolbar">
        {SHOW_TRACK_MENU && (
          <TrackMenu
            key="tracks"
            rows={trackRows}
            openIds={openIds}
            portalTarget={fullscreenEl}
            disabled={!viewState}
            onToggle={onToggleTrack}
            onShowAll={showTracks}
            onHideAll={onHideAll}
            onBackToFilters={onBackToFilters}
          />
        )}
        {canSelectRegion && (
          <Tooltip
            key="region"
            label={regionActive ? 'Clear this region' : 'Use this region'}
            openDelay={400}
          >
            <ActionIcon
              size="sm"
              variant={regionActive ? 'filled' : 'subtle'}
              aria-label="Use this region"
              aria-pressed={regionActive}
              disabled={!viewState}
              onClick={toggleRegion}
              data-testid="jbrowse-use-region"
              data-active={regionActive ? 'true' : 'false'}
            >
              <Icon icon="tabler:crosshair" width={16} height={16} />
            </ActionIcon>
          </Tooltip>
        )}
        {canBreakpoint && (
          <Tooltip key="breakpoint" label={EXTRA_VIEW_TITLE.breakpoint} openDelay={400}>
            <ActionIcon
              size="sm"
              variant="subtle"
              aria-label={EXTRA_VIEW_TITLE.breakpoint}
              disabled={!viewState}
              onClick={() => setExtraView('breakpoint')}
              data-testid="jbrowse-open-breakpoint"
            >
              <Icon icon="tabler:arrows-split-2" width={16} height={16} />
            </ActionIcon>
          </Tooltip>
        )}
        {canCircular && (
          <Tooltip key="circular" label={EXTRA_VIEW_TITLE.circular} openDelay={400}>
            <ActionIcon
              size="sm"
              variant="subtle"
              aria-label={EXTRA_VIEW_TITLE.circular}
              disabled={!viewState}
              onClick={() => setExtraView('circular')}
              data-testid="jbrowse-open-circular"
            >
              <Icon icon="tabler:circle-dotted" width={16} height={16} />
            </ActionIcon>
          </Tooltip>
        )}
        <JBrowseDataPopover
          key="data"
          trackRows={trackData.rows}
          trackColumns={trackData.columns}
          regions={regionGrid}
          regionsLabel={regionsLabel}
        />
        <ViewMenu
          key="view"
          items={toggles}
          displaySettings={displaySettings}
          disabled={!viewState}
        />
      </React.Fragment>,
    );
  }, [
    onToolbarNode,
    toolbar,
    setToggle,
    selectionEnabled,
    selectionMode,
    trackRows,
    openIds,
    fullscreenEl,
    viewState,
    onToggleTrack,
    showTracks,
    onHideAll,
    onBackToFilters,
    hasMate,
    toggleBothSides,
    metadata.follow_window,
    metadata.auto_height,
    metadata.show_density,
    locusFrom,
    canBreakpoint,
    canCircular,
    trackData,
    regionGrid,
    regionsLabel,
    canSelectRegion,
    regionActive,
    toggleRegion,
    displaySettings,
  ]);
  useEffect(() => () => onToolbarNode?.(null), [onToolbarNode]);

  // ---- render ----------------------------------------------------------------
  const statusText = payload
    ? `${payload.shown_track_ids.length} shown · ${payload.matched_tracks}/${payload.total_tracks} tracks${
        payload.filter_applied ? ' match the filters' : ''
      }${payload.truncated ? ` (first ${payload.max_tracks ?? metadata.max_tracks ?? 20})` : ''}`
    : '';
  const colorScaleKey = JSON.stringify(colorScale);
  const sequentialLegendMap = useMemo(
    () => (colorScale && payload ? conditionSequentialMap(colorScale, payload.tracks as never[]) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, colorScaleKey],
  );
  // The colours the open tracks wear, by the same rules the view applies them:
  // the manifest's colour, else `color_by`'s, else the sample's.
  const legend = useMemo(() => {
    if (!payload || !toolbar.showLegend) return [];
    const rows = payload.track_rows;
    const byGroup = colorBy
      ? colorScale
        ? sequentialLegendMap
        : categoryColorMap(colorSource, colorBy, rows.map((r) => r.group ?? null), colorPalette)
      : null;
    const bySample = sampleColourMap(
      colorSource,
      sampleColourColumn(payload.selection_column, rows),
      rows,
      colorPalette,
    );
    return trackLegend(rows, openIds, (r) =>
      r.color || (byGroup ? byGroup.get(r.group ?? '') : r.sample ? bySample.get(r.sample) : null),
    );
  }, [payload, toolbar.showLegend, openIds, colorBy, colorSource, colorPalette, sequentialLegendMap]);
  // A `color_scale` draws a gradient between its extreme open values rather
  // than one swatch per value.
  const legendGradient = useMemo(
    () =>
      payload && toolbar.showLegend && colorScale && sequentialLegendMap
        ? legendRamp(payload.track_rows, openIds, sequentialLegendMap, colorScale.scheme)
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, toolbar.showLegend, openIds, sequentialLegendMap],
  );
  const compact = useDensity() === 'compact';
  const description =
    typeof metadata.description === 'string' && metadata.description ? metadata.description : '';
  const stepperShown =
    stepperEnabled && (stepper.total > 0 || sources.length > 1) && !!viewState;
  const densityShown =
    densityEnabled && !!viewState && (density.data?.tracks.length ?? 0) > 0;
  const ucscMissing = payload?.ucsc_missing ?? [];
  const selectedCount = Array.isArray(ownFilter?.value) ? (ownFilter!.value as unknown[]).length : 0;

  return (
    <Box
      ref={rootRef}
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
      <style>{HIGHLIGHT_CHIP_CSS}</style>
      {(metadata.title || stepperShown || selectionRegion) && (
        <Group
          gap="xs"
          pl="xs"
          pr={compact ? 28 : 'xs'}
          pt={6}
          pb={4}
          // Wide: one line, the description giving way. Narrow: the navigator
          // wraps to a line of its own rather than truncating its buttons.
          wrap={compact ? 'nowrap' : 'wrap'}
          style={{ flexShrink: 0, minWidth: 0, rowGap: 4 }}
          data-testid="jbrowse-header"
        >
          {metadata.title ? (
            // Compact (a linked view section): one line, the description moves
            // into the title's tooltip and the tile's kind is tagged.
            <Tooltip label={description} disabled={!compact || !description} multiline maw={320} openDelay={300}>
              <Text fw={600} size="sm" truncate style={{ flex: compact ? '0 1 auto' : '0 0 auto', minWidth: 0 }}>
                {metadata.title as string}
              </Text>
            </Tooltip>
          ) : null}
          {compact && metadata.title ? (
            <AdvancedVizKindContext.Provider value={GENOME_KIND_LABEL}>
              <VizKindBadge />
            </AdvancedVizKindContext.Provider>
          ) : null}
          {!compact && description && (
            <Text c="dimmed" size="xs" truncate title={description} style={{ flex: '1 1 120px', minWidth: 0 }}>
              {description}
            </Text>
          )}
          {selectionRegion && selectionSourceIndex && Number.isFinite(selectionRegion.end) ? (
            <Box style={{ flex: '0 1 auto', minWidth: 0 }}>
              <LinkedTileChip
                role="follows"
                otherIndex={selectionSourceIndex}
                fallbackTitle="Genome view"
                explanation={
                  `This browser opens on the region selected in ` +
                  `${tileTitle(selectionSourceIndex) ?? 'the genome view'}, shaded here. ` +
                  'Its view is drawn there as a dashed band in this colour, and the axis there ' +
                  'follows when you move out of it.'
                }
                data-testid="jbrowse-link-chip"
              />
            </Box>
          ) : null}
          {stepperShown && (
            <Group gap={0} wrap="nowrap" ml="auto" style={{ flex: '0 0 auto', minWidth: 0 }}>
              <CallNavigator
                navigator={stepper}
                sources={sources}
                scoreLabel={locusFrom?.sort_by ?? null}
                compact={compact}
                tileWidth={tileWidth}
                dashboardId={dashboardId}
                index={String(metadata.index)}
                filters={fetchFilters}
                versionBody={versionBody}
                onNavigate={goToCall}
                onPrev={() => void goStep(-1)}
                onNext={() => void goStep(1)}
              />
            </Group>
          )}
        </Group>
      )}
      {densityShown && (
        <Box px="xs" pb={4} style={{ flexShrink: 0 }}>
          <DensityStrip
            data={density.data}
            sources={enabledSourceSpecs}
            visible={visibleRegions}
            width={Math.max(0, tileWidth - 16)}
            group={densityGroup}
            onGroupChange={setDensityGroup}
            onNavigate={navigate}
            regions={assemblyRegions}
            compact={compact}
          />
        </Box>
      )}
      {payload === null && loading && <ComponentSkeleton variant="block" />}
      {error && !payload && (
        <Text size="sm" c="red" p="md" className="dashboard-error">
          Genome browser failed: {error}
        </Text>
      )}
      {viewState && (
        <Box
          ref={lgvBoxRef}
          className="depictio-jbrowse-host"
          style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}
        >
          <EmbeddedLGV
            viewState={viewState}
            muiThemeOverrides={muiThemeOverrides}
            leaveFeatureWidget={leaveFeatureWidget}
          />
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
          {legendGradient && (
            <Tooltip label={legendGradient.values.join(' > ')} withinPortal={false}>
              <Group gap={4} wrap="nowrap" data-testid="jbrowse-legend-ramp" style={{ flexShrink: 0 }}>
                <Text size="xs" c="dimmed">
                  {legendGradient.from}
                </Text>
                <Box
                  style={{
                    width: 56,
                    height: 8,
                    borderRadius: 4,
                    background: `linear-gradient(to right, ${legendGradient.stops.join(', ')})`,
                  }}
                />
                <Text size="xs" c="dimmed">
                  {legendGradient.to}
                </Text>
              </Group>
            </Tooltip>
          )}
          {legend.length > 0 && !legendGradient && (
            <Group
              gap={8}
              wrap="nowrap"
              data-testid="jbrowse-legend"
              style={{ minWidth: 0, overflow: 'hidden', flexShrink: 1 }}
            >
              {legend.map((entry) => (
                <Tooltip
                  key={entry.color}
                  label={entry.names.join(', ')}
                  withinPortal={false}
                  disabled={entry.names.length < 2}
                >
                  <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
                    <ColorSwatch color={entry.color} size={8} withShadow={false} />
                    <Text size="xs" c="dimmed">
                      {entry.label}
                    </Text>
                  </Group>
                </Tooltip>
              ))}
            </Group>
          )}
          {payload.filter_applied && (
            <Badge size="xs" variant="light">
              filtered
            </Badge>
          )}
          {ucscMissing.length > 0 && (
            <Tooltip label={`UCSC tracks not found: ${ucscMissing.join(', ')}`} withinPortal={false}>
              <Badge size="xs" variant="light" color="orange" data-testid="jbrowse-ucsc-missing">
                {ucscMissing.length} UCSC missing
              </Badge>
            </Tooltip>
          )}
          {toolbar.forceLoad && (
            <Badge size="xs" variant="light" color="gray">
              force load
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
      <JBrowseViewsModal
        view={extraView}
        onClose={() => setExtraView(null)}
        payload={payload}
        locus={stepper.current?.locus ?? payload?.location ?? ''}
        mateLocus={mateOfCall ?? ''}
        openTrackIds={openIds}
        portalTarget={fullscreenEl}
      />
    </Box>
  );
};

export default JBrowseRenderer;

/**
 * The report host of the static runtime: the dashboard's own renderers, drawn
 * into the tiles of a Quarto report.
 *
 * ONE React root, ONE manifest, ONE filter store: every tile is a portal of
 * this component into its placeholder, so a filter picked in the panel (or a
 * selection made on a figure) recomputes every tile of the report in place,
 * through the same shimmed data path the bundle uses. What the bundle's App
 * adds on top (the shell, the grid, tabs, sections, groups, comments) is the
 * dashboard's, not the document's: the document keeps its own headings, its
 * narrative and its order, and only the tiles change hands.
 *
 * A tile is drawn only when the runtime can draw it at the report's state
 * (`tileMountVerdict`); until then, and whenever a renderer throws, the
 * export's own output for it (its fallback) stays on screen.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Badge, Button, Group, Text } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import {
  AvailableFilterValuesProvider,
  CategoryColorsContext,
  ComponentRenderer,
  FilterPanel,
  COLOR_BY_NONE,
  FunnelView,
  activeFiltersFor,
  bulkComputeCards,
  enrichFilterWithDcId,
  groupsRenderPayload,
  groupsToFilters,
  hasLiveValues,
  isControlsPlacement,
  mergeFiltersBySource,
  resolveGroupRender,
  useCategoricalColumns,
  useColorByColumnRender,
} from 'depictio-react-core';
import type {
  CategoryColorSource,
  FilterSectionSpec,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';
import {
  REPORT_MOUNTED_ATTR,
  compactPanelSections,
  componentFor,
  formatTileRef,
  reportCategorySource,
  tabDoc,
  type BundleManifest,
  type FilterChannel,
  type ReportSectionSpec,
  type TileRef,
} from 'depictio-static-core';

import { familyMetadata } from '../bundle';
import { initialSelectionGroups } from '../selectionGroupsShim';

/** Same pause as the viewer's (App.tsx `FILTER_DEBOUNCE_MS`). */
const FILTER_DEBOUNCE_MS = 250;

/** A tile's height in the document. The dashboard sizes tiles by its grid;
 *  a document stacks them full width, so plots get the height of a figure
 *  and cards and controls their own. An advanced viz is a little taller: its
 *  controls sit behind the settings icon (see `withReportControls`), so the
 *  whole box is the plot's. */
const TILE_HEIGHT: Record<string, number> = {
  figure: 440,
  advanced_viz: 560,
  table: 460,
  multiqc: 460,
  map: 460,
  image: 420,
  jbrowse: 420,
};

const placed = new WeakMap<object, StoredMetadata>();

/** Where the report's settings place an advanced viz's controls: the element
 *  the export writes for its runtime (`SETTINGS_MARKER_ID` in the generator),
 *  absent from reports exported before it. */
function reportVizControls(): unknown {
  if (typeof document === 'undefined') return undefined;
  return document.getElementById('depictio-report-settings')?.dataset.vizControls;
}

/** An advanced viz in a report keeps its controls closed, behind the settings
 *  icon, unless something placed them: the tile itself, then the report's
 *  settings, then the dashboard. Docked controls took the room of the plot.
 *  The same object comes back for the same tile, so a render does not hand
 *  the renderer new metadata. */
function withReportControls(m: StoredMetadata, dashboardDefault: unknown): StoredMetadata {
  if (m.component_type !== 'advanced_viz' || isControlsPlacement(m.controls_placement)) return m;
  let out = placed.get(m);
  if (!out) {
    const report = reportVizControls();
    const placement = isControlsPlacement(report)
      ? report
      : isControlsPlacement(dashboardDefault)
        ? dashboardDefault
        : 'popover';
    out = { ...m, controls_placement: placement } as StoredMetadata;
    placed.set(m, out);
  }
  return out;
}

export interface ReportTile {
  /** The placeholder the export wrote. */
  host: HTMLElement;
  /** The node the runtime draws into (a child of `host`). */
  mount: HTMLElement;
  refs: TileRef[];
}

export interface ReportPanel {
  host: HTMLElement;
  mount: HTMLElement;
  tabId: string;
}

interface Props {
  manifest: BundleManifest;
  tiles: ReportTile[];
  panels: ReportPanel[];
  /** The combined file's one filter state, shared with its dashboard view. */
  channel?: FilterChannel | null;
}

/** The name this view writes to a shared filter channel under. */
const CHANNEL_SOURCE = 'report';

/** One renderer crash restores that tile's fallback; the others carry on. */
class TileBoundary extends React.Component<
  { onError: () => void; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn('[depictio report] a tile failed to render; its fallback stays', error);
    this.props.onError();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/** How far ahead of the viewport a tile starts drawing: close enough that it
 *  is ready when scrolled to, far enough from the rest of a long report that
 *  the first paint only pays for what is on screen. */
const MOUNT_MARGIN = '600px 0px';

/**
 * The placeholders that have come into view (or near it), once and for all.
 *
 * A report is long and mostly folded (`dpx-fold`, the export's own script):
 * drawing every tile up front draws dozens of plots nobody has opened, each at
 * a size it cannot measure inside a hidden fold. A tile mounts the first time
 * it nears the viewport, which also covers a fold being opened: a hidden
 * element never intersects, and one revealed does. Without an
 * IntersectionObserver every placeholder counts as seen.
 */
function useSeen(hosts: HTMLElement[]): ReadonlySet<HTMLElement> {
  const [seen, setSeen] = useState<ReadonlySet<HTMLElement>>(() =>
    typeof IntersectionObserver === 'undefined' ? new Set(hosts) : new Set(),
  );
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        const hits = entries.filter((e) => e.isIntersecting).map((e) => e.target as HTMLElement);
        if (hits.length === 0) return;
        for (const el of hits) observer.unobserve(el);
        setSeen((prev) => {
          const next = new Set(prev);
          for (const el of hits) next.add(el);
          return next;
        });
      },
      { rootMargin: MOUNT_MARGIN },
    );
    for (const host of hosts) observer.observe(host);
    return () => observer.disconnect();
  }, [hosts]);
  return seen;
}

/** Marks its placeholder drawn once React has committed it. */
const Mounted: React.FC<{ host: HTMLElement; children: React.ReactNode }> = ({
  host,
  children,
}) => {
  useEffect(() => {
    host.setAttribute(REPORT_MOUNTED_ATTR, '');
    return () => host.removeAttribute(REPORT_MOUNTED_ATTR);
  }, [host]);
  return <>{children}</>;
};

const ReportRuntime: React.FC<Props> = ({ manifest, tiles, panels, channel = null }) => {
  const entryId = manifest.dashboard.id;
  const metadata = useMemo(() => familyMetadata() as unknown as StoredMetadata[], []);
  const entryInteractive = useMemo(() => {
    const doc = manifest.dashboard.doc as { stored_metadata?: StoredMetadata[] };
    return (doc.stored_metadata ?? []).filter((m) => m.component_type === 'interactive');
  }, [manifest]);

  // The report opens on the exported state, and "Reset" goes back to it: the
  // document narrates that state, and its fallbacks and frozen tiles were
  // drawn at it. No exported filter means no filter, not the dashboard's
  // defaults (a reader who cleared one exported it cleared).
  const initialFilters = useMemo<InteractiveFilter[]>(
    () => (manifest.initial_filters ?? []) as unknown as InteractiveFilter[],
    [manifest],
  );
  // In a combined file the dashboard view may have moved the filters already.
  const [filters, setFilters] = useState<InteractiveFilter[]>(
    () => (channel?.get() as InteractiveFilter[] | null) ?? initialFilters,
  );
  const [deferredFilters] = useDebouncedValue(filters, FILTER_DEBOUNCE_MS);
  const initialKey = useMemo(() => JSON.stringify(initialFilters), [initialFilters]);
  const touched = filters !== initialFilters && JSON.stringify(filters) !== initialKey;

  // One filter state for both views of a combined file: every change is
  // published, and a change made in the dashboard lands here.
  useEffect(() => {
    channel?.set(filters, CHANNEL_SOURCE);
  }, [channel, filters]);
  useEffect(
    () => channel?.subscribe(CHANNEL_SOURCE, (next) => setFilters(next as InteractiveFilter[])),
    [channel],
  );

  // The exported selection groups, colour-by and split. A report has no group
  // panel: they are the state the document narrates, fixed. The groups that
  // were filtering project into filters here, composed after the reader's own
  // (as the viewer's App does), so "Back to the exported state" and the
  // filter panel never see them.
  const seeded = useMemo(() => initialSelectionGroups(), [manifest]);
  const groupFilters = useMemo(() => groupsToFilters(seeded?.groups ?? []), [seeded]);
  const colorBy = seeded?.colorBy ?? COLOR_BY_NONE;
  const colorByColumns = useCategoricalColumns(colorBy.kind === 'column' ? metadata : undefined);
  const colorByColumnRender = useColorByColumnRender(colorBy, colorByColumns);
  const groupRender = useMemo(
    () =>
      resolveGroupRender(
        colorBy,
        groupsRenderPayload(seeded?.groups ?? []),
        colorByColumnRender,
        seeded?.displayMode ?? 'color',
        seeded?.showOther ?? true,
      ),
    [seeded, colorBy, colorByColumnRender],
  );
  const filtersWithGroups = useMemo(
    () => (groupFilters.length > 0 ? [...filters, ...groupFilters] : filters),
    [filters, groupFilters],
  );
  const deferredWithGroups = useMemo(
    () => (groupFilters.length > 0 ? [...deferredFilters, ...groupFilters] : deferredFilters),
    [deferredFilters, groupFilters],
  );

  const onFilterChange = useCallback(
    (update: InteractiveFilter) => {
      setFilters((prev) => mergeFiltersBySource(prev, enrichFilterWithDcId(update, metadata)));
    },
    [metadata],
  );
  const resetFilters = useCallback(() => setFilters(initialFilters), [initialFilters]);

  // Each tab's colours, as the viewer hands its own tab's document to
  // CategoryColorsContext: a tile resolves "Bacteria" to the colour its tab
  // (or the main tab) pins, not to the palette's next hue.
  const colorSources = useMemo(() => {
    const out = new Map<string, CategoryColorSource | null>();
    for (const tile of tiles) {
      const tabId = tile.refs[0]?.tabId ?? '';
      if (!out.has(tabId)) {
        out.set(tabId, reportCategorySource(manifest, tabId) as CategoryColorSource | null);
      }
    }
    return out;
  }, [tiles, manifest]);

  // Only what has come into view is drawn (see useSeen).
  const hosts = useMemo(
    () => [...tiles.map((t) => t.host), ...panels.map((p) => p.host)],
    [tiles, panels],
  );
  const seen = useSeen(hosts);

  // Each panel's tab: the entry tab's in the Filters part, a child tab's own
  // in that tab's part (the export writes one where the tab has filters).
  // The panel, compact: the report's controls are a block of the page, not the
  // app's rail, so every section opens folded but one narrowing the exported
  // view. A section's own filter bar on the dashboard is a section here too.
  const panelSpecs = useMemo(() => {
    const active = new Set(activeFiltersFor(initialFilters).map((f) => String(f.index)));
    const out = new Map<
      string,
      { components: StoredMetadata[]; sections: FilterSectionSpec[]; layout: unknown }
    >();
    for (const panel of panels) {
      if (out.has(panel.tabId)) continue;
      const doc = tabDoc(manifest, panel.tabId) as {
        stored_metadata?: StoredMetadata[];
        filter_sections?: ReportSectionSpec[];
        grid_sections?: ReportSectionSpec[];
        left_panel_layout_data?: unknown;
      } | null;
      const components =
        panel.tabId === entryId
          ? entryInteractive
          : (doc?.stored_metadata ?? []).filter((m) => m.component_type === 'interactive');
      out.set(panel.tabId, {
        components,
        sections: compactPanelSections(
          doc?.filter_sections,
          components,
          active,
          doc?.grid_sections ?? [],
        ) as unknown as FilterSectionSpec[],
        layout: doc?.left_panel_layout_data,
      });
    }
    return out;
  }, [manifest, panels, entryId, entryInteractive, initialFilters]);

  // Tiles that failed: their fallback comes back.
  const [failed, setFailed] = useState<ReadonlySet<HTMLElement>>(() => new Set());
  const fail = useCallback((host: HTMLElement) => {
    setFailed((prev) => new Set(prev).add(host));
  }, []);

  // Cards (and text tiles with live values) are computed in one call, as the
  // viewer does: ComponentRenderer draws a card from the value it is handed.
  const cardIds = useMemo(() => {
    const ids: string[] = [];
    for (const tile of tiles) {
      for (const ref of tile.refs) {
        const m = componentFor(manifest, ref) as unknown as StoredMetadata | null;
        if (m && (m.component_type === 'card' || hasLiveValues(m))) ids.push(ref.index);
      }
    }
    return ids;
  }, [tiles, manifest]);
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardSecondary, setCardSecondary] = useState<Record<string, Record<string, unknown>>>({});
  const [cardsLoading, setCardsLoading] = useState(false);
  const cardRound = useRef(0);
  const filterKey = JSON.stringify(deferredWithGroups);
  useEffect(() => {
    if (cardIds.length === 0) return;
    const round = ++cardRound.current;
    setCardsLoading(true);
    bulkComputeCards(entryId, deferredWithGroups, cardIds)
      .then((res) => {
        if (round !== cardRound.current) return;
        setCardValues(res.values ?? {});
        setCardSecondary(res.secondary_values ?? {});
      })
      .catch((err) => console.warn('[depictio report] card compute failed', err))
      .finally(() => {
        if (round === cardRound.current) setCardsLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entryId, filterKey, cardIds]);

  const funnelDefault =
    (manifest.dashboard.doc as { funnel_filtering?: boolean }).funnel_filtering !== false;
  const [funnelEnabled, setFunnelEnabled] = useState(funnelDefault);
  const [funnelViewOpen, setFunnelViewOpen] = useState(false);

  const renderComponent = (ref: TileRef) => {
    const own = componentFor(manifest, ref) as unknown as StoredMetadata | null;
    if (!own) return null;
    const m = withReportControls(
      own,
      (tabDoc(manifest, ref.tabId) as { advanced_viz_controls?: unknown } | null)
        ?.advanced_viz_controls,
    );
    const type = String(m.component_type ?? '');
    const height = TILE_HEIGHT[type];
    return (
      <div
        key={ref.index}
        className="depictio-report-tile-body"
        data-component-type={type}
        // A renderer taller than its box (a gallery's grid) scrolls inside
        // it instead of running over the caption below.
        style={height ? { height, overflow: 'auto' } : undefined}
      >
        <ComponentRenderer
          metadata={m}
          filters={type === 'card' ? deferredWithGroups : filtersWithGroups}
          groupRender={groupRender}
          onFilterChange={onFilterChange}
          dashboardId={ref.tabId}
          cardValue={cardValues[ref.index]}
          cardSecondaryValues={cardSecondary[ref.index]}
          cardLoading={cardsLoading}
        />
      </div>
    );
  };

  return (
    <AvailableFilterValuesProvider
      dashboardMetadata={metadata}
      funnel={{ enabled: funnelEnabled, dashboardId: entryId, filters: deferredFilters }}
    >
      {tiles.map((tile, i) =>
        failed.has(tile.host) || !seen.has(tile.host)
          ? null
          : createPortal(
              <TileBoundary onError={() => fail(tile.host)}>
                <Mounted host={tile.host}>
                  <CategoryColorsContext.Provider
                    value={colorSources.get(tile.refs[0]?.tabId ?? '') ?? null}
                  >
                    {/* `dashboard-content`: the Paper chrome styles a tile under
                        it (glass.css), as it does on the dashboard. */}
                    <div data-testid="dashboard-content" className="depictio-report-content">
                      {tile.refs.length > 1 ? (
                        <div className="depictio-report-row">{tile.refs.map(renderComponent)}</div>
                      ) : (
                        renderComponent(tile.refs[0])
                      )}
                    </div>
                  </CategoryColorsContext.Provider>
                </Mounted>
              </TileBoundary>,
              tile.mount,
              // By position: a highlight draws the same component a second
              // time, and two portals keyed alike would drop one.
              `${i}:${tile.refs.map(formatTileRef).join(' ')}`,
            ),
      )}
      {panels
        .filter((panel) => seen.has(panel.host))
        .map((panel) =>
          createPortal(
            <TileBoundary onError={() => fail(panel.host)}>
              <Mounted host={panel.host}>
                <div className="depictio-report-filters-body" data-testid="depictio-report-filters">
                  <Group justify="space-between" mb="xs" wrap="nowrap">
                    <Text size="sm" c="dimmed">
                      {touched
                        ? channel
                          ? 'Filtered in this file (here or in the dashboard view): every ' +
                            'interactive tile below follows. The text of the report, its numbers ' +
                            'and its static figures still describe the exported state.'
                          : 'Filtered in this page: every interactive tile below follows. The text ' +
                            'of the report still describes the exported state.'
                        : channel
                          ? 'The exported state. Change a filter here or in the dashboard view and ' +
                            'every interactive tile follows, in both, with no server.'
                          : 'The exported state. Change a filter and every interactive tile below ' +
                            'recomputes in this page, with no server.'}
                    </Text>
                    {touched ? (
                      <Button
                        size="xs"
                        variant="light"
                        onClick={resetFilters}
                        data-testid="depictio-report-reset"
                      >
                        Back to the exported state
                      </Button>
                    ) : (
                      <Badge variant="light" color="gray">
                        Exported state
                      </Badge>
                    )}
                  </Group>
                  <div className="depictio-report-panel">
                    <FilterPanel
                      components={panelSpecs.get(panel.tabId)?.components ?? []}
                      allMetadata={metadata}
                      filters={filters}
                      onFilterChange={onFilterChange}
                      onResetAllFilters={resetFilters}
                      layoutData={panelSpecs.get(panel.tabId)?.layout}
                      filterSections={panelSpecs.get(panel.tabId)?.sections}
                      dashboardId={entryId}
                      stateScopeId={`report:${entryId}`}
                      funnel={{
                        enabled: funnelEnabled,
                        onToggle: () => setFunnelEnabled((v) => !v),
                        onOpenView: () => setFunnelViewOpen(true),
                      }}
                    />
                  </div>
                </div>
              </Mounted>
            </TileBoundary>,
            panel.mount,
            `panel:${panel.tabId}`,
          ),
        )}
      <FunnelView
        opened={funnelViewOpen}
        onClose={() => setFunnelViewOpen(false)}
        dashboardId={entryId}
        filters={deferredFilters}
      />
    </AvailableFilterValuesProvider>
  );
};

export default ReportRuntime;

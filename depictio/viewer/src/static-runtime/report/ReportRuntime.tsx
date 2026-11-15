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
  ComponentRenderer,
  FilterPanel,
  FunnelView,
  bulkComputeCards,
  enrichFilterWithDcId,
  hasLiveValues,
  mergeFiltersBySource,
  withInteractiveDefaults,
} from 'depictio-react-core';
import type { InteractiveFilter, StoredMetadata } from 'depictio-react-core';
import {
  REPORT_MOUNTED_ATTR,
  componentFor,
  type BundleManifest,
  type TileRef,
} from 'depictio-static-core';

import { familyMetadata } from '../bundle';

/** Same pause as the viewer's (App.tsx `FILTER_DEBOUNCE_MS`). */
const FILTER_DEBOUNCE_MS = 250;

/** A tile's height in the document. The dashboard sizes tiles by its grid;
 *  a document stacks them full width, so plots get the height of a figure
 *  and cards and controls their own. */
const TILE_HEIGHT: Record<string, number> = {
  figure: 440,
  advanced_viz: 480,
  table: 460,
  multiqc: 460,
  map: 460,
  image: 420,
  jbrowse: 420,
};

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
}

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

const ReportRuntime: React.FC<Props> = ({ manifest, tiles, panels }) => {
  const entryId = manifest.dashboard.id;
  const metadata = useMemo(() => familyMetadata() as unknown as StoredMetadata[], []);
  const entryInteractive = useMemo(() => {
    const doc = manifest.dashboard.doc as { stored_metadata?: StoredMetadata[] };
    return (doc.stored_metadata ?? []).filter((m) => m.component_type === 'interactive');
  }, [manifest]);

  // The report opens on the exported state; "Reset" goes back to it, not to
  // the dashboard's defaults — the document narrates the former.
  const initialFilters = useMemo<InteractiveFilter[]>(() => {
    const exported = (manifest.initial_filters ?? []) as unknown as InteractiveFilter[];
    return exported.length > 0 ? exported : withInteractiveDefaults([], entryInteractive);
  }, [manifest, entryInteractive]);
  const [filters, setFilters] = useState<InteractiveFilter[]>(initialFilters);
  const [deferredFilters] = useDebouncedValue(filters, FILTER_DEBOUNCE_MS);
  const touched = filters !== initialFilters;

  const onFilterChange = useCallback(
    (update: InteractiveFilter) => {
      setFilters((prev) => mergeFiltersBySource(prev, enrichFilterWithDcId(update, metadata)));
    },
    [metadata],
  );
  const resetFilters = useCallback(() => setFilters(initialFilters), [initialFilters]);

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
  const filterKey = JSON.stringify(deferredFilters);
  useEffect(() => {
    if (cardIds.length === 0) return;
    const round = ++cardRound.current;
    setCardsLoading(true);
    bulkComputeCards(entryId, deferredFilters, cardIds)
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
    const m = componentFor(manifest, ref) as unknown as StoredMetadata | null;
    if (!m) return null;
    const type = String(m.component_type ?? '');
    const height = TILE_HEIGHT[type];
    return (
      <div
        key={ref.index}
        className="depictio-report-tile-body"
        data-component-type={type}
        style={height ? { height } : undefined}
      >
        <ComponentRenderer
          metadata={m}
          filters={type === 'card' ? deferredFilters : filters}
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
      {tiles
        .filter((tile) => !failed.has(tile.host))
        .map((tile) =>
          createPortal(
            <TileBoundary onError={() => fail(tile.host)}>
              <Mounted host={tile.host}>
                {/* `dashboard-content`: the Paper chrome styles a tile under it
                    (glass.css), as it does on the dashboard. */}
                <div data-testid="dashboard-content" className="depictio-report-content">
                  {tile.refs.length > 1 ? (
                    <div className="depictio-report-row">{tile.refs.map(renderComponent)}</div>
                  ) : (
                    renderComponent(tile.refs[0])
                  )}
                </div>
              </Mounted>
            </TileBoundary>,
            tile.mount,
            tile.refs.map((r) => r.index).join(' '),
          ),
        )}
      {panels.map((panel) =>
        createPortal(
          <TileBoundary onError={() => fail(panel.host)}>
            <Mounted host={panel.host}>
              <div className="depictio-report-filters-body" data-testid="depictio-report-filters">
                <Group justify="space-between" mb="xs" wrap="nowrap">
                  <Text size="sm" c="dimmed">
                    {touched
                      ? 'Filtered in this page: every interactive tile below follows. The text ' +
                        'of the report still describes the exported state.'
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
                <FilterPanel
                  components={
                    panel.tabId === entryId
                      ? entryInteractive
                      : metadata.filter((m) => m.component_type === 'interactive')
                  }
                  allMetadata={metadata}
                  filters={filters}
                  onFilterChange={onFilterChange}
                  onResetAllFilters={resetFilters}
                  layoutData={
                    (manifest.dashboard.doc as { left_panel_layout_data?: unknown })
                      .left_panel_layout_data
                  }
                  filterSections={
                    (manifest.dashboard.doc as { filter_sections?: never }).filter_sections
                  }
                  dashboardId={entryId}
                  stateScopeId={`report:${entryId}`}
                  funnel={{
                    enabled: funnelEnabled,
                    onToggle: () => setFunnelEnabled((v) => !v),
                    onOpenView: () => setFunnelViewOpen(true),
                  }}
                />
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

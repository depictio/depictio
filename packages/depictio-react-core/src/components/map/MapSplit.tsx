import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Group, Paper, Text, useMantineColorScheme } from '@mantine/core';

import { renderMap } from '../../api';
import type { InteractiveFilter, StoredMetadata } from '../../api';
import { useDataVersionRequest } from '../../dataVersions';
import { renderDefinitionKey } from '../../renderKey';
import { filtersExcludingOwn } from '../../selection';
import type { PanelSpec } from '../../splitPanels';
import { useReportLoadStatus } from '../DashboardLoadingProvider';
import SplitPanels from '../advanced_viz/SplitPanels';
import { parseMapFit } from './fit';
import type { MapFitSpec } from './fit';
import { allSignaturesEqual, sharedMapView } from './split';
import type { MapSharedView, PanelBox } from './split';

/** What one panel tells the split about itself. */
export interface MapPanelReport {
  /** Has a figure on screen (or failed to get one). */
  status: 'loading' | 'ready' | 'error';
  /** A fetch is in flight, even if a previous figure is still showing. */
  busy: boolean;
  /** `figureSignature` of what it drew. */
  signature: string | null;
  /** Its drawing area, net of the figure's margins. */
  box: PanelBox | null;
}

/** What the split hands each panel: it is a read-only member of a set, not a
 *  map of its own. */
export interface MapPanelShared {
  /** The panel's name, which keys its reports. */
  key: string;
  /** The one framing every panel uses. `null` until it is known. */
  view: MapSharedView | null;
  /** The framing is still being worked out: draw nothing yet rather than a map
   *  that is about to jump. False once there is a view, or when there will not
   *  be one (the panel then frames itself). */
  hold: boolean;
  /** Tell the split something about this panel. */
  report: (key: string, patch: Partial<MapPanelReport>) => void;
}

const EMPTY_REPORT: MapPanelReport = { status: 'loading', busy: true, signature: null, box: null };

function sameReport(a: MapPanelReport, b: MapPanelReport): boolean {
  return (
    a.status === b.status &&
    a.busy === b.busy &&
    a.signature === b.signature &&
    a.box?.width === b.box?.width &&
    a.box?.height === b.box?.height
  );
}

export interface MapSplitProps {
  dashboardId: string;
  metadata: StoredMetadata;
  /** The dashboard's filters, before any panel's constraints. */
  filters: InteractiveFilter[];
  panels: PanelSpec[];
  refreshTick?: number;
  bare?: boolean;
  /** Builds one panel's map. */
  renderPanel: (
    filters: InteractiveFilter[],
    shared: MapPanelShared,
  ) => React.ReactNode;
  /** Every panel came back with the same points: the groups reach nothing on
   *  this map's dataset. The caller draws the map whole. */
  onIneffective: () => void;
}

/**
 * A map as small multiples: one map per group, each from that group's rows,
 * all framed the same way.
 *
 * The shared framing is what makes the panels comparable. The extent comes from
 * the *unsplit* data (a second, ordinary `render_map` whose figure is thrown
 * away and whose `metadata.fit` is kept), so a panel holding a handful of
 * points is not zoomed in on them and the same place sits in the same spot in
 * every panel. It is fitted against the smallest panel measured, which keeps
 * every point inside every panel.
 */
const MapSplit: React.FC<MapSplitProps> = ({
  dashboardId,
  metadata,
  filters,
  panels,
  refreshTick,
  bare = false,
  renderPanel,
  onIneffective,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const { body: versionBody, key: versionKey, definitionVersionId } = useDataVersionRequest();
  const definitionKey = renderDefinitionKey(metadata, definitionVersionId);

  // The component's own selection is not part of any panel's data (a panel
  // strips it, and does not emit one), so the unsplit fit ignores it too.
  const filtersForFit = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'map_selection'),
    [filters, metadata.index],
  );

  const [fit, setFit] = useState<{
    state: 'loading' | 'ready' | 'none';
    spec: MapFitSpec | null;
  }>({ state: 'loading', spec: null });

  useEffect(() => {
    let cancelled = false;
    setFit((prev) => (prev.state === 'ready' ? prev : { state: 'loading', spec: null }));
    renderMap(dashboardId, metadata.index, filtersForFit, theme, versionBody)
      .then((res) => {
        if (cancelled) return;
        const spec = parseMapFit(res.metadata);
        setFit({ state: spec ? 'ready' : 'none', spec });
      })
      .catch(() => {
        // No unsplit framing: the panels fall back to framing themselves,
        // which is the old behaviour of a map and still shows every group.
        if (!cancelled) setFit({ state: 'none', spec: null });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filtersForFit), theme, refreshTick, versionKey, definitionKey]);

  const [reports, setReports] = useState<Record<string, MapPanelReport>>({});
  const report = useCallback((key: string, patch: Partial<MapPanelReport>) => {
    setReports((prev) => {
      const current = prev[key] ?? EMPTY_REPORT;
      const next = { ...current, ...patch };
      return sameReport(current, next) ? prev : { ...prev, [key]: next };
    });
  }, []);

  const names = useMemo(() => panels.map((p) => p.name), [panels]);
  const mine = names.map((name) => reports[name] ?? EMPTY_REPORT);

  // The view waits for every panel to have said how big it is (or failed): a
  // panel still to report might be the smallest.
  const boxes = mine.map((r) => r.box).filter((b): b is PanelBox => b != null);
  const allMeasured = mine.every((r) => r.box != null || r.status === 'error');
  const boxKey = boxes.map((b) => `${b.width}x${b.height}`).join(',');
  const view = useMemo(
    () => (allMeasured ? sharedMapView(fit.spec, boxes) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fit.spec, allMeasured, boxKey],
  );
  const hold = fit.state === 'loading' || (fit.state === 'ready' && view == null);

  // The tile counts as loaded once every panel has a figure or has failed.
  const settled = mine.every((r) => r.status !== 'loading');
  const allFailed = mine.every((r) => r.status === 'error');
  useReportLoadStatus(
    metadata.index,
    settled && fit.state !== 'loading' ? (allFailed ? 'error' : 'ready') : 'loading',
  );

  // Every panel on the same picture: the groups narrowed nothing here.
  const quiet = mine.every((r) => r.status === 'ready' && !r.busy);
  const ineffective = quiet && allSignaturesEqual(mine.map((r) => r.signature));
  const ineffectiveRef = useRef(onIneffective);
  ineffectiveRef.current = onIneffective;
  useEffect(() => {
    if (ineffective) ineffectiveRef.current();
  }, [ineffective]);

  // SplitPanels would fingerprint rows published through the advanced_viz
  // extras, which a map does not publish: the check above replaces it.
  const noop = useCallback(() => {}, []);

  const Shell = bare ? Box : Paper;
  const shellProps = bare ? {} : { p: 'sm' as const, withBorder: true, radius: 'md' as const };

  return (
    <Shell
      {...shellProps}
      style={{ flex: 1, minHeight: 0, height: '100%', display: 'flex', flexDirection: 'column' }}
    >
      {metadata.title && !bare && (
        <Group gap="xs" mb="xs" wrap="nowrap" className="dc-tile-head">
          <Text fw={600} size="sm">
            {metadata.title}
          </Text>
        </Group>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <SplitPanels
          panels={panels}
          filters={filters}
          onIneffective={noop}
          renderPanel={(panelFilters, key) =>
            renderPanel(panelFilters, { key, view, hold, report })
          }
        />
      </div>
    </Shell>
  );
};

export default MapSplit;

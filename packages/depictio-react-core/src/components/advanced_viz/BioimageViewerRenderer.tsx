import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Center,
  Checkbox,
  ColorInput,
  ColorSwatch,
  Group,
  Loader,
  Paper,
  RangeSlider,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  createBioimageSource,
  createBioimageZarrStore,
  fetchAdvancedVizData,
  fetchBioimageStores,
  InteractiveFilter,
  BioimageStoreInfo,
  StoredMetadata,
} from '../../api';
import { isFilterActive } from '../../activeFilters';
import { mantineCategoricalPalette, resolveCategoricalPalette, stableColorMap } from '../../colors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersExcludingOwn,
} from '../../selection';
import { useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import { useVizConfigWriter } from './usePersistedVizControl';
import {
  formatLength,
  hexToRgb,
  normaliseHex,
  type ChannelState,
  type ConfigChannel,
  type Rgb,
} from './bioimage/channels';
import { pointsInPolygon, scaleBarLength, type Polygon } from './bioimage/geometry';
import {
  buildLabelLut,
  cellColouring,
  pairLabelsStore,
  rampColor,
  rampGradient,
  type LabelStyle,
} from './bioimage/labels';
// Types only: the adapter module pulls deck.gl + viv and is imported lazily.
import type {
  BioimageInfo,
  BioimageViewer,
  OverlayPoint,
  SelectionMode,
} from './bioimage/viewer';

interface BioimageViewerConfig {
  image_wf_id?: string | null;
  image_dc_id?: string | null;
  store?: string | null;
  sample_dc_id?: string | null;
  sample_column?: string | null;
  channels?: ConfigChannel[];
  show_scalebar?: boolean;
  points_wf_id?: string | null;
  points_dc_id?: string | null;
  cell_id_col?: string | null;
  x_col?: string | null;
  y_col?: string | null;
  color_col?: string | null;
  points_scale?: number;
  points_offset_x?: number;
  points_offset_y?: number;
  point_radius?: number;
  points_sample_col?: string | null;
  selection_enabled?: boolean;
  labels_wf_id?: string | null;
  labels_dc_id?: string | null;
  labels_opacity?: number;
  labels_outline?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: BioimageViewerConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Emits the ROI selection as a `scatter_selection` on the points DC. Absent
   *  in read-only hosts, which hides the ROI tools. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/** Categories listed in the overlay legend before it stops. */
const LEGEND_MAX = 10;

/**
 * The value an upstream filter selects on the sample column, or null.
 *
 * The first value of the first active filter on that column wins: the viewer
 * shows one image at a time, so a multi-select narrows to its first pick. When
 * the component names the sample DC, a filter that says it came from another
 * DC is ignored.
 */
function sampleFromFilters(
  filters: InteractiveFilter[],
  column: string | null | undefined,
  dcId: string | null | undefined,
): string | null {
  if (!column) return null;
  for (const f of filters) {
    if (!isFilterActive(f)) continue;
    if ((f.column_name ?? f.metadata?.column_name) !== column) continue;
    if (dcId && f.metadata?.dc_id && f.metadata.dc_id !== dcId) continue;
    const v = Array.isArray(f.value) ? f.value.find((x) => x != null) : f.value;
    if (v != null && v !== '') return String(v);
  }
  return null;
}

function toConfigChannels(channels: readonly ChannelState[]): ConfigChannel[] {
  return channels.map((c) => ({
    index: c.index,
    name: c.name,
    visible: c.visible,
    color: c.color,
    contrast_limits: c.contrastLimits,
  }));
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Why an image failed to open, for the tile. A 403 on a remote store is the
 *  server's allow-list refusing the host or bucket, which the reader cannot fix
 *  from here, so it says so instead of echoing a status code. */
function imageErrorText(err: unknown, store: string, remote: boolean): string {
  const status = (err as { status?: unknown } | null)?.status;
  if (remote && status === 403) {
    return `Could not open ${store}: remote host not allowed on this server`;
  }
  return `Could not open ${store}: ${errorText(err)}`;
}

/** Whether two store listings name the same stores, so a refresh that found
 *  nothing new keeps the previous list (and its object identities). */
function sameStores(a: BioimageStoreInfo[] | null, b: BioimageStoreInfo[]): boolean {
  return a !== null && JSON.stringify(a) === JSON.stringify(b);
}

/** Value of `data-bioimage-ready`, read by the screenshot capture: "false"
 *  while the image loads, "true" once drawn, "error" when the store or image
 *  failed, "skipped" when nothing will ever draw (no WebGL slot, no store). */
type ReadyState = 'false' | 'true' | 'error' | 'skipped';

/** Whether a points row's sample value names `store`, by sample or full name. */
function isRowOfStore(sample: unknown, store: BioimageStoreInfo): boolean {
  const value = String(sample ?? '');
  return value === store.sample || value === store.name;
}

/** The empty-state text once the store list has loaded, if there is nothing to show. */
function emptyStoreMessage(
  stores: BioimageStoreInfo[],
  activeStore: BioimageStoreInfo | null,
  sampleValue: string | null,
): string | undefined {
  if (stores.length === 0) return 'No image stores in this data collection';
  if (!activeStore && sampleValue != null) return `No image for sample "${sampleValue}"`;
  return undefined;
}

interface PlaneSliderProps {
  label: string;
  value: number;
  size: number;
  onChange: (value: number) => void;
}

/** A 1-based slider over the planes of one non-spatial axis (z or t). */
function PlaneSlider({ label, value, size, onChange }: PlaneSliderProps): React.ReactElement {
  return (
    <div>
      <Text size="xs" fw={500} mb={4}>
        {label}: {value + 1} / {size}
      </Text>
      <Slider
        size="xs"
        min={0}
        max={size - 1}
        step={1}
        value={value}
        label={(v) => v + 1}
        onChange={onChange}
      />
    </div>
  );
}

interface OverlayButtonProps {
  label: string;
  icon: string;
  /** Set for the ROI mode toggles: filled and `aria-pressed` while active. */
  active?: boolean;
  onClick: () => void;
}

function OverlayButton({ label, icon, active, onClick }: OverlayButtonProps): React.ReactElement {
  return (
    <Tooltip label={label} withArrow openDelay={300}>
      <ActionIcon
        size="sm"
        variant={active ? 'filled' : 'default'}
        aria-label={label}
        aria-pressed={active}
        onClick={onClick}
      >
        <Icon icon={icon} width={14} />
      </ActionIcon>
    </Tooltip>
  );
}

/**
 * Pyramidal image viewer (viz_kind "bioimage_viewer") for OME-Zarr (NGFF 0.4/0.5),
 * SpatialData images (served as OME-Zarr) and OME-TIFF: viv's multiscale
 * image layer on deck.gl, behind the adapter in ./bioimage/viewer.ts.
 *
 * Which store is shown: the one whose sample an upstream filter on
 * `sample_column` selects, else the reader's pick, else `store`, else the
 * first. An optional points overlay (a cell table with image coordinates)
 * draws on top, faded where the dashboard filters exclude a cell, and a lasso
 * or rectangle over it emits the enclosed cell ids as a `scatter_selection`
 * on the points DC, so it cross-filters and can become an analysis group.
 *
 * An optional labels DC (segmentation masks, one store per sample) draws the
 * mask of the shown sample over the image: each cell filled and outlined in
 * its points colour (label value = `cell_id_col`), faded where the filters
 * exclude it, ringed in the accent when selected; a click on a cell selects
 * it. Its centroids then stay undrawn, but the lasso still selects on them.
 *
 * WebGL budget: one slot via useWebglSlot. A tile denied one renders a
 * placeholder and never creates a deck context.
 */
const BioimageViewerRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as BioimageViewerConfig;
  const writeConfig = useVizConfigWriter(metadata);
  const glGranted = useWebglSlot(true);

  const imageDcId = config.image_dc_id ?? null;
  const pointsDcId = config.points_dc_id ?? null;
  const pointsWfId = config.points_wf_id ?? null;
  const cellIdCol = config.cell_id_col ?? null;
  const xCol = config.x_col ?? null;
  const yCol = config.y_col ?? null;
  const colorCol = config.color_col ?? null;
  const sampleCol = config.points_sample_col ?? null;
  const pointsEnabled = Boolean(pointsWfId && pointsDcId && xCol && yCol);

  // The viewer's own ROI selection is stripped before anything reads the
  // filters: it keeps drawing every cell and rings the selected ones instead.
  const fetchFilters = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );
  const fetchFiltersKey = JSON.stringify(fetchFilters);
  const activeFetchFilters = useMemo(
    () => fetchFilters.filter(isFilterActive),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fetchFiltersKey],
  );

  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const ownSelection = useMemo<string[]>(() => {
    const own = filters.find((f) => f.index === metadata.index && f.source === 'scatter_selection');
    return Array.isArray(own?.value) ? own.value.map((v) => String(v)) : [];
  }, [filters, metadata.index]);

  // ---- Stores -------------------------------------------------------------
  const [stores, setStores] = useState<BioimageStoreInfo[] | null>(null);
  const [storesLoading, setStoresLoading] = useState(true);
  const [storesError, setStoresError] = useState<string | null>(null);
  // The DC whose store list is on screen. Only the first fetch for a DC shows
  // the loading state: a refresh swaps the frame's children for a skeleton
  // otherwise, which unmounts the host and so the viewer with the reader's view.
  const storesDcRef = useRef<string | null>(null);

  useEffect(() => {
    if (!imageDcId) {
      storesDcRef.current = null;
      setStores(null);
      setStoresError('Bioimage viewer: missing image DC binding');
      setStoresLoading(false);
      return;
    }
    let cancelled = false;
    if (storesDcRef.current !== imageDcId) {
      setStores(null);
      setStoresLoading(true);
      setStoresError(null);
    }
    fetchBioimageStores(imageDcId)
      .then((list) => {
        if (cancelled) return;
        storesDcRef.current = imageDcId;
        setStores((prev) => (sameStores(prev, list) ? prev : list));
        setStoresError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setStoresError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setStoresLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [imageDcId, refreshTick]);

  const sampleValue = useMemo(
    () => sampleFromFilters(activeFetchFilters, config.sample_column, config.sample_dc_id),
    [activeFetchFilters, config.sample_column, config.sample_dc_id],
  );
  const [pickedStore, setPickedStore] = useState<string | null>(config.store ?? null);
  const activeStore = useMemo<BioimageStoreInfo | null>(() => {
    if (!stores || stores.length === 0) return null;
    if (sampleValue != null) {
      return stores.find((s) => s.sample === sampleValue || s.name === sampleValue) ?? null;
    }
    return stores.find((s) => s.name === pickedStore) ?? stores[0];
  }, [stores, sampleValue, pickedStore]);

  // ---- Labels stores --------------------------------------------------------
  // A labels DC (segmentation masks) holds one store per sample; the one of
  // the shown image's sample is drawn over it.
  const labelsDcId = config.labels_dc_id ?? null;
  const [labelStores, setLabelStores] = useState<BioimageStoreInfo[] | null>(null);
  const [labelStoresError, setLabelStoresError] = useState<string | null>(null);
  useEffect(() => {
    setLabelStoresError(null);
    if (!labelsDcId) {
      setLabelStores(null);
      return;
    }
    let cancelled = false;
    fetchBioimageStores(labelsDcId)
      .then((list) => {
        if (!cancelled) setLabelStores((prev) => (sameStores(prev, list) ? prev : list));
      })
      .catch((err: unknown) => {
        if (!cancelled) setLabelStoresError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
  }, [labelsDcId, refreshTick]);
  const pairedLabels = useMemo(
    () => pairLabelsStore(labelStores, activeStore, stores?.length ?? 0),
    [labelStores, activeStore, stores],
  );
  const pairedLabelsName = pairedLabels?.name ?? null;

  // ---- Viewer lifecycle ---------------------------------------------------
  // The host is tracked as state (callback ref), so the viewer is created when
  // the node mounts and torn down when it unmounts, e.g. behind an error.
  const [hostEl, setHostEl] = useState<HTMLDivElement | null>(null);
  const [viewer, setViewer] = useState<BioimageViewer | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  const [drawn, setDrawn] = useState(false);
  const [zoom, setZoom] = useState(0);
  const roiRef = useRef<(polygon: Polygon) => void>(() => {});
  const labelClickRef = useRef<(label: number) => void>(() => {});
  const [labelsDrawn, setLabelsDrawn] = useState(false);
  const [labelsError, setLabelsError] = useState<string | null>(null);

  useEffect(() => {
    if (!glGranted || !hostEl) return;
    let disposed = false;
    let created: BioimageViewer | null = null;
    import('./bioimage/viewer')
      .then(({ createBioimageViewer }) =>
        createBioimageViewer(hostEl, {
          onViewportLoad: () => {
            setDrawn(true);
            setImageLoading(false);
          },
          onLabelsLoad: () => setLabelsDrawn(true),
          onLabelClick: (label) => labelClickRef.current(label),
          onZoomChange: (z) => setZoom(Math.round(z * 100) / 100),
          onRoi: (polygon) => roiRef.current(polygon),
          onError: (err) => console.warn('[bioimage_viewer]', err),
        }),
      )
      .then((v) => {
        if (disposed) {
          v.dispose();
          return;
        }
        created = v;
        setViewer(v);
      })
      .catch((err: unknown) => {
        if (!disposed) setImageError(errorText(err));
      });
    return () => {
      disposed = true;
      setViewer(null);
      setDrawn(false);
      setLabelsDrawn(false);
      created?.dispose();
    };
  }, [glGranted, hostEl]);

  // ---- Image load ---------------------------------------------------------
  const [info, setInfo] = useState<BioimageInfo | null>(null);
  const [channels, setChannels] = useState<ChannelState[]>([]);
  const [plane, setPlane] = useState<{ z: number; t: number }>({ z: 0, t: 0 });
  // Read at load time only: the reader's own channel edits write back to the
  // config, and must not reload the image they were made on.
  const configChannelsRef = useRef<ConfigChannel[]>(config.channels ?? []);
  configChannelsRef.current = config.channels ?? [];

  // The image last loaded into which viewer. Loading it again into the same
  // viewer is a refresh: the image reloads in place, and the reader's view,
  // channel edits and plane carry over.
  const loadedRef = useRef<{ viewer: BioimageViewer; key: string } | null>(null);
  const activeStoreName = activeStore?.name ?? null;
  const activeStoreFormat = activeStore?.format ?? 'ome-zarr';
  const activeStoreRemote = Boolean(activeStore?.remote);

  useEffect(() => {
    if (!viewer || !activeStoreName || !imageDcId) return;
    let cancelled = false;
    const key = `${imageDcId}\u0000${activeStoreName}`;
    const refresh = loadedRef.current?.viewer === viewer && loadedRef.current.key === key;
    loadedRef.current = { viewer, key };
    setImageError(null);
    setDrawn(false);
    if (!refresh) {
      setImageLoading(true);
      setInfo(null);
    }
    viewer
      .load(
        createBioimageSource(imageDcId, { name: activeStoreName, format: activeStoreFormat }),
        configChannelsRef.current,
        { keepView: refresh },
      )
      .then((loaded) => {
        if (cancelled) return;
        setInfo(loaded);
        if (refresh) {
          // Keep the reader's channel state, including an unsaved edit.
          setChannels((prev) => (prev.length === loaded.channels.length ? prev : loaded.channels));
          setPlane((p) =>
            p.z < loaded.sizes.z && p.t < loaded.sizes.t
              ? p
              : { z: loaded.defaultZ, t: loaded.defaultT },
          );
        } else {
          setChannels(loaded.channels);
          setPlane({ z: loaded.defaultZ, t: loaded.defaultT });
        }
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof Error && err.name === 'LoadSupersededError')) return;
        setImageError(imageErrorText(err, activeStoreName, activeStoreRemote));
        setImageLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [viewer, activeStoreName, activeStoreFormat, activeStoreRemote, imageDcId, refreshTick]);

  // An image error replaces the host (and so the viewer) with the message.
  // Another store, or a refresh, deserves a fresh attempt: clearing the error
  // remounts the host, which recreates the viewer, which loads the new store.
  useEffect(() => {
    setImageError(null);
  }, [activeStoreName, refreshTick]);

  useEffect(() => {
    if (viewer && info) viewer.setChannels(channels);
  }, [viewer, info, channels]);

  useEffect(() => {
    if (viewer && info) viewer.setSelection(plane);
  }, [viewer, info, plane]);

  useEffect(() => {
    if (!hostEl || !viewer) return;
    const ro = new ResizeObserver(() => viewer.resize());
    ro.observe(hostEl);
    return () => ro.disconnect();
  }, [hostEl, viewer]);

  // ---- Theme --------------------------------------------------------------
  const primaryShade = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6];
  const accent: Rgb | undefined = hexToRgb(primaryShade) ?? undefined;
  const accentKey = accent?.join(',') ?? '';
  useEffect(() => {
    viewer?.setDark(isDark, accent);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, isDark, accentKey]);

  // ---- Points overlay -----------------------------------------------------
  const pointCols = useMemo(
    () =>
      Array.from(
        new Set([cellIdCol, xCol, yCol, colorCol, sampleCol].filter((c): c is string => !!c)),
      ),
    [cellIdCol, xCol, yCol, colorCol, sampleCol],
  );
  const pointColsKey = pointCols.join('|');
  const [pointRows, setPointRows] = useState<Record<string, unknown[]> | null>(null);
  const [pointsEstimated, setPointsEstimated] = useState(false);
  const [pointsError, setPointsError] = useState<string | null>(null);

  // The whole table, unfiltered: excluded cells stay on the image, faded.
  useEffect(() => {
    if (!pointsEnabled || !pointsWfId || !pointsDcId) {
      setPointRows(null);
      return;
    }
    let cancelled = false;
    setPointsError(null);
    fetchAdvancedVizData({
      wfId: pointsWfId,
      dcId: pointsDcId,
      columns: pointCols,
      filters: [],
      vizKind: 'bioimage_viewer',
    })
      .then((res) => {
        if (cancelled) return;
        setPointRows(res.rows);
        setPointsEstimated(Boolean(res.sampled));
      })
      .catch((err: unknown) => {
        if (!cancelled) setPointsError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointsEnabled, pointsWfId, pointsDcId, pointColsKey, refreshTick]);

  // The cells the dashboard filters keep, by id. Null means nothing filters.
  const [keptIds, setKeptIds] = useState<Set<string> | null>(null);
  useEffect(() => {
    if (!pointsEnabled || !pointsWfId || !pointsDcId || !cellIdCol || !activeFetchFilters.length) {
      setKeptIds(null);
      return;
    }
    let cancelled = false;
    fetchAdvancedVizData({
      wfId: pointsWfId,
      dcId: pointsDcId,
      columns: [cellIdCol],
      filters: activeFetchFilters,
      vizKind: 'bioimage_viewer',
    })
      .then((res) => {
        if (cancelled) return;
        setKeptIds(new Set((res.rows[cellIdCol] ?? []).map((v) => String(v))));
      })
      .catch(() => {
        // Best effort: without the filtered set every cell draws unfaded.
        if (!cancelled) setKeptIds(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pointsEnabled, pointsWfId, pointsDcId, cellIdCol, activeFetchFilters, refreshTick]);

  const palette = useMemo(
    () => resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark)),
    [theme, isDark],
  );
  // A numeric measurement gets a colour ramp over its range, anything else
  // one palette swatch per value.
  const colouring = useMemo(
    () => (colorCol && pointRows ? cellColouring(pointRows[colorCol] ?? []) : null),
    [colorCol, pointRows],
  );
  const continuous = colouring?.kind === 'continuous' ? colouring : null;
  const colorScale = useMemo(() => {
    if (!colorCol || !pointRows || continuous) return null;
    const values = (pointRows[colorCol] ?? []).map((v) => (v == null ? '' : String(v)));
    return stableColorMap(values, palette);
  }, [colorCol, pointRows, palette, continuous]);

  const overlay = useMemo<OverlayPoint[]>(() => {
    if (!pointRows || !xCol || !yCol || !activeStore) return [];
    const xs = pointRows[xCol] ?? [];
    const ys = pointRows[yCol] ?? [];
    const ids = cellIdCol ? (pointRows[cellIdCol] ?? []) : null;
    const cats = colorCol ? (pointRows[colorCol] ?? []) : null;
    const samples = sampleCol ? (pointRows[sampleCol] ?? []) : null;
    const scale = config.points_scale ?? 1;
    const ox = config.points_offset_x ?? 0;
    const oy = config.points_offset_y ?? 0;
    const base: Rgb = accent ?? hexToRgb(palette[0]) ?? [128, 128, 128];
    const out: OverlayPoint[] = [];
    for (let i = 0; i < xs.length; i += 1) {
      if (samples && !isRowOfStore(samples[i], activeStore)) continue;
      const x = Number(xs[i]) * scale + ox;
      const y = Number(ys[i]) * scale + oy;
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const id = ids ? String(ids[i] ?? '') : String(i);
      const cat = cats ? String(cats[i] ?? '') : null;
      const color = continuous
        ? (rampColor(continuous, cats?.[i]) ?? base)
        : cat != null && colorScale
          ? (hexToRgb(colorScale.get(cat)) ?? base)
          : base;
      out.push({ id, x, y, color, faded: keptIds ? !keptIds.has(id) : false });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    pointRows,
    xCol,
    yCol,
    cellIdCol,
    colorCol,
    sampleCol,
    activeStore,
    config.points_scale,
    config.points_offset_x,
    config.points_offset_y,
    colorScale,
    continuous,
    keptIds,
    accentKey,
    palette,
  ]);

  // ---- Labels overlay -----------------------------------------------------
  const [labelsVisible, setLabelsVisible] = useState(true);
  const [labelsOutline, setLabelsOutline] = useState(config.labels_outline ?? true);
  const [labelsOpacity, setLabelsOpacity] = useState(config.labels_opacity ?? 0.5);
  useEffect(() => setLabelsOutline(config.labels_outline ?? true), [config.labels_outline]);
  useEffect(() => setLabelsOpacity(config.labels_opacity ?? 0.5), [config.labels_opacity]);
  const [labelsSize, setLabelsSize] = useState<{ width: number; height: number } | null>(null);

  // Open the paired store once the image is up; drop it when unpaired. Hiding
  // the labels keeps the store open (the layer just stops drawing).
  const labelsWanted = Boolean(labelsDcId && pairedLabelsName);
  useEffect(() => {
    if (!viewer || !info) return;
    let cancelled = false;
    setLabelsDrawn(false);
    setLabelsError(null);
    setLabelsSize(null);
    const store =
      labelsWanted && labelsDcId && pairedLabelsName
        ? createBioimageZarrStore(labelsDcId, pairedLabelsName)
        : null;
    viewer
      .setLabels(store)
      .then((opened) => {
        if (!cancelled && opened) setLabelsSize({ width: opened.width, height: opened.height });
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof Error && err.name === 'LoadSupersededError')) return;
        setLabelsError(`Could not open the labels of ${pairedLabelsName}: ${errorText(err)}`);
      });
    return () => {
      cancelled = true;
    };
    // `info` is a new object on every load, including a refresh of the same image.
  }, [viewer, info, labelsWanted, labelsDcId, pairedLabelsName, refreshTick]);

  const labelsShown = labelsVisible && labelsWanted && labelsSize !== null && !labelsError;
  // Masks share the image's pixel grid; another size would draw misaligned.
  const labelsMisaligned =
    labelsSize !== null &&
    info !== null &&
    (labelsSize.width !== info.width || labelsSize.height !== info.height);
  // Cells join the table on `cell_id_col` (label value = cell id). Labels the
  // table does not list draw in the accent, faded once a table is joined.
  const joinable = Boolean(pointsEnabled && cellIdCol && pointRows);
  const ownSelectionSet = useMemo(() => new Set(ownSelection), [ownSelection]);
  const labelLut = useMemo(() => {
    const neutral: Rgb = accent ?? hexToRgb(palette[0]) ?? [128, 128, 128];
    const unknown: LabelStyle = { color: neutral, faded: joinable, selected: false };
    return buildLabelLut(joinable ? overlay : [], ownSelectionSet, unknown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay, ownSelectionSet, joinable, accentKey, palette]);
  useEffect(() => {
    if (!viewer) return;
    viewer.setLabelsStyle({
      lut: labelLut,
      opacity: labelsOpacity,
      outline: labelsOutline,
      accent: accent ?? [128, 128, 128],
      visible: labelsVisible,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, labelLut, labelsOpacity, labelsOutline, labelsVisible, accentKey]);

  // The masks show the cells, so their centroids stay undrawn (a lasso still
  // selects on them).
  const pointRadius = config.point_radius ?? 6;
  useEffect(() => {
    if (viewer && info) viewer.setPoints(labelsShown ? [] : overlay, pointRadius);
  }, [viewer, info, overlay, pointRadius, labelsShown]);

  const ownSelectionKey = ownSelection.join('\u0000');
  useEffect(() => {
    if (viewer) viewer.setHighlighted(new Set(ownSelection));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, ownSelectionKey]);

  const legend = useMemo(() => {
    if (continuous) return null;
    if (!colorScale || !colorCol || overlay.length === 0 || !pointRows) return null;
    const present = new Set<string>();
    const cats = pointRows[colorCol] ?? [];
    const samples = sampleCol ? (pointRows[sampleCol] ?? []) : null;
    for (let i = 0; i < cats.length; i += 1) {
      if (samples && activeStore && !isRowOfStore(samples[i], activeStore)) continue;
      present.add(String(cats[i] ?? ''));
    }
    const entries = colorScale.universe.filter((v) => present.has(v));
    return { entries: entries.slice(0, LEGEND_MAX), more: Math.max(0, entries.length - LEGEND_MAX) };
  }, [colorScale, colorCol, overlay.length, pointRows, sampleCol, activeStore, continuous]);

  // ---- ROI selection ------------------------------------------------------
  const roiEnabled = Boolean(selectionColumn && pointsDcId && overlay.length > 0);
  const [mode, setMode] = useState<SelectionMode>('pan');
  useEffect(() => {
    if (!roiEnabled && mode !== 'pan') setMode('pan');
  }, [roiEnabled, mode]);
  useEffect(() => {
    viewer?.setSelectionMode(mode);
  }, [viewer, mode]);

  const emitSelection = (ids: string[]) => {
    if (!onFilterChange || !selectionColumn || !pointsDcId) return;
    // The selection lives on the points table, not on the image DC this
    // component is bound to, so the cross-DC links resolve from the cells.
    onFilterChange(
      advancedVizSelectionFilter({ ...metadata, dc_id: pointsDcId }, selectionColumn, ids),
    );
  };
  // A click on a cell selects it (a second click on the only selected cell
  // clears); background and cells missing from the table do nothing.
  labelClickRef.current = (label: number) => {
    if (!roiEnabled || !labelsShown || label === 0) return;
    const id = labelLut.ids.get(label);
    if (id === undefined || labelLut.styles.get(label)?.faded) return;
    const only = ownSelection.length === 1 && ownSelection[0] === id;
    emitSelection(only ? [] : [id]);
  };
  // Faded cells are ones the dashboard already excludes; a lasso catches the
  // cells it is showing, as the scatter lassos do.
  roiRef.current = (polygon: Polygon) => {
    if (!roiEnabled) return;
    const caught = pointsInPolygon(
      overlay.filter((p) => !p.faded),
      polygon,
    );
    emitSelection(Array.from(new Set(caught.map((p) => p.id))));
  };

  // ---- Controls -----------------------------------------------------------
  const updateChannel = (index: number, patch: Partial<ChannelState>, persist: boolean) => {
    const next = channels.map((c) => (c.index === index ? { ...c, ...patch } : c));
    setChannels(next);
    if (persist) writeConfig({ channels: toConfigChannels(next) });
  };
  const integerDtype = info ? !/^Float/.test(info.dtype) : true;

  // Memoised so a zoom (which re-renders for the scale bar) does not hand the
  // frame a new controls node and re-publish the Settings popover.
  const controls = useMemo(() => (
    <Stack gap="xs">
      {stores && stores.length > 1 ? (
        <Select
          size="xs"
          label="Image"
          data={stores.map((s) => ({ value: s.name, label: s.sample }))}
          value={activeStore?.name ?? null}
          disabled={sampleValue != null}
          description={
            sampleValue != null ? `Follows the ${config.sample_column} filter` : undefined
          }
          onChange={(v) => {
            if (!v) return;
            setPickedStore(v);
            writeConfig({ store: v });
          }}
          allowDeselect={false}
        />
      ) : null}
      {info && info.sizes.z > 1 ? (
        <PlaneSlider
          label="Z plane"
          value={plane.z}
          size={info.sizes.z}
          onChange={(v) => setPlane((p) => ({ ...p, z: v }))}
        />
      ) : null}
      {info && info.sizes.t > 1 ? (
        <PlaneSlider
          label="Time point"
          value={plane.t}
          size={info.sizes.t}
          onChange={(v) => setPlane((p) => ({ ...p, t: v }))}
        />
      ) : null}
      {channels.length ? (
        <div>
          <Text size="xs" fw={500} mb={4}>
            Channels
          </Text>
          <Stack gap="sm">
            {channels.map((c) => {
              const [lo, hi] = c.domain;
              const step = integerDtype ? 1 : Math.max((hi - lo) / 500, Number.EPSILON);
              return (
                <Stack key={c.index} gap={4}>
                  <Group gap="xs" wrap="nowrap" justify="space-between">
                    <Checkbox
                      size="xs"
                      label={c.name}
                      checked={c.visible}
                      onChange={(e) =>
                        updateChannel(c.index, { visible: e.currentTarget.checked }, true)
                      }
                    />
                    <ColorInput
                      size="xs"
                      w={110}
                      format="hex"
                      value={c.color}
                      onChange={(v) => {
                        const hex = normaliseHex(v);
                        if (hex) updateChannel(c.index, { color: hex }, false);
                      }}
                      onChangeEnd={(v) => {
                        const hex = normaliseHex(v);
                        if (hex) updateChannel(c.index, { color: hex }, true);
                      }}
                    />
                  </Group>
                  <RangeSlider
                    size="xs"
                    min={lo}
                    max={hi}
                    step={step}
                    minRange={0}
                    value={c.contrastLimits}
                    disabled={!c.visible}
                    onChange={(v) => updateChannel(c.index, { contrastLimits: v }, false)}
                    onChangeEnd={(v) => updateChannel(c.index, { contrastLimits: v }, true)}
                  />
                </Stack>
              );
            })}
          </Stack>
        </div>
      ) : null}
      {labelsDcId ? (
        <div>
          <Text size="xs" fw={500} mb={4}>
            Cell masks
          </Text>
          <Stack gap={6}>
            <Switch
              size="xs"
              label="Show masks"
              checked={labelsVisible}
              disabled={!labelsWanted}
              onChange={(e) => setLabelsVisible(e.currentTarget.checked)}
            />
            <Switch
              size="xs"
              label="Outlines"
              checked={labelsOutline}
              disabled={!labelsWanted || !labelsVisible}
              onChange={(e) => {
                const next = e.currentTarget.checked;
                setLabelsOutline(next);
                writeConfig({ labels_outline: next });
              }}
            />
            <div>
              <Text size="xs" mb={2}>
                Fill opacity
              </Text>
              <Slider
                size="xs"
                min={0}
                max={1}
                step={0.05}
                value={labelsOpacity}
                disabled={!labelsWanted || !labelsVisible}
                label={(v) => `${Math.round(v * 100)}%`}
                onChange={setLabelsOpacity}
                onChangeEnd={(v) => writeConfig({ labels_opacity: v })}
              />
            </div>
            {labelStores && !labelsWanted && activeStore ? (
              <Text size="xs" c="dimmed">
                No mask for sample "{activeStore.sample}"
              </Text>
            ) : null}
            {labelsMisaligned && labelsSize && info ? (
              <Text size="xs" c="orange">
                Mask is {labelsSize.width} x {labelsSize.height} px, the image {info.width} x{' '}
                {info.height} px: they should share one pixel grid.
              </Text>
            ) : null}
            {labelStoresError || labelsError ? (
              <Text size="xs" c="red">
                {labelStoresError ? `Labels: ${labelStoresError}` : labelsError}
              </Text>
            ) : null}
          </Stack>
        </div>
      ) : null}
      {pointsError ? (
        <Text size="xs" c="red">
          Points overlay: {pointsError}
        </Text>
      ) : null}
    </Stack>
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ), [stores, activeStore, sampleValue, config.sample_column, info, plane, channels, integerDtype, pointsError, labelsDcId, labelStores, labelsWanted, labelsVisible, labelsOutline, labelsOpacity, labelsSize, labelsMisaligned, labelStoresError, labelsError]);

  // ---- Overlay chrome -----------------------------------------------------
  const physical = config.show_scalebar === false ? null : (info?.physicalSize ?? null);
  const bar = physical ? scaleBarLength(physical.value, zoom, 120) : null;

  const toolButton = (value: SelectionMode, label: string, icon: string) => (
    <OverlayButton
      label={label}
      icon={icon}
      active={mode === value}
      onClick={() => setMode(value)}
    />
  );
  const hasSelection = roiEnabled && ownSelection.length > 0;

  const noStoreMessage =
    !storesLoading && !storesError && stores
      ? emptyStoreMessage(stores, activeStore, sampleValue)
      : undefined;

  const frameError = storesError ?? imageError;
  // A bound labels DC holds the thumbnail until its tiles are drawn too, unless
  // it has no mask for this sample or failed (the image alone is then final).
  const labelsPending =
    Boolean(labelsDcId) &&
    labelsVisible &&
    !labelStoresError &&
    !labelsError &&
    (labelStores === null || (labelsWanted && !labelsDrawn));
  const ready: ReadyState = frameError
    ? 'error'
    : !glGranted || noStoreMessage
      ? 'skipped'
      : drawn && !labelsPending
        ? 'true'
        : 'false';

  // The screenshot capture waits on `data-bioimage-ready`. It sits on a
  // wrapper rather than the host because the frame swaps its children for a
  // skeleton, an alert or an empty state, and every branch must report.
  // `display: contents` keeps the wrapper out of the tile's layout.
  return (
    <div data-bioimage-ready={ready} style={{ display: 'contents' }}>
      <AdvancedVizFrame
        title={metadata.title || 'Bioimage'}
        subtitle={(metadata as any).description || (metadata as any).subtitle}
        controls={controls}
        loading={storesLoading}
        error={frameError}
        emptyMessage={noStoreMessage}
        dataRows={pointRows ?? undefined}
        dataColumns={pointRows ? pointCols : undefined}
        estimated={pointsEstimated}
      >
        {glGranted ? (
          <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 240 }}>
            <div
              ref={setHostEl}
              style={{
                position: 'absolute',
                inset: 0,
                overflow: 'hidden',
                borderRadius: 'var(--mantine-radius-sm)',
                touchAction: 'none',
              }}
            />
            <Group gap={4} style={{ position: 'absolute', top: 6, left: 6 }} wrap="nowrap">
              <ActionIcon.Group>
                {roiEnabled ? (
                  <>
                    {toolButton('pan', 'Pan and zoom', 'mdi:hand-back-right-outline')}
                    {toolButton('lasso', 'Lasso select cells', 'mdi:lasso')}
                    {toolButton('rect', 'Rectangle select cells', 'mdi:selection-drag')}
                  </>
                ) : null}
                <OverlayButton
                  label="Reset view"
                  icon="mdi:fit-to-screen"
                  onClick={() => viewer?.resetView()}
                />
                {hasSelection ? (
                  <OverlayButton
                    label="Clear selection"
                    icon="mdi:selection-off"
                    onClick={() => emitSelection([])}
                  />
                ) : null}
              </ActionIcon.Group>
              {hasSelection ? (
                <Badge size="xs" variant="filled">
                  {ownSelection.length.toLocaleString()} selected
                </Badge>
              ) : null}
            </Group>
            {stores && stores.length > 1 && activeStore ? (
              <Badge
                size="xs"
                variant="default"
                style={{ position: 'absolute', top: 8, right: 8 }}
              >
                {activeStore.sample}
              </Badge>
            ) : null}
            {legend && legend.entries.length ? (
              <Paper
                p={6}
                radius="sm"
                shadow="xs"
                style={{ position: 'absolute', bottom: 8, left: 8, maxWidth: '45%', opacity: 0.92 }}
              >
                <Stack gap={2}>
                  {legend.entries.map((v) => (
                    <Group key={v} gap={6} wrap="nowrap">
                      <ColorSwatch color={colorScale!.get(v)} size={10} withShadow={false} />
                      <Text size="xs" lineClamp={1}>
                        {v || '(empty)'}
                      </Text>
                    </Group>
                  ))}
                  {legend.more ? (
                    <Text size="xs" c="dimmed">
                      +{legend.more} more
                    </Text>
                  ) : null}
                </Stack>
              </Paper>
            ) : null}
            {continuous && colorCol && overlay.length ? (
              <Paper
                p={6}
                radius="sm"
                shadow="xs"
                style={{ position: 'absolute', bottom: 8, left: 8, maxWidth: '45%', opacity: 0.92 }}
              >
                <Stack gap={2}>
                  <Text size="xs" lineClamp={1}>
                    {colorCol}
                  </Text>
                  <div
                    style={{
                      width: 120,
                      height: 8,
                      borderRadius: 'var(--mantine-radius-xs)',
                      background: rampGradient(continuous.scale),
                    }}
                  />
                  <Group justify="space-between" gap={8} wrap="nowrap">
                    <Text size="xs" c="dimmed">
                      {continuous.min.toLocaleString(undefined, { maximumSignificantDigits: 3 })}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {continuous.max.toLocaleString(undefined, { maximumSignificantDigits: 3 })}
                    </Text>
                  </Group>
                </Stack>
              </Paper>
            ) : null}
            {bar && physical ? (
              <Paper
                px={6}
                py={4}
                radius="sm"
                shadow="xs"
                style={{ position: 'absolute', bottom: 8, right: 8, opacity: 0.92 }}
              >
                <Stack gap={2} align="center">
                  <Text size="xs" lh={1}>
                    {formatLength(bar.value, physical.unit)}
                  </Text>
                  <div
                    style={{
                      width: bar.screenPx,
                      height: 3,
                      background: 'var(--mantine-color-text)',
                    }}
                  />
                </Stack>
              </Paper>
            ) : null}
            {imageLoading ? (
              <Center style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                <Loader size="sm" />
              </Center>
            ) : null}
          </div>
        ) : (
          <Center h="100%" mih={240}>
            <Stack gap={4} align="center">
              <Text size="sm" c="dimmed" fw={500}>
                Image viewer paused
              </Text>
              <Text size="xs" c="dimmed" ta="center">
                The WebGL context budget is exhausted. Close or scroll past another GL-heavy tile to
                activate this viewer.
              </Text>
            </Stack>
          </Center>
        )}
      </AdvancedVizFrame>
    </div>
  );
};

export default BioimageViewerRenderer;

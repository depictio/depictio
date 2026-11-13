import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Center,
  CloseButton,
  Group,
  Loader,
  Paper,
  Slider,
  Stack,
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
  fetchBioimageRemoteValidation,
  fetchBioimageStores,
  InteractiveFilter,
  BioimageNgffValidation,
  BioimageSource,
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
import ColourKey from '../jbrowse/ColourKey';
import { foldByColour, keyTitle, type LegendRamp } from '../jbrowse/trackLegend';
import AdvancedVizFrame from './AdvancedVizFrame';
import PointerModeSwitch, { type PointerMode } from './controls/PointerModeSwitch';
import {
  VizControlGroup,
  VizInlineField,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
  VIZ_SLIDER_CONTROL_PX,
} from './controls/VizControls';
import { usePersistedVizControl, useVizConfigWriter } from './usePersistedVizControl';
import BioimageBadges from './bioimage/BioimageBadges';
import OpenInMenu from './bioimage/OpenInMenu';
import ChannelRow from './bioimage/ChannelRow';
import BioimageHelp from './bioimage/BioimageHelp';
import type { HelpContext } from './bioimage/help';
import {
  formatLength,
  hexToRgb,
  MAX_RENDERED_CHANNELS,
  type ChannelState,
  type ConfigChannel,
  type Rgb,
} from './bioimage/channels';
import { clearImageInfo, publishImageInfo } from './bioimage/imageInfoRegistry';
import { onPlane, pointsInPolygon, scaleBarLength, type Polygon } from './bioimage/geometry';
import {
  buildLabelLut,
  cellColouring,
  pairLabelsStore,
  rampColor,
  rampStops,
  type LabelStyle,
} from './bioimage/labels';
import {
  axesProblem,
  containerImagePath,
  firstLabelPath,
  normaliseWellName,
  openContainer,
  readNgffAttrs,
  subStore,
  wellForValue,
  type NgffContainer,
} from './bioimage/layout';
// Types only: the adapter module pulls deck.gl + viv and is imported lazily.
import type {
  BioimageInfo,
  BioimageViewer,
  CompareMode,
  OverlayPoint,
  SelectionMode,
} from './bioimage/viewer';
import { formatMetric, metricChange, readSteps, type StepColumns } from './bioimage/steps';

interface BioimageViewerConfig {
  image_wf_id?: string | null;
  image_dc_id?: string | null;
  store?: string | null;
  sample_dc_id?: string | null;
  sample_column?: string | null;
  well_column?: string | null;
  channels?: ConfigChannel[];
  show_scalebar?: boolean;
  points_wf_id?: string | null;
  points_dc_id?: string | null;
  cell_id_col?: string | null;
  x_col?: string | null;
  y_col?: string | null;
  z_col?: string | null;
  t_col?: string | null;
  points_all_planes?: boolean;
  color_col?: string | null;
  points_scale?: number;
  points_offset_x?: number;
  points_offset_y?: number;
  point_radius?: number;
  points_sample_col?: string | null;
  points_well_col?: string | null;
  selection_enabled?: boolean;
  selection_column?: string | null;
  labels_wf_id?: string | null;
  labels_dc_id?: string | null;
  labels_opacity?: number;
  labels_outline?: boolean;
  steps_wf_id?: string | null;
  steps_dc_id?: string | null;
  steps_store_col?: string | null;
  steps_label_col?: string | null;
  steps_order_col?: string | null;
  steps_sample_col?: string | null;
  steps_reference_col?: string | null;
  steps_metric_cols?: string[];
  overlay_store?: string | null;
  points_z_tolerance?: number;
  overlay_opacity?: number;
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

/** Milliseconds per time point while the T axis plays. */
const PLAY_STEP_MS = 600;

/** What the pointer does on the image. Pan is always there; the selection
 *  modes need cells to select and a dashboard to filter. */
const POINTER_MODES: ReadonlyArray<Omit<PointerMode<SelectionMode>, 'disabledReason'>> = [
  {
    value: 'pan',
    label: 'Pan',
    icon: 'tabler:hand-grab',
    tooltip: 'Pan: drag moves the image. Ctrl / Cmd + scroll zooms; click a cell to select it.',
  },
  {
    value: 'lasso',
    label: 'Lasso',
    icon: 'tabler:lasso',
    tooltip: 'Lasso: draw around cells to select them and filter the dashboard.',
  },
  {
    value: 'rect',
    label: 'Rectangle',
    icon: 'tabler:marquee-2',
    tooltip: 'Rectangle: drag a box around cells to select them and filter the dashboard.',
  },
];

interface PlaneSliderProps {
  label: string;
  value: number;
  size: number;
  onChange: (value: number) => void;
  /** Set for the T axis: a play button steps through the time points. */
  playing?: boolean;
  onTogglePlay?: () => void;
}

/** A 1-based slider over the planes of one non-spatial axis (Z or T), inline
 *  like every other control; T gets a play button before its track. */
function PlaneSlider({
  label,
  value,
  size,
  onChange,
  playing,
  onTogglePlay,
}: PlaneSliderProps): React.ReactElement {
  if (!onTogglePlay) {
    return (
      <VizSlider
        label={`${label} ${value + 1}/${size}`}
        aria-label={label}
        min={0}
        max={size - 1}
        step={1}
        value={value}
        thumbLabel={(v) => v + 1}
        onChange={onChange}
      />
    );
  }
  return (
    <VizInlineField label={`${label} ${value + 1}/${size}`} controlWidth={VIZ_SLIDER_CONTROL_PX + 28}>
      <Group gap={6} wrap="nowrap">
        <Tooltip label={playing ? 'Pause' : 'Play through time'} withArrow openDelay={300}>
          <ActionIcon
            size="sm"
            variant={playing ? 'filled' : 'default'}
            aria-label={playing ? 'Pause' : 'Play'}
            aria-pressed={playing}
            onClick={onTogglePlay}
          >
            <Icon icon={playing ? 'tabler:player-pause' : 'tabler:player-play'} width={12} />
          </ActionIcon>
        </Tooltip>
        <Slider
          size="xs"
          style={{ flex: 1 }}
          aria-label={label}
          min={0}
          max={size - 1}
          step={1}
          value={value}
          label={(v) => v + 1}
          onChange={onChange}
        />
      </Group>
    </VizInlineField>
  );
}

/** A notice under the image: a part of the tile that could not draw, said
 *  where the reader sees it rather than inside the Settings popover. */
interface Notice {
  key: string;
  tone: 'error' | 'warning' | 'info';
  text: string;
}

const NOTICE_COLOURS: Record<Notice['tone'], string> = {
  error: 'red',
  warning: 'orange',
  info: 'dimmed',
};

const NOTICE_ICONS: Record<Notice['tone'], string> = {
  error: 'tabler:alert-circle',
  warning: 'tabler:alert-triangle',
  info: 'tabler:info-circle',
};

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
  // Keys what the tile publishes for the component's Info tab (see imageInfoRegistry).
  const componentKey = String(metadata.index);
  useEffect(() => () => clearImageInfo(componentKey), [componentKey]);
  const pointsDcId = config.points_dc_id ?? null;
  const pointsWfId = config.points_wf_id ?? null;
  const cellIdCol = config.cell_id_col ?? null;
  // What a cell is selected, faded and highlighted by: a sample:cell key when
  // the cell id is unique only per sample; labels still join on the cell id.
  const keyCol = cellIdCol ? (config.selection_column || cellIdCol) : null;
  const xCol = config.x_col ?? null;
  const yCol = config.y_col ?? null;
  const colorCol = config.color_col ?? null;
  const sampleCol = config.points_sample_col ?? null;
  const wellCol = config.points_well_col ?? null;
  const zCol = config.z_col ?? null;
  const tCol = config.t_col ?? null;
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

  // ---- Processing steps ---------------------------------------------------
  // A steps table (one row per sample and step) picks the store instead of the
  // store picker: its rows, narrowed by the dashboard filters, are the steps.
  const stepsWfId = config.steps_wf_id ?? null;
  const stepsDcId = config.steps_dc_id ?? null;
  const stepCols = useMemo<StepColumns | null>(
    () =>
      config.steps_store_col
        ? {
            store: config.steps_store_col,
            label: config.steps_label_col,
            order: config.steps_order_col,
            sample: config.steps_sample_col,
            reference: config.steps_reference_col,
            metrics: config.steps_metric_cols ?? [],
          }
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      config.steps_store_col,
      config.steps_label_col,
      config.steps_order_col,
      config.steps_sample_col,
      config.steps_reference_col,
      (config.steps_metric_cols ?? []).join('|'),
    ],
  );
  const stepsEnabled = Boolean(stepsWfId && stepsDcId && stepCols);
  const [stepRows, setStepRows] = useState<Record<string, unknown[]> | null>(null);
  const [stepsError, setStepsError] = useState<string | null>(null);
  useEffect(() => {
    if (!stepsEnabled || !stepsWfId || !stepsDcId || !stepCols) {
      setStepRows(null);
      setStepsError(null);
      return;
    }
    let cancelled = false;
    const columns = [
      ...new Set(
        [stepCols.store, stepCols.label, stepCols.order, stepCols.sample, stepCols.reference, ...stepCols.metrics].filter(
          (c): c is string => Boolean(c),
        ),
      ),
    ];
    fetchAdvancedVizData({
      wfId: stepsWfId,
      dcId: stepsDcId,
      columns,
      filters: activeFetchFilters,
      vizKind: 'bioimage_viewer',
    })
      .then((res) => {
        if (cancelled) return;
        setStepRows(res.rows);
        setStepsError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setStepsError(errorText(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepsEnabled, stepsWfId, stepsDcId, stepCols, fetchFiltersKey, refreshTick]);
  const steps = useMemo(
    () => (stepRows && stepCols ? readSteps(stepRows, stepCols) : null),
    [stepRows, stepCols],
  );
  const [pickedStepSample, setPickedStepSample] = useState<string | null>(null);
  const stepSample = steps
    ? pickedStepSample != null && steps.bySample.has(pickedStepSample)
      ? pickedStepSample
      : (steps.samples[0] ?? null)
    : null;
  const sampleSteps = useMemo(
    () => (steps && stepSample != null ? (steps.bySample.get(stepSample) ?? []) : []),
    [steps, stepSample],
  );
  const [pickedStep, setPickedStep] = useState<string | null>(null);
  // The last step by default: the end result is what a reader checks first.
  const pickedStepIndex = sampleSteps.findIndex((st) => st.label === pickedStep);
  const activeStepIndex = pickedStepIndex >= 0 ? pickedStepIndex : sampleSteps.length - 1;
  const activeStep = activeStepIndex >= 0 ? sampleSteps[activeStepIndex] : null;
  const previousStep = activeStepIndex > 0 ? sampleSteps[activeStepIndex - 1] : null;

  const sampleValue = useMemo(
    () => sampleFromFilters(activeFetchFilters, config.sample_column, config.sample_dc_id),
    [activeFetchFilters, config.sample_column, config.sample_dc_id],
  );
  const [pickedStore, setPickedStore] = useState<string | null>(config.store ?? null);
  // The overlay store is drawn over the image, never picked as the image.
  const sampleStores = useMemo(
    () => (stores ?? []).filter((s) => s.name !== config.overlay_store),
    [stores, config.overlay_store],
  );
  const activeStore = useMemo<BioimageStoreInfo | null>(() => {
    if (!stores || stores.length === 0) return null;
    if (stepsEnabled) {
      return activeStep ? (stores.find((s) => s.name === activeStep.store) ?? null) : null;
    }
    if (sampleValue != null) {
      return sampleStores.find((s) => s.sample === sampleValue || s.name === sampleValue) ?? null;
    }
    return sampleStores.find((s) => s.name === pickedStore) ?? sampleStores[0] ?? null;
  }, [stores, sampleStores, sampleValue, pickedStore, stepsEnabled, activeStep]);
  const activeStoreName = activeStore?.name ?? null;
  const activeStoreFormat = activeStore?.format ?? 'ome-zarr';
  const activeStoreRemote = Boolean(activeStore?.remote);
  // Every format but OME-TIFF is read as a zarr key tree.
  const isZarr = activeStoreFormat !== 'ome-tiff';
  const storeKey = imageDcId && activeStoreName ? `${imageDcId}\u0000${activeStoreName}` : null;

  // ---- Container: plate wells, bioformats2raw series ----------------------
  // An OME-Zarr root may hold more than one image: an HCS plate (one image per
  // well field) or a bioformats2raw container (one per series). The image
  // drawn is the first field of the well an upstream filter on `well_column`
  // names, else the reader's pick, else the plate's first well.
  const [container, setContainer] = useState<{ key: string; value: NgffContainer } | null>(null);
  useEffect(() => {
    if (!storeKey || !isZarr || !imageDcId || !activeStoreName) {
      setContainer(null);
      return;
    }
    let cancelled = false;
    const unknown: NgffContainer = { layout: 'unknown', version: null, wells: [] };
    openContainer(createBioimageZarrStore(imageDcId, activeStoreName))
      .then((value) => {
        if (!cancelled) setContainer({ key: storeKey, value });
      })
      .catch(() => {
        // The image reader then says why the store cannot be opened.
        if (!cancelled) setContainer({ key: storeKey, value: unknown });
      });
    return () => {
      cancelled = true;
    };
  }, [storeKey, isZarr, imageDcId, activeStoreName, refreshTick]);
  const containerValue = container && container.key === storeKey ? container.value : null;
  const wells = containerValue?.wells ?? [];
  const wellValue = useMemo(
    () => sampleFromFilters(activeFetchFilters, config.well_column, null),
    [activeFetchFilters, config.well_column],
  );
  const [pickedWell, setPickedWell] = useState<string | null>(null);
  useEffect(() => setPickedWell(null), [storeKey]);
  const activeWell = useMemo(() => {
    if (!wells.length) return null;
    if (wellValue != null) return wellForValue(wells, wellValue);
    return wells.find((w) => w.path === pickedWell) ?? wells[0];
  }, [wells, wellValue, pickedWell]);
  const wellMissing = wellValue != null && wells.length > 0 && activeWell === null;

  // The image group to open inside the store, once the container is known.
  const [target, setTarget] = useState<{ key: string; path: string } | null>(null);
  const [targetError, setTargetError] = useState<string | null>(null);
  useEffect(() => {
    setTargetError(null);
    if (!storeKey || !imageDcId || !activeStoreName || wellMissing) {
      setTarget(null);
      return;
    }
    if (!isZarr) {
      setTarget({ key: storeKey, path: '' });
      return;
    }
    if (!containerValue) return;
    let cancelled = false;
    const wellPath = activeWell?.path ?? null;
    const root = createBioimageZarrStore(imageDcId, activeStoreName);
    containerImagePath(root, containerValue, wellPath)
      .then(async (path) => {
        // Axes outside NGFF's t, c, z, y, x get a sentence, not a reader stack trace.
        const problem = axesProblem(await readNgffAttrs(root, path));
        if (cancelled) return;
        if (problem) {
          setTarget(null);
          setTargetError(`${activeStoreName}: ${problem}`);
        } else setTarget({ key: `${storeKey}\u0000${path}`, path });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setTarget(null);
        setTargetError(`Could not open ${activeStoreName}: ${errorText(err)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [storeKey, isZarr, imageDcId, activeStoreName, containerValue, activeWell, wellMissing]);
  const imagePath = target?.path ?? null;

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

  useEffect(() => {
    if (!viewer || !activeStoreName || !imageDcId || !target) return;
    let cancelled = false;
    const key = target.key;
    const refresh = loadedRef.current?.viewer === viewer && loadedRef.current.key === key;
    loadedRef.current = { viewer, key };
    setImageError(null);
    setDrawn(false);
    if (!refresh) {
      setImageLoading(true);
      setInfo(null);
    }
    const source: BioimageSource = isZarr
      ? { kind: 'zarr', store: subStore(createBioimageZarrStore(imageDcId, activeStoreName), target.path) }
      : createBioimageSource(imageDcId, { name: activeStoreName, format: activeStoreFormat });
    viewer
      .load(source, configChannelsRef.current, { keepView: refresh })
      .then((loaded) => {
        if (cancelled) return;
        setInfo(loaded);
        publishImageInfo(componentKey, {
          store: activeStoreName,
          info: loaded,
          ...(containerValue && containerValue.layout !== 'image'
            ? { layout: containerValue.layout }
            : {}),
          ...(target.path ? { imagePath: target.path } : {}),
        });
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
    // `target` changes identity on every resolve; its key and path say what it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, target?.key, target?.path, activeStoreFormat, activeStoreRemote, imageDcId, refreshTick]);

  // No image to open (a refused store, a missing well): the last image's axes,
  // channels and plane must not outlive it in the badges and the sliders.
  useEffect(() => {
    if (target) return;
    loadedRef.current = null;
    setInfo(null);
    setChannels([]);
  }, [target]);

  // An image error replaces the host (and so the viewer) with the message.
  // Another store, or a refresh, deserves a fresh attempt: clearing the error
  // remounts the host, which recreates the viewer, which loads the new store.
  useEffect(() => {
    setImageError(null);
  }, [activeStoreName, imagePath, refreshTick]);

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
        new Set(
          [cellIdCol, keyCol, xCol, yCol, zCol, tCol, colorCol, sampleCol, wellCol].filter(
            (c): c is string => !!c,
          ),
        ),
      ),
    [cellIdCol, keyCol, xCol, yCol, zCol, tCol, colorCol, sampleCol, wellCol],
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
  const [keptIdsFailed, setKeptIdsFailed] = useState(false);
  useEffect(() => {
    setKeptIdsFailed(false);
    if (!pointsEnabled || !pointsWfId || !pointsDcId || !keyCol || !activeFetchFilters.length) {
      setKeptIds(null);
      return;
    }
    let cancelled = false;
    fetchAdvancedVizData({
      wfId: pointsWfId,
      dcId: pointsDcId,
      columns: [keyCol],
      filters: activeFetchFilters,
      vizKind: 'bioimage_viewer',
    })
      .then((res) => {
        if (cancelled) return;
        setKeptIds(new Set((res.rows[keyCol] ?? []).map((v) => String(v))));
      })
      .catch(() => {
        // Without the filtered set every cell draws unfaded, and the tile says so.
        if (cancelled) return;
        setKeptIds(null);
        setKeptIdsFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [pointsEnabled, pointsWfId, pointsDcId, keyCol, activeFetchFilters, refreshTick]);

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

  const [allPlanes, setAllPlanes] = usePersistedVizControl(metadata, 'points_all_planes', false);
  const stacked = Boolean(
    (zCol && info && info.sizes.z > 1) || (tCol && info && info.sizes.t > 1),
  );
  const overlay = useMemo<OverlayPoint[]>(() => {
    if (!pointRows || !xCol || !yCol || !activeStore) return [];
    const xs = pointRows[xCol] ?? [];
    const ys = pointRows[yCol] ?? [];
    const ids = cellIdCol ? (pointRows[cellIdCol] ?? []) : null;
    const keys = keyCol && keyCol !== cellIdCol ? (pointRows[keyCol] ?? []) : null;
    const cats = colorCol ? (pointRows[colorCol] ?? []) : null;
    const samples = sampleCol ? (pointRows[sampleCol] ?? []) : null;
    // On a plate, a cell belongs to the shown image when its well is the one open.
    const rowWells = wellCol && activeWell ? (pointRows[wellCol] ?? []) : null;
    // In a stack, a cell sits on its plane: only the shown z and t draw.
    const rowZ = zCol && !allPlanes && info && info.sizes.z > 1 ? (pointRows[zCol] ?? []) : null;
    const rowT = tCol && !allPlanes && info && info.sizes.t > 1 ? (pointRows[tCol] ?? []) : null;
    const zTolerance = config.points_z_tolerance ?? 0;
    const scale = config.points_scale ?? 1;
    const ox = config.points_offset_x ?? 0;
    const oy = config.points_offset_y ?? 0;
    const base: Rgb = accent ?? hexToRgb(palette[0]) ?? [128, 128, 128];
    const out: OverlayPoint[] = [];
    for (let i = 0; i < xs.length; i += 1) {
      if (samples && !isRowOfStore(samples[i], activeStore)) continue;
      if (rowWells && activeWell && normaliseWellName(String(rowWells[i] ?? '')) !== activeWell.name) {
        continue;
      }
      if (rowZ && !onPlane(Number(rowZ[i]), plane.z, zTolerance)) continue;
      if (rowT && Math.round(Number(rowT[i])) !== plane.t) continue;
      const x = Number(xs[i]) * scale + ox;
      const y = Number(ys[i]) * scale + oy;
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const cellId = ids ? String(ids[i] ?? '') : String(i);
      const id = keys ? String(keys[i] ?? '') : cellId;
      const cat = cats ? String(cats[i] ?? '') : null;
      let color = base;
      if (continuous) color = rampColor(continuous, cats?.[i]) ?? base;
      else if (cat != null && colorScale) color = hexToRgb(colorScale.get(cat)) ?? base;
      out.push({
        id,
        ...(keys ? { label: cellId } : {}),
        x,
        y,
        color,
        faded: keptIds ? !keptIds.has(id) : false,
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    pointRows,
    xCol,
    yCol,
    cellIdCol,
    keyCol,
    colorCol,
    sampleCol,
    wellCol,
    zCol,
    tCol,
    allPlanes,
    plane.z,
    plane.t,
    info,
    activeWell,
    activeStore,
    config.points_scale,
    config.points_z_tolerance,
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
  const [labelsOutline, setLabelsOutline] = usePersistedVizControl(metadata, 'labels_outline', true);
  const [labelsOpacity, setLabelsOpacity] = usePersistedVizControl(metadata, 'labels_opacity', 0.5);
  const [labelsSize, setLabelsSize] = useState<{ width: number; height: number } | null>(null);

  // Open the paired store once the image is up; drop it when unpaired. Hiding
  // the labels keeps the store open (the layer just stops drawing).
  // Without a labels DC, an OME-Zarr image's own `labels/` group (NGFF) is
  // drawn the same way; a store that has none simply shows no labels.
  const embeddedLabels = !labelsDcId && activeStoreFormat === 'ome-zarr' && !!activeStoreName;
  const [embeddedLabelsFound, setEmbeddedLabelsFound] = useState(false);
  const labelsWanted = Boolean(labelsDcId && pairedLabelsName) || embeddedLabelsFound;
  useEffect(() => {
    if (!viewer || !info) return;
    let cancelled = false;
    setLabelsDrawn(false);
    setLabelsError(null);
    setLabelsSize(null);
    setEmbeddedLabelsFound(false);
    const open = async () => {
      if (labelsDcId && pairedLabelsName) return createBioimageZarrStore(labelsDcId, pairedLabelsName);
      if (!embeddedLabels || !imageDcId || !activeStoreName) return null;
      // The image's own `labels/` group: its first label image, by the name it lists.
      const image = subStore(createBioimageZarrStore(imageDcId, activeStoreName), imagePath ?? '');
      const path = await firstLabelPath(image);
      return path ? subStore(image, path) : null;
    };
    open()
      .then((store) => (cancelled ? null : viewer.setLabels(store)))
      .then((opened) => {
        if (cancelled || !opened) return;
        setLabelsSize({ width: opened.width, height: opened.height });
        if (embeddedLabels) setEmbeddedLabelsFound(true);
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof Error && err.name === 'LoadSupersededError')) return;
        setLabelsError(
          embeddedLabels
            ? `Could not open the labels of ${activeStoreName}: ${errorText(err)}`
            : `Could not open the labels of ${pairedLabelsName}: ${errorText(err)}`,
        );
      });
    return () => {
      cancelled = true;
    };
    // `info` is a new object on every load, including a refresh of the same image.
  }, [
    viewer,
    info,
    labelsDcId,
    pairedLabelsName,
    embeddedLabels,
    imageDcId,
    activeStoreName,
    imagePath,
    refreshTick,
  ]);

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

  // ---- Reference image (a step's fixed image) ------------------------------
  const referenceName = activeStep?.reference ?? null;
  const referenceKnown = Boolean(
    referenceName && stores?.some((st) => st.name === referenceName),
  );
  const [compareMode, setCompareMode] = useState<CompareMode>('colours');
  const [compareOpacity, setCompareOpacity] = useState(0.5);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  const comparing = referenceKnown && compareMode !== 'off';
  useEffect(() => {
    if (!viewer) return;
    let cancelled = false;
    setReferenceError(null);
    const store =
      comparing && imageDcId && referenceName
        ? createBioimageZarrStore(imageDcId, referenceName)
        : null;
    viewer.setReference(store).catch((err: unknown) => {
      if (cancelled || (err instanceof Error && err.name === 'LoadSupersededError')) return;
      setReferenceError(`Could not open the reference ${referenceName}: ${errorText(err)}`);
    });
    return () => {
      cancelled = true;
    };
  }, [viewer, imageDcId, referenceName, comparing]);
  // Colours mode compares one channel: the first one shown.
  const compareChannel = channels.find((c) => c.visible)?.index ?? 0;
  useEffect(() => {
    if (!viewer) return;
    viewer.setReferenceStyle({
      mode: comparing ? compareMode : 'off',
      opacity: compareOpacity,
      channel: compareChannel,
    });
  }, [viewer, comparing, compareMode, compareOpacity, compareChannel]);

  // ---- Overlay image (another modality over this one) ---------------------
  const overlayName = config.overlay_store ?? null;
  const overlayKnown = Boolean(overlayName && stores?.some((st) => st.name === overlayName));
  const [overlayChannels, setOverlayChannels] = useState<ChannelState[]>([]);
  const [overlayOpacity, setOverlayOpacity] = usePersistedVizControl(metadata, 'overlay_opacity', 0.6);
  const [overlayError, setOverlayError] = useState<string | null>(null);
  useEffect(() => {
    if (!viewer) return;
    let cancelled = false;
    setOverlayError(null);
    setOverlayChannels([]);
    const store = overlayKnown && imageDcId && overlayName ? createBioimageZarrStore(imageDcId, overlayName) : null;
    viewer
      .setOverlay(store)
      .then((opened) => {
        if (!cancelled && opened) setOverlayChannels(opened.channels);
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof Error && err.name === 'LoadSupersededError')) return;
        setOverlayError(`Could not open the overlay ${overlayName}: ${errorText(err)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [viewer, imageDcId, overlayName, overlayKnown]);
  useEffect(() => {
    viewer?.setOverlayStyle({ channels: overlayChannels, opacity: overlayOpacity });
  }, [viewer, overlayChannels, overlayOpacity]);
  const updateOverlayChannel = (index: number, patch: Partial<ChannelState>) =>
    setOverlayChannels((prev) => prev.map((c) => (c.index === index ? { ...c, ...patch } : c)));

  // The masks show the cells, so their centroids stay undrawn (a lasso still
  // selects on them).
  const [pointRadius, setPointRadius] = usePersistedVizControl(metadata, 'point_radius', 6);
  useEffect(() => {
    if (viewer && info) viewer.setPoints(labelsShown ? [] : overlay, pointRadius);
  }, [viewer, info, overlay, pointRadius, labelsShown]);

  const ownSelectionKey = ownSelection.join('\u0000');
  useEffect(() => {
    if (viewer) viewer.setHighlighted(new Set(ownSelection));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, ownSelectionKey]);

  // The key to the cell colours, as the genome browser keys its tracks: one
  // swatch per category on the shown image, or the ramp of a numeric column.
  const colourKey = useMemo<{ entries: ReturnType<typeof foldByColour>; ramp: LegendRamp | null }>(() => {
    const none = { entries: [], ramp: null };
    if (!colorCol || overlay.length === 0 || !pointRows) return none;
    if (continuous) {
      const fmt = (v: number) => v.toLocaleString(undefined, { maximumSignificantDigits: 3 });
      return {
        entries: [],
        ramp: {
          stops: rampStops(continuous.scale),
          from: fmt(continuous.min),
          to: fmt(continuous.max),
          values: [fmt(continuous.min), fmt(continuous.max)],
        },
      };
    }
    if (!colorScale) return none;
    const present = new Set<string>();
    const cats = pointRows[colorCol] ?? [];
    const samples = sampleCol ? (pointRows[sampleCol] ?? []) : null;
    for (let i = 0; i < cats.length; i += 1) {
      if (samples && activeStore && !isRowOfStore(samples[i], activeStore)) continue;
      present.add(String(cats[i] ?? ''));
    }
    const items = colorScale.universe
      .filter((v) => present.has(v))
      .map((v) => ({ label: v || '(empty)', color: colorScale.get(v) ?? '' }));
    return { entries: foldByColour(items), ramp: null };
  }, [colorScale, continuous, colorCol, overlay.length, pointRows, sampleCol, activeStore]);

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
  const updateChannel = (index: number, patch: Partial<ChannelState>) => {
    const next = channels.map((c) => (c.index === index ? { ...c, ...patch } : c));
    setChannels(next);
    return next;
  };
  const persistChannels = (next: readonly ChannelState[]) =>
    writeConfig({ channels: toConfigChannels(next) });
  const integerDtype = info ? !/^Float/.test(info.dtype) : true;
  const visibleChannels = channels.filter((c) => c.visible).length;

  // T plays by stepping the plane; any other plane change (the slider, a new
  // image) leaves it as the reader set it.
  const [playing, setPlaying] = useState(false);
  const sizeT = info?.sizes.t ?? 1;
  useEffect(() => {
    if (!playing || sizeT <= 1) return;
    const id = window.setInterval(
      () => setPlane((p) => ({ ...p, t: (p.t + 1) % sizeT })),
      PLAY_STEP_MS,
    );
    return () => window.clearInterval(id);
  }, [playing, sizeT]);
  useEffect(() => setPlaying(false), [target?.key]);

  // The encoding tier: what is drawn (which sample, well, plane).
  const primaryControls = useMemo(
    () => (
      <>
        {stepsEnabled && steps ? (
          <>
            {steps.samples.length > 1 ? (
              <VizSelect
                label="Sample"
                searchable
                data={steps.samples}
                value={stepSample}
                onChange={(v) => v != null && setPickedStepSample(v)}
                allowDeselect={false}
              />
            ) : null}
            {/* One unit for the docked panel: a lone line of text is folded under
                "More options", and the metrics belong with the step they describe. */}
            <Stack gap={4}>
              {sampleSteps.length > 1 ? (
                sampleSteps.length <= 5 ? (
                  <VizSegmented
                    label="Step"
                    data={sampleSteps.map((st) => st.label)}
                    value={activeStep?.label ?? ''}
                    onChange={setPickedStep}
                    data-testid="bioimage-steps"
                  />
                ) : (
                  <VizSelect
                    label="Step"
                    data={sampleSteps.map((st) => st.label)}
                    value={activeStep?.label ?? null}
                    onChange={(v) => v != null && setPickedStep(v)}
                    allowDeselect={false}
                    data-testid="bioimage-steps"
                  />
                )
              ) : null}
              {activeStep && stepCols && stepCols.metrics.length ? (
                <Text size="xs" c="dimmed" data-testid="bioimage-step-metrics">
                  {stepCols.metrics
                    .map((m) => {
                      const value = activeStep.metrics[m];
                      const change = previousStep ? metricChange(value, previousStep.metrics[m]) : null;
                      const delta =
                        change == null || change === 0
                          ? ''
                          : ` (${change > 0 ? '+' : '−'}${formatMetric(Math.abs(change))} vs ${previousStep?.label})`;
                      return `${m} ${formatMetric(value)}${delta}`;
                    })
                    .join(' · ')}
                </Text>
              ) : null}
            </Stack>
            {referenceKnown ? (
              <>
                <VizSegmented
                  label="Compare"
                  data={[
                    { value: 'off', label: 'Off' },
                    { value: 'colours', label: 'Colours' },
                    { value: 'fade', label: 'Fade' },
                  ]}
                  value={compareMode}
                  onChange={(v) => setCompareMode(v as CompareMode)}
                  data-testid="bioimage-compare"
                />
                {compareMode === 'fade' ? (
                  <VizSlider
                    label="Reference"
                    min={0}
                    max={1}
                    step={0.05}
                    value={compareOpacity}
                    onChange={setCompareOpacity}
                  />
                ) : null}
                {compareMode === 'colours' ? (
                  <Text size="xs" c="dimmed">
                    {`This step in green, ${referenceName} in magenta: where they agree the image is grey-white.`}
                  </Text>
                ) : null}
              </>
            ) : null}
          </>
        ) : null}
        {!stepsEnabled && sampleStores.length > 1 ? (
          <VizSelect
            label="Sample"
            data={sampleStores.map((s) => ({ value: s.name, label: s.sample }))}
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
        {wells.length > 1 ? (
          <VizSelect
            label="Well"
            searchable
            data={wells.map((w) => ({ value: w.path, label: w.name }))}
            value={activeWell?.path ?? null}
            disabled={wellValue != null}
            description={wellValue != null ? `Follows the ${config.well_column} filter` : undefined}
            onChange={(v) => v && setPickedWell(v)}
            allowDeselect={false}
          />
        ) : null}
        {info && info.sizes.z > 1 ? (
          <PlaneSlider
            label="Z"
            value={plane.z}
            size={info.sizes.z}
            onChange={(v) => setPlane((p) => ({ ...p, z: v }))}
          />
        ) : null}
        {info && info.sizes.t > 1 ? (
          <PlaneSlider
            label="Time"
            value={plane.t}
            size={info.sizes.t}
            playing={playing}
            onTogglePlay={() => setPlaying((p) => !p)}
            onChange={(v) => {
              setPlaying(false);
              setPlane((p) => ({ ...p, t: v }));
            }}
          />
        ) : null}
        {overlayChannels.length ? (
          <VizSlider
            label="Overlay"
            min={0}
            max={1}
            step={0.05}
            value={overlayOpacity}
            onChange={setOverlayOpacity}
            data-testid="bioimage-overlay-opacity"
          />
        ) : null}
      </>
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stores, sampleStores, activeStore, sampleValue, config.sample_column, wells, activeWell, wellValue, config.well_column, info, plane, playing, stepsEnabled, steps, stepSample, sampleSteps, activeStep, previousStep, stepCols, referenceKnown, referenceName, compareMode, compareOpacity, overlayChannels.length, overlayOpacity],
  );

  // The cosmetic tier: how it is drawn. One group per channel, then the labels
  // and the cells; memoised so a zoom (which re-renders for the scale bar)
  // does not hand the frame a new node and re-publish the Settings popover.
  const controls = useMemo(
    () => (
      <>
        {channels.length ? (
          <VizControlGroup
            title={
              channels.length > MAX_RENDERED_CHANNELS
                ? `Channels · ${visibleChannels} of ${channels.length} shown`
                : 'Channels'
            }
          >
            {/* One block: the dock keeps it whole rather than folding channels
                past the first two under "More options". */}
            <Stack gap={2} data-testid="bioimage-channels">
            {channels.map((c) => {
              const [lo, hi] = c.domain;
              const step = integerDtype ? 1 : Math.max((hi - lo) / 500, Number.EPSILON);
              // viv shades a fixed number of channels at once: past it, another
              // one is offered greyed out with the reason.
              const full = !c.visible && visibleChannels >= MAX_RENDERED_CHANNELS;
              return (
                <ChannelRow
                  key={c.index}
                  name={c.name}
                  color={c.color}
                  visible={c.visible}
                  blockedReason={
                    full
                      ? `At most ${MAX_RENDERED_CHANNELS} channels show at once: hide one to show this one`
                      : null
                  }
                  domain={c.domain}
                  step={step}
                  contrastLimits={c.contrastLimits}
                  onVisibleChange={(v) => persistChannels(updateChannel(c.index, { visible: v }))}
                  onColourCommit={(hex) => persistChannels(updateChannel(c.index, { color: hex }))}
                  onContrastChange={(v) => updateChannel(c.index, { contrastLimits: v })}
                  onContrastCommit={(v) => persistChannels(updateChannel(c.index, { contrastLimits: v }))}
                />
              );
            })}
            </Stack>
          </VizControlGroup>
        ) : null}
        {overlayChannels.length ? (
          <VizControlGroup title={`Overlay · ${overlayName}`}>
            <Stack gap={2} data-testid="bioimage-overlay-channels">
              {overlayChannels.map((c) => (
                <ChannelRow
                  key={c.index}
                  name={c.name}
                  color={c.color}
                  visible={c.visible}
                  domain={c.domain}
                  step={1}
                  contrastLimits={c.contrastLimits}
                  onVisibleChange={(v) => updateOverlayChannel(c.index, { visible: v })}
                  onColourCommit={(hex) => updateOverlayChannel(c.index, { color: hex })}
                  onContrastChange={(v) => updateOverlayChannel(c.index, { contrastLimits: v })}
                  onContrastCommit={(v) => updateOverlayChannel(c.index, { contrastLimits: v })}
                />
              ))}
            </Stack>
          </VizControlGroup>
        ) : null}
        {labelsDcId || embeddedLabelsFound ? (
          <VizControlGroup title="Labels">
            <VizSwitch
              label="Show labels"
              checked={labelsVisible}
              disabled={!labelsWanted}
              onChange={(e) => setLabelsVisible(e.currentTarget.checked)}
            />
            <VizSwitch
              label="Outlines"
              checked={labelsOutline}
              disabled={!labelsWanted || !labelsVisible}
              onChange={(e) => setLabelsOutline(e.currentTarget.checked)}
            />
            <VizSlider
              label="Fill opacity"
              min={0}
              max={1}
              step={0.05}
              value={labelsOpacity}
              disabled={!labelsWanted || !labelsVisible}
              thumbLabel={(v) => `${Math.round(v * 100)}%`}
              onChange={setLabelsOpacity}
            />
          </VizControlGroup>
        ) : null}
        {pointsEnabled ? (
          <VizControlGroup title="Cells">
            {stacked ? (
              <VizSwitch
                label="All planes"
                title="Draw every cell, not only the shown plane's"
                checked={allPlanes}
                onChange={(e) => setAllPlanes(e.currentTarget.checked)}
              />
            ) : null}
            <VizSlider
              label="Point size"
              min={1}
              max={20}
              step={1}
              value={pointRadius}
              disabled={labelsShown}
              thumbLabel={(v) => `${v} px`}
              onChange={setPointRadius}
            />
          </VizControlGroup>
        ) : null}
      </>
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [channels, integerDtype, visibleChannels, labelsDcId, embeddedLabelsFound, labelsWanted, labelsVisible, labelsOutline, labelsOpacity, pointsEnabled, pointRadius, labelsShown, stacked, allPlanes, overlayChannels, overlayName],
  );

  // ---- Notices ------------------------------------------------------------
  const notices: Notice[] = [];
  if (pointsError) notices.push({ key: 'points', tone: 'error', text: `Cells: ${pointsError}` });
  if (labelStoresError) {
    notices.push({ key: 'label-stores', tone: 'error', text: `Labels: ${labelStoresError}` });
  }
  if (labelsError) notices.push({ key: 'labels', tone: 'error', text: labelsError });
  if (stepsError) notices.push({ key: 'steps', tone: 'error', text: `Steps: ${stepsError}` });
  if (referenceError) notices.push({ key: 'reference', tone: 'error', text: referenceError });
  if (overlayError) notices.push({ key: 'overlay', tone: 'error', text: overlayError });
  if (overlayName && stores && !overlayKnown) {
    notices.push({
      key: 'overlay-missing',
      tone: 'warning',
      text: `The overlay ${overlayName} is not a store of this image collection.`,
    });
  }
  if (referenceName && stores && !referenceKnown) {
    notices.push({
      key: 'reference-missing',
      tone: 'warning',
      text: `The reference ${referenceName} is not a store of this image collection.`,
    });
  }
  if (labelsMisaligned && labelsSize && info) {
    notices.push({
      key: 'misaligned',
      tone: 'warning',
      text:
        `Labels are ${labelsSize.width} × ${labelsSize.height} px, the image ` +
        `${info.width} × ${info.height} px: they should share one pixel grid.`,
    });
  }
  if (labelsDcId && labelStores && !labelsWanted && activeStore) {
    notices.push({ key: 'no-mask', tone: 'info', text: `No labels for sample "${activeStore.sample}"` });
  }
  if (keptIdsFailed) {
    notices.push({
      key: 'kept',
      tone: 'warning',
      text: 'Could not read which cells the filters keep: every cell is drawn.',
    });
  }

  // ---- Overlay chrome -----------------------------------------------------
  const physical = config.show_scalebar === false ? null : (info?.physicalSize ?? null);
  const bar = physical ? scaleBarLength(physical.value, zoom, 120) : null;
  const hasSelection = roiEnabled && ownSelection.length > 0;

  const pointerModes = useMemo<PointerMode<SelectionMode>[]>(
    () =>
      POINTER_MODES.map((m) => ({
        ...m,
        disabledReason:
          m.value === 'pan' || roiEnabled
            ? null
            : onFilterChange
              ? 'Selection needs cells on the shown image.'
              : 'Selection is off in this read-only view.',
      })),
    [roiEnabled, onFilterChange],
  );

  // A remote store has no ingest check: the API makes one when it is shown.
  const [remoteValidation, setRemoteValidation] = useState<
    Record<string, BioimageNgffValidation | null>
  >({});
  const askRemoteValidation =
    imageDcId && activeStoreName && activeStoreRemote && isZarr && !activeStore?.validation
      ? activeStoreName
      : null;
  useEffect(() => {
    if (!imageDcId || !askRemoteValidation || askRemoteValidation in remoteValidation) return;
    let cancelled = false;
    fetchBioimageRemoteValidation(imageDcId, askRemoteValidation)
      .then((report) => {
        if (!cancelled) setRemoteValidation((m) => ({ ...m, [askRemoteValidation]: report }));
      })
      // A host not allowed or a storage failure: the image error says it; no badge.
      .catch(() => {
        if (!cancelled) setRemoteValidation((m) => ({ ...m, [askRemoteValidation]: null }));
      });
    return () => {
      cancelled = true;
    };
  }, [imageDcId, askRemoteValidation, remoteValidation]);
  const validation =
    activeStore?.validation ?? (activeStoreName ? remoteValidation[activeStoreName] : null) ?? null;
  const helpContext: HelpContext = {
    steps: stepsEnabled && sampleSteps.length > 1,
    reference: referenceKnown,
    samples: stepsEnabled
      ? Boolean(steps && steps.samples.length > 1)
      : Boolean(stores && stores.length > 1),
    sampleFollowsFilter: sampleValue != null || wellValue != null,
    plate: wells.length > 1,
    hasZ: (info?.sizes.z ?? 1) > 1,
    hasT: (info?.sizes.t ?? 1) > 1,
    channels: channels.length,
    points: pointsEnabled,
    colourBy: colorCol,
    pointsFollowPlane: stacked,
    selectable: roiEnabled && Boolean(onFilterChange),
    labels: Boolean(labelsDcId || embeddedLabelsFound),
    overlay: overlayChannels.length > 0,
  };
  const headerBadges: React.ReactNode[] = [
    ...(pointsEnabled
      ? [
          <PointerModeSwitch
            key="mode"
            value={mode}
            modes={pointerModes}
            onChange={setMode}
            aria-label="Pointer mode"
            testId="bioimage-pointer-mode"
            testIdPrefix="bioimage-mode"
          />,
        ]
      : []),
    ...(hasSelection
      ? [
          <Badge
            key="selection"
            size="xs"
            variant="filled"
            radius="sm"
            tt="none"
            data-testid="bioimage-selection-badge"
            rightSection={
              <CloseButton
                size="xs"
                variant="transparent"
                c="inherit"
                aria-label="Clear selection"
                onClick={() => emitSelection([])}
              />
            }
          >
            {ownSelection.length.toLocaleString()} selected
          </Badge>,
        ]
      : []),
    ...(activeStore
      ? [
          <BioimageBadges
            key="store"
            format={activeStore.format}
            validation={validation}
            ngffVersion={containerValue?.version ?? null}
            axes={info?.labels ?? null}
            layout={containerValue?.layout ?? null}
            labels={labelsShown}
            remote={activeStore.remote}
          />,
        ]
      : []),
  ];

  // What is on screen, under the title: the sample, the well, the plane.
  const echo = activeStore
    ? [
        stores && stores.length > 1 ? activeStore.sample : null,
        activeWell ? `well ${activeWell.name}` : null,
      ]
        .filter(Boolean)
        .join(' · ') || undefined
    : undefined;

  const noStoreMessage =
    !storesLoading && !storesError && stores
      ? stepsEnabled
        ? !steps
          ? undefined
          : !activeStep
            ? 'No processing step matches the filters'
            : !activeStore
              ? `Step "${activeStep.label}" names ${activeStep.store}, which is not a store of this image collection`
              : undefined
        : wellMissing && wellValue != null
        ? `No well "${wellValue}" in this plate`
        : emptyStoreMessage(stores, activeStore, sampleValue)
      : undefined;

  const frameError = storesError ?? targetError ?? imageError;
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

  const showKey = colourKey.ramp !== null || colourKey.entries.length > 0;
  const statusStrip =
    showKey || notices.length ? (
      <Group
        gap="xs"
        justify="space-between"
        wrap="wrap"
        mt={4}
        data-testid="bioimage-status-strip"
        style={{ minWidth: 0 }}
      >
        {showKey ? (
          <ColourKey
            title={colorCol ? keyTitle(colorCol) : undefined}
            entries={colourKey.entries}
            ramp={colourKey.ramp}
            testId="bioimage-colour-key"
            rampTestId="bioimage-colour-ramp"
          />
        ) : (
          <span />
        )}
        {notices.length ? (
          <Stack gap={2} style={{ minWidth: 0, flex: '1 1 200px' }} align="flex-end">
            {notices.map((n) => (
              <Group key={n.key} gap={4} wrap="nowrap" data-testid={`bioimage-notice-${n.key}`}>
                <Icon icon={NOTICE_ICONS[n.tone]} width={12} color={`var(--mantine-color-${n.tone === 'info' ? 'dimmed' : NOTICE_COLOURS[n.tone] + '-6'})`} />
                <Text size="xs" c={NOTICE_COLOURS[n.tone]} lineClamp={2}>
                  {n.text}
                </Text>
              </Group>
            ))}
          </Stack>
        ) : null}
      </Group>
    ) : null;

  // The screenshot capture waits on `data-bioimage-ready`. It sits on a
  // wrapper rather than the host because the frame swaps its children for a
  // skeleton, an alert or an empty state, and every branch must report.
  // `display: contents` keeps the wrapper out of the tile's layout.
  return (
    <div data-bioimage-ready={ready} style={{ display: 'contents' }}>
      <AdvancedVizFrame
        title={metadata.title || 'Bioimage'}
        subtitle={(metadata as any).description || (metadata as any).subtitle}
        primaryControls={primaryControls}
        controls={controls}
        echo={echo}
        badges={headerBadges}
        dockEssentials={4}
        loading={storesLoading}
        error={frameError}
        emptyMessage={noStoreMessage}
        dataRows={pointRows ?? undefined}
        dataColumns={pointRows ? pointCols : undefined}
        estimated={pointsEstimated}
      >
        {glGranted ? (
          <Box
            style={{
              display: 'flex',
              flexDirection: 'column',
              width: '100%',
              height: '100%',
              minHeight: 240,
            }}
          >
            <div style={{ position: 'relative', flex: '1 1 auto', minHeight: 200 }}>
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
              <Group gap={4} wrap="nowrap" style={{ position: 'absolute', right: 6, top: 6, zIndex: 2 }}>
                <BioimageHelp context={helpContext} />
                {activeStore && imageDcId ? (
                  <OpenInMenu
                    dcId={imageDcId}
                    store={activeStore}
                    layout={containerValue?.layout ?? null}
                    imagePath={imagePath}
                    view={{
                      channels: channels.map((c) => ({
                        index: c.index,
                        color: c.color,
                        visible: c.visible,
                        window: c.contrastLimits,
                      })),
                      z: info && info.sizes.z > 1 ? plane.z : null,
                      t: info && info.sizes.t > 1 ? plane.t : null,
                      width: info?.width ?? null,
                      height: info?.height ?? null,
                    }}
                  />
                ) : null}
                <Tooltip label="Reset view" withArrow openDelay={300}>
                  <ActionIcon
                    size="sm"
                    variant="default"
                    aria-label="Reset view"
                    data-testid="bioimage-reset-view"
                    onClick={() => viewer?.resetView()}
                  >
                    <Icon icon="tabler:focus-centered" width={14} height={14} />
                  </ActionIcon>
                </Tooltip>
              </Group>
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
            {statusStrip}
          </Box>
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

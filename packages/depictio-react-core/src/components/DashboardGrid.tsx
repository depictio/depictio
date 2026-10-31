import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Responsive as ResponsiveGridLayout } from 'react-grid-layout';
import {
  GRID_BREAKPOINTS,
  GRID_COL_COUNTS,
  GRID_MAX_COLS,
  GRID_WIDEST_BREAKPOINT,
  ROW_SPLIT,
  breakpointForWidth,
  phoneLayout,
  scaleLayout,
  toSplitRows,
} from '../gridConfig';
import type { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { StoredMetadata, InteractiveFilter } from '../api';
import type { FilterSectionSpec } from '../api';
import { ActiveHighlight } from '../highlight';
import { HighlightProvider } from '../highlight/bus';
import { useZoomSyncRegistered } from '../highlight/zoomSync';
import ZoomSyncSectionButton from './ZoomSyncSectionButton';
import type { GroupRenderState } from '../selectionGroups';
import {
  PANEL_RESIZE_END_EVENT,
  PANEL_TOGGLE_EVENTS,
  PanelToggleDetail,
  isPanelResizing,
} from '../utils/panelToggle';
import { Accordion, ActionIcon, Badge, Button, Group, Paper, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { collapsedSectionKeys, sectionComponents } from '../utils/groupInteractive';
import type { ComponentSection } from '../utils/groupInteractive';
import { extractLayoutItems, stripBoxPrefix } from '../utils/leftPanelLayout';
import { useCollapseState } from '../hooks/useCollapseState';
import { sameSectionName, useRevealComponent, useRevealSection } from '../reveal';
import { resolveSectionColor, sectionColorVar } from './SectionIcon';
import {
  applyAccordionValue,
  SectionAccordion,
  SectionAccordionItem,
  SectionHeader,
} from './SectionAccordion';
import ComponentRenderer, { formatValue, inferCardTitle } from './ComponentRenderer';
import { FilterStripSection, SectionFilterBar } from './interactive/strip/FilterStrip';
import {
  barSectionNames,
  hasSectionBar,
  isBarMember,
  isStripSection,
  sectionRuns,
} from './interactive/strip/stripLayout';
import { isFilterActive } from '../activeFilters';
import { filtersInScope, sectionFilterScopes, type FilterScopes } from '../filterScope';
import { withSectionStyles } from './figureStyle';
import { usePreannouncedDefaultRegions } from './advanced_viz/genomespy/defaultRegionGate';
import {
  fitLayoutHeights,
  isAutofitted,
  useAutofitHeights,
  GRID_ROW_GAP_PX,
  GRID_ROW_PX,
  SPLIT_ROW_PX,
} from './autofit';
import { DensityContext } from './density';
import {
  LINKED_VIEW_MIN_PANE_PX,
  effectiveDisplay,
  fitRowPx,
  layoutRows,
  minRowPxForTiles,
  rowFloorPx,
} from './sectionGroups';
import type { LayoutOverride } from './sectionGroups';
import LinkedViewPanes, { LinkedViewControls } from './LinkedViewPanes';
import type { LinkedViewPanesMode } from './LinkedViewPanes';
import {
  LINKED_VIEW_GUTTER_PX,
  buildSplitTree,
  splitSignature,
  treeLayouts,
  treeMinHeightPx,
  linkedViewSplitStorageKey,
} from './linkedViewSplit';
import type { SplitTree } from './linkedViewSplit';
import {
  applyRecordPanels,
  findSidePanels,
  linkedSelectionActive,
  panelExpanded,
  reconcileOverrides,
  recordPanelLinks,
  sectionSidePanels,
} from './recordPanelLayout';
import type { RecordSidePanel } from './recordPanelLayout';
import { RecordPanelContext, RecordPanelSource, RecordPanelToggle } from './RecordPanel';
import type { FoldedRecordPanel, RecordPanelState } from './RecordPanel';

/** Bucket key for what is left of the unsectioned components once the tab's
 *  opening text has been split off — never a real section name, so it can't
 *  collide with `sectionKey(name)`. */
const UNSECTIONED_REST_KEY = '\u0000unsectioned-rest';

/** What a linked view section's frame (header, paddings) is taken to cost until
 *  it has been measured, in px. */
const FALLBACK_CHROME_PX = 64;
/** A scrolling container shorter than this is not a screen worth fitting to. */
const MIN_FIT_VIEWPORT_PX = 240;

/** How a linked view section is laid out this render: its layout, the panes it
 *  is cut into (null where react-grid-layout draws it), the least each tile
 *  keeps, and how a change to the split is written. */
interface LinkedViewPlan {
  layout: Layout[];
  width: number;
  /** Row height, px, of the section's grid: fitted to the screen, and never
   *  under what the tiles' floors need. */
  rowPx: number;
  tree: SplitTree | null;
  mode: LinkedViewPanesMode | null;
  /** The least each tile keeps by default, px, by layout key. */
  floors: Record<string, number>;
  /** Height of the panes, px; 0 without a tree. */
  height: number;
  /** `edit`: the layout the section was opened with, for Reset. */
  baseline: SplitTree | null;
  /** Write `next` into the dashboard like a resize of the grid would. */
  commit: (next: SplitTree) => void;
}

interface DashboardGridProps {
  dashboardId: string;
  metadataList: StoredMetadata[];
  layoutData?: unknown;
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Precomputed card values keyed by component index. */
  cardValues?: Record<string, unknown>;
  /** Precomputed secondary aggregations keyed by component index → aggregation name. */
  cardSecondaryValues?: Record<string, Record<string, unknown>>;
  /** True while the bulk compute is pending. */
  cardValuesLoading?: boolean;
  /**
   * Counter incremented to force per-component data fetches to re-run even
   * when ``filters`` is reference-equal (e.g. on a realtime ``data_collection_updated``
   * event). Renderers include this in their effect deps; ``undefined`` is a no-op.
   */
  refreshTick?: number;
  /** The batch currently highlighted (live arrival or a pinned re-selection
   *  from the event log). Forwarded to renderers so they glow its rows. */
  activeHighlight?: ActiveHighlight | null;
  /** Selection groups to color figures by. Forwarded to figure renderers,
   *  which fold it into their render request. */
  groupRender?: GroupRenderState;
  /** Allow users to drag grid items. Defaults to false (viewer-safe). */
  isDraggable?: boolean;
  /** Allow users to resize grid items. Defaults to false (viewer-safe). */
  isResizable?: boolean;
  /** Whether the grid is being used in edit mode. Drives overlay rendering. */
  editMode?: boolean;
  /**
   * Fired on every drag/resize end. Only meaningful when `isDraggable` or
   * `isResizable` is true. We forward whatever react-grid-layout emits.
   */
  onLayoutChange?: (newLayout: Layout[]) => void;
  /**
   * Dashboard-level autofit switch (`DashboardData.autofit`). False restores
   * stored-height-only layout for every tile on the dashboard.
   */
  autofit?: boolean;
  /**
   * Fired when the user resizes a tile's height by hand, with the height they
   * dragged it to. The editor answers by writing `fit: 'fixed'` on that
   * component, which takes it out of autofit for good, the one gesture in the
   * precedence chain that outranks the content.
   */
  onTileFixed?: (componentId: string, height: number) => void;
  /**
   * Optional per-cell overlay renderer. When `editMode` is true and this
   * callback is provided, the returned node is rendered absolutely positioned
   * in the top-right of each grid cell (above the component content).
   */
  renderItemOverlay?: (
    componentId: string,
    metadata: StoredMetadata,
  ) => React.ReactNode;
  /** `DashboardData.grid_sections` — order, icons and default collapse for the
   *  grid's accordion sections. Empty means no sections, i.e. one flat grid. */
  gridSections?: FilterSectionSpec[];
  /**
   * Rendered between the unsectioned bucket and this tab's named sections —
   * the slot the apps put the cross-tab `PersistentSectionsHost` (`pin: top`)
   * in, so a family-wide section lands after the tab's own title/intro text
   * (the unsectioned components) instead of above it, matching the order its
   * owning tab draws. Opaque on purpose: its members must never enter this
   * grid's layout merge.
   */
  beforeSections?: React.ReactNode;
  /**
   * Host-provided per-section actions, beside the fold control rather than
   * inside it. Called with the section name (`null` for the unsectioned grid,
   * which has no header). The editor puts its "…" here, so a section is edited
   * from where it is seen.
   */
  renderSectionActions?: (sectionName: string | null) => React.ReactNode;
  /**
   * Editor-only per-filter actions for the members of a filter bar (a grid
   * section with `display: 'strip'`). Separate from `renderItemOverlay`
   * because a filter's menu offers the filter sections and bars it can move
   * to, not the grid's tile sections.
   */
  renderStripItemOverlay?: (metadata: StoredMetadata) => React.ReactNode;
  /**
   * The filters a filter bar's controls display, when they should differ from
   * `filters`. The apps hand the grid a debounced copy (and with group filters
   * folded in) so figures don't refetch per keystroke; a control has to show a
   * click at once, as the filter panel's do.
   */
  controlFilters?: InteractiveFilter[];
  /**
   * Which filters belong to a section's own bar (`filterScope.ts`). A cell in
   * section S is handed the tab's filters plus S's bar filters, and no other
   * section's. The apps pass the family-wide map (a bar fanned out from a
   * sibling tab scopes its filters away from this grid too); without it the
   * grid derives the map from its own sections.
   */
  filterScopes?: FilterScopes;
  /** Clears the given filters (by index): a bar's "Reset". */
  onResetFilters?: (indices: string[]) => void;
  /**
   * Where the sections' fold state is kept. Defaults to the dashboard's own
   * key, so a reader's folds survive a reload. `null` keeps it in memory: a
   * grid drawing the dashboard's sections somewhere else (the Guide) must not
   * fold or unfold them on the dashboard.
   */
  collapseStorageKey?: string | null;
  /**
   * The reader's `?layout=` pick for grid sections that declare
   * `display: 'linked'` (`sectionGroups.ts`): `classic` draws them as
   * ordinary sections, null keeps what the dashboard declares. Has no effect
   * on a dashboard without them.
   */
  layoutOverride?: LayoutOverride;
}

/**
 * The stored `lg` layout, scaled to every breakpoint.
 *
 * Given only `lg`, react-grid-layout derives the others by cloning it and
 * running `correctBounds`, which *clamps* `w` to the column count rather than
 * scaling it. A half-width tile (w 4 of 8) therefore stays w 4 and becomes a
 * full row at `sm` (4 of 4), so the same dashboard read as half-width in one
 * surface and full-width in another purely because their containers sit either
 * side of a breakpoint. Scaling proportionally (`scaleLayout`) keeps a
 * half-width tile half a row everywhere, while still degrading to fewer, wider
 * columns on a phone.
 */
/** One layout per breakpoint, proportionally rescaled from the `lg` one.
 *  Exported because every grid that shows stored tiles needs it: handing
 *  react-grid-layout only `lg` lets it generate the narrower breakpoints
 *  itself, and its `correctBounds` clamps a right-hand tile onto its
 *  neighbour, which vertical compaction then pushes onto its own row — two
 *  half-width tables stack instead of sitting side by side. */
export function responsiveLayouts(lg: Layout[]): Record<string, Layout[]> {
  return {
    lg,
    md: scaleLayout(lg, GRID_COL_COUNTS.md),
    sm: scaleLayout(lg, GRID_COL_COUNTS.sm),
    xs: phoneLayout(lg, GRID_COL_COUNTS.xs),
  };
}

/**
 * Renders the dashboard component tree inside react-grid-layout. Depictio's
 * stored_layout_data uses dash-dynamic-grid-layout's format, which is a thin
 * wrapper over react-grid-layout — same {i, x, y, w, h} shape works directly.
 *
 * When stored_layout_data is absent, components are auto-placed in a 2-column
 * flow to give the viewer SOMETHING reasonable (matches Dash's fallback).
 *
 * By default the grid is purely read-only (no drag, no resize, no overlay).
 * Editor callers opt in via `isDraggable` / `isResizable` / `editMode` /
 * `renderItemOverlay`.
 */
const DashboardGrid: React.FC<DashboardGridProps> = ({
  dashboardId,
  metadataList,
  layoutData,
  filters,
  onFilterChange,
  cardValues,
  cardSecondaryValues,
  cardValuesLoading,
  refreshTick,
  activeHighlight,
  groupRender,
  isDraggable = false,
  isResizable = false,
  editMode = false,
  onLayoutChange,
  autofit = true,
  onTileFixed,
  renderItemOverlay,
  gridSections,
  beforeSections,
  renderSectionActions,
  renderStripItemOverlay,
  controlFilters,
  filterScopes,
  onResetFilters,
  collapseStorageKey,
  layoutOverride = null,
}) => {
  // Filter-bar members ride along in `metadataList` so they bucket into their
  // section, but they are drawn by the bar and never laid out on the grid:
  // their coordinates (if any) live in the left panel's layout, and an item
  // without one here would be auto-placed — and then persisted by the editor.
  const barNames = useMemo(() => barSectionNames(gridSections), [gridSections]);
  const onGrid = useCallback((m: StoredMetadata) => !isBarMember(m, barNames), [barNames]);
  const gridMetadata = useMemo(() => metadataList.filter(onGrid), [metadataList, onGrid]);
  const scopes = useMemo(
    () => filterScopes ?? sectionFilterScopes(metadataList, gridSections),
    [filterScopes, metadataList, gridSections],
  );
  // What a bar's controls show and count as active: the instant copy.
  const shownFilters = controlFilters ?? filters;

  // A locus navigator below the fold sits behind LazyMount and cannot announce
  // its default region before the tracks above the fold fetch, so the layout
  // announces it from the stored config (`defaultRegionGate.ts`).
  usePreannouncedDefaultRegions(metadataList, Boolean(onFilterChange));

  // Memoised because it feeds the deps of everything below: rebuilding this
  // array on every render (a panel toggle, a collapse click) would invalidate
  // the memoised grid cells and re-render every Plotly figure on the dashboard.
  const layouts = useMemo(
    () => normalizeLayout(gridMetadata, layoutData, isDraggable || isResizable, false),
    [gridMetadata, layoutData, isDraggable, isResizable],
  );

  // Measure our own container so the grid never overflows the parent pane.
  // Falls back to viewport width on first render before the ResizeObserver
  // fires (single frame, harmless).
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState<number>(() =>
    typeof window !== 'undefined' ? window.innerWidth - 40 : 1200,
  );
  // Non-null while a sidebar collapse/expand transition is in flight. While
  // locked, the ResizeObserver suppresses its updates so the predicted final
  // `containerWidth` (set once at toggle time) doesn't get stomped on by the
  // 60+ in-flight RO firings as the parent CSS-animates its width.
  const lockedWidthRef = useRef<number | null>(null);
  // How much narrower a section's grid is than the wrapper: a section draws a
  // box around its content, so the room left inside it is the wrapper minus that
  // chrome. RGL takes a pixel width, and a width one inset too wide overflows
  // the box and gets clipped by the wrapper's `overflowX: hidden` — the
  // rightmost component in every section loses its edge. Measured rather than
  // restated from the CSS, so the treatment can change without this drifting.
  const [sectionInset, setSectionInset] = useState(0);
  // The same for a linked view, whose frame pads its tiles less (sectionAccordion.css,
  // glass.css): measured on a linked view of its own, null until there is one.
  const [linkedViewInset, setLinkedViewInset] = useState<number | null>(null);
  const measureRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (!wrapperRef.current || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const next = wrapper.getBoundingClientRect().width;
      if (!next || next <= 0) return;
      setContainerWidth(Math.floor(next));
      // Every ordinary section draws the same chrome, so one of them answers
      // for all; a linked view draws a tighter one, and answers for itself.
      const probe = wrapper.querySelector('[data-section-grid]:not([data-linked-view-grid])');
      if (probe) {
        setSectionInset(Math.max(0, Math.round(next - probe.getBoundingClientRect().width)));
      }
      const bench = wrapper.querySelector('[data-linked-view-grid]');
      if (bench) {
        setLinkedViewInset(Math.max(0, Math.round(next - bench.getBoundingClientRect().width)));
      }
    };
    measureRef.current = measure;
    const ro = new ResizeObserver(() => {
      if (lockedWidthRef.current !== null) return;
      // A panel drag changes this width on every pointermove. Re-laying out
      // every section's grid that often is what made the drag heavier the more
      // of the dashboard was expanded, so the grid holds still until the drag
      // ends and then measures once. See `panelToggle.ts`.
      if (isPanelResizing()) return;
      measure();
    });
    ro.observe(wrapperRef.current);
    window.addEventListener(PANEL_RESIZE_END_EVENT, measure);
    return () => {
      ro.disconnect();
      window.removeEventListener(PANEL_RESIZE_END_EVENT, measure);
    };
  }, []);

  // When a chrome panel toggles, jump `containerWidth` to its predicted final
  // value in one shot. RGL re-renders item transforms once with that final
  // value, and the existing CSS transition (bumped to 300ms during the
  // sidebar slide via `body.sidebar-transitioning`) animates each item from
  // its current transform to the new one — perfectly in sync with Mantine's
  // own 300ms ease width transition on the navbar.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let rafId: number | null = null;
    // Shared across toggles rather than captured per invocation: with several
    // panels able to animate (sidebar, filter panel), a second toggle landing
    // mid-transition has to extend the running pump. A per-invocation deadline
    // would be invisible to the loop already in flight, which then expires on
    // the first toggle's schedule and leaves the second one un-pumped.
    let transitionEndAt = 0;
    const onPanelToggle = (event: Event) => {
      const detail = (event as CustomEvent).detail as PanelToggleDetail | undefined;
      if (!detail) return;
      // Use the locked width if a previous toggle is still in flight (rapid
      // re-toggle); otherwise read the live DOM width before applying delta.
      const baseWidth =
        lockedWidthRef.current !== null
          ? lockedWidthRef.current
          : wrapperRef.current?.getBoundingClientRect().width ?? 0;
      if (baseWidth <= 0) return;
      const delta = detail.willBeOpen ? -detail.swingPx : detail.swingPx;
      const final = Math.max(100, Math.floor(baseWidth + delta));
      lockedWidthRef.current = final;
      setContainerWidth(final);

      // Plotly's `useResizeHandler` and AG Grid both listen to the WINDOW
      // resize event, not the per-cell ResizeObserver. As the panel slides,
      // each grid item's CSS transition smoothly grows/shrinks its outer
      // div, but Plotly's <canvas>/<svg> stays pinned at its pre-toggle
      // pixel size — producing the clipped / stretched look the user sees.
      // Dispatch synthetic window resize events on each animation frame for
      // the transition's duration so Plotly + AG Grid re-flow in lockstep.
      // Both internally throttle, so 60Hz dispatch is cheap.
      transitionEndAt = Math.max(transitionEndAt, performance.now() + detail.durationMs + 50);
      const tickResize = () => {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new Event('resize'));
        }
        if (performance.now() < transitionEndAt) {
          rafId = requestAnimationFrame(tickResize);
        } else {
          rafId = null;
        }
      };
      if (rafId == null) rafId = requestAnimationFrame(tickResize);

      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        lockedWidthRef.current = null;
        timer = null;
        // Reconcile with reality after the transition (handles browser-resize
        // mid-toggle, sub-pixel rounding, etc.).
        if (wrapperRef.current) {
          const w = wrapperRef.current.getBoundingClientRect().width;
          if (w > 0) setContainerWidth(Math.floor(w));
        }
        // One final resize so figures/tables snap to exact final dims.
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new Event('resize'));
        }
      }, detail.durationMs + 50);
    };
    for (const name of PANEL_TOGGLE_EVENTS) {
      window.addEventListener(name, onPanelToggle as EventListener);
    }
    return () => {
      for (const name of PANEL_TOGGLE_EVENTS) {
        window.removeEventListener(name, onPanelToggle as EventListener);
      }
      if (timer) clearTimeout(timer);
      if (rafId != null) cancelAnimationFrame(rafId);
    };
  }, []);

  // Section collapse. Persisted per dashboard, and a dashboard author can seed
  // it via `grid_sections`.
  const sectionsCollapsedByDefault = useMemo(
    () => collapsedSectionKeys(gridSections),
    [gridSections],
  );
  const sectionCollapse = useCollapseState(
    collapseStorageKey === undefined ? `grid-section-collapsed:${dashboardId}` : collapseStorageKey,
    sectionsCollapsedByDefault,
  );
  // Tiles that can zoom together now, for the sections' sync button. Read from
  // the host's provider: the viewer and the editor wrap the grid in one, which
  // the grid's own provider below reuses.
  const zoomSyncable = useZoomSyncRegistered();

  // One bucket per `section`. A dashboard that sets none produces a single
  // unnamed bucket and renders exactly as it did before sections existed.
  //
  // `includeEmpty` only in edit mode: a section just created from the Sections
  // manager has no members yet, and skipping it would make the act of creating
  // one look like it did nothing. A published dashboard still never shows an
  // empty band.
  const sections = useMemo(() => {
    const buckets = sectionComponents(metadataList, gridSections, editMode);
    // Split the unsectioned bucket after its opening text, so a persistent
    // section fanned out from a sibling tab can land between the two.
    //
    // A pinned section is the family's shared content: it has to sit in the
    // same place on every tab. Rendered after the whole unsectioned bucket it
    // did on a tab with sections of its own — but on a tab that sections
    // nothing, the bucket IS the tab, and the pinned section fell to the very
    // bottom. Rendered before it, it jumps ahead of the intro text that says
    // what the tab is. The intro belongs first, the shared metadata second.
    //
    // Edit mode keeps the single flat bucket: splitting it would put the intro
    // text in a grid of its own, where it could no longer be dragged next to
    // the components below it.
    if (editMode) return buckets;
    const flatIdx = new Map(layouts.map((l, i) => [l.i, i]));
    const at = (m: StoredMetadata) => {
      const l = layouts.find((x) => x.i === m.index);
      return l ? [l.y, l.x, flatIdx.get(m.index) ?? 0] : [0, 0, flatIdx.get(m.index) ?? 0];
    };
    return buckets.flatMap((b) => {
      if (b.sectionName || b.members.length === 0) return [b];
      const ordered = [...b.members].sort((a, c) => {
        const [ay, ax, ai] = at(a);
        const [cy, cx, ci] = at(c);
        return ay - cy || ax - cx || ai - ci;
      });
      let lead = 0;
      while (lead < ordered.length && ordered[lead].component_type === 'text') lead += 1;
      // No opening text: the whole bucket is "the rest", so the pinned section
      // still renders above it rather than below the tab's entire content.
      if (lead === 0) return [{ ...b, key: UNSECTIONED_REST_KEY }];
      if (lead === ordered.length) return [b];
      return [
        { ...b, members: ordered.slice(0, lead) },
        { ...b, key: UNSECTIONED_REST_KEY, members: ordered.slice(lead) },
      ];
    });
  }, [metadataList, gridSections, editMode, layouts]);
  /**
   * Sections whose grid is actually rendered: the ones open now, plus every one
   * that has been open at some point since mount.
   *
   * A section that has never been opened renders no grid at all. Mantine's
   * `Accordion.Panel` collapses to `height: 0` but keeps its children mounted,
   * so a folded section's figures were mounting, and mounting is what starts
   * their fetch. The viewport gate does not save them either: a child inside a
   * zero-height panel has a zero-height rect sitting at the section header's y,
   * which `useInView`'s fallback probe reads as on-screen. So a dashboard whose
   * author folded a section by default still paid for every figure in it —
   * exactly the cost folding is supposed to avoid.
   *
   * Additive rather than tracking the current state, so collapsing a section
   * again keeps its figures mounted and re-expanding is instant. Only the
   * never-opened case is worth the refetch, and that is the case where there is
   * nothing to throw away.
   */
  const openSectionKeys = sections.filter((s) => sectionCollapse.isOpen(s.key)).map((s) => s.key);
  const [renderedSections, setRenderedSections] = useState<Set<string>>(
    // Seeded from the first render so a section that starts open draws its grid
    // immediately, rather than painting empty and filling in an effect later.
    () => new Set(openSectionKeys),
  );
  useEffect(() => {
    setRenderedSections((prev) => {
      const missing = openSectionKeys.filter((k) => !prev.has(k));
      return missing.length ? new Set([...prev, ...missing]) : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSectionKeys.join(' ')]);

  // The dashboard search, asking for a component in a folded section: open it,
  // as a click on its header would, and the effect above mounts its grid. A
  // plain section never folds and a filter bar has no fold, so neither has
  // anything to open.
  useRevealComponent((index) => {
    const section = sections.find((s) => s.members.some((m) => m.index === index));
    if (!section?.sectionName) return;
    if (section.spec?.appearance === 'plain' || isStripSection(section.spec)) return;
    if (!sectionCollapse.isOpen(section.key)) sectionCollapse.setAll([section.key], false);
  });
  // A text tile's `section:` link, the same opening by the section's name.
  useRevealSection((name) => {
    const section = sections.find((s) => sameSectionName(s.sectionName, name));
    if (!section || section.spec?.appearance === 'plain' || isStripSection(section.spec)) return;
    if (!sectionCollapse.isOpen(section.key)) sectionCollapse.setAll([section.key], false);
  });

  // The inset probe is a section's grid, so the first measurement can only
  // happen once one has rendered — and again whenever the set of them changes,
  // since a dashboard can go from no sections to some without the wrapper
  // resizing. `renderedSections` is in here for the all-folded dashboard, where
  // the first grid to exist is the one the user has just expanded.
  useEffect(() => {
    measureRef.current();
  }, [sections, renderedSections]);

  // Latest grid order per section, so a drag in one section can be merged with
  // the others' current positions into the single flat array we persist.
  const sectionLayoutsRef = useRef<Map<string, Layout[]>>(new Map());
  // Linked view sections drawn as split panes (`renderLinkedView`). They report
  // only when one of their gutters is moved, not on every change of layout like
  // a react-grid-layout does, so the order remembered above goes stale for them:
  // another section's drag must merge their stored layout, not that.
  const splitSectionsRef = useRef<Set<string>>(new Set());
  // The editor's Reset restores a linked view to the layout it was opened with.
  // Held per section for as long as this grid lives: the first layout it sees,
  // replaced when the section is re-cut or changes from outside (a restored
  // version), never by the section's own gutters (`ours` marks those writes).
  const linkedViewBaselines = useRef(
    new Map<string, { structure: string; baseline: SplitTree; seen: string; ours: boolean }>(),
  );

  // Text tiles size themselves to their prose, and cards to their content. A
  // stored height is a guess made when the component was written, and it is
  // wrong as soon as the wording changes, the viewport does, or the card gains
  // a breakdown it did not have: too small and the content spills over the tile
  // below, too large and the tile is mostly blank. The renderers measure what
  // they actually need and we turn that into rows here.
  const autoHeights = useAutofitHeights();
  // Nothing a read-only grid lays out is ever persisted, which is what lets it
  // fit tiles to their content and count in half rows.
  const readOnly = !(isDraggable || isResizable);
  // Edit mode: the linked views an author is arranging, drawn as the plain
  // grid so their tiles can be moved and resized, then turned back into a
  // linked view built from the new positions. This editor session only.
  const [arranging, setArranging] = useState<ReadonlySet<string>>(() => new Set());
  const toggleArranging = useCallback((key: string) => {
    setArranging((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }, []);

  // The height each tile is stored with, and which of them follow their
  // content. Both are needed on the way back out: what the editor renders is
  // the fitted layout, and what it must persist is the stored one.
  const storedHeights = useMemo(() => {
    const map = new Map<string, number>();
    for (const l of layouts) map.set(l.i, l.h);
    return map;
  }, [layouts]);
  const autofittedIds = useMemo(() => {
    const ids = new Set<string>();
    if (!autofit) return ids;
    for (const m of metadataList) if (isAutofitted(m)) ids.add(m.index);
    return ids;
  }, [metadataList, autofit]);
  // Tiles the user has just resized by hand, between react-grid-layout's
  // `onResizeStop` and the `onLayoutChange` that follows it. Their new height
  // is the one thing on that pass that must be persisted rather than reverted
  // to what is stored; `onTileFixed` takes them out of autofit for later
  // passes, but that write is a render away.
  const resizedByHand = useRef<Set<string>>(new Set());

  const baseLayoutForSection = useCallback(
    (allMembers: StoredMetadata[], spec?: FilterSectionSpec, fitted = true): Layout[] => {
      const members = allMembers.filter(onGrid);
      const ids = new Set(members.map((m) => m.index));
      const mine = layouts.filter((l) => ids.has(l.i));
      // `y` is stored per dashboard, not per section, so a section whose members
      // sit low in the flat layout (a table at y=22) would open onto 22 rows of
      // nothing once it gets a grid of its own. Re-packing rebases it to the top
      // and closes the gaps the other sections' members left behind. In edit mode
      // react-grid-layout would converge to the same packing on its own; doing it
      // up front means the first paint is already right.
      // Convert each measured height into rows before packing, so the packing
      // closes up around the real sizes. GRID_ROW_PX / GRID_ROW_GAP_PX mirror
      // the `rowHeight` and vertical `margin` handed to ResponsiveGridLayout
      // below; a read-only grid counts in half rows (gridConfig's ROW_SPLIT,
      // SPLIT_ROW_PX) so a fitted tile stops within half a row of its content.
      // Runs in the editor too, so the author sizes tiles against what the
      // reader will see. What the editor must never do is persist a fitted
      // height: `handleSectionLayoutChange` puts the stored heights back before
      // anything reaches `onLayoutChange`, and a tile the user resizes by hand
      // leaves autofit altogether (`fit: fixed`). A read-only grid persists
      // nothing at all.
      // Cards are fitted in the style they are drawn in, their section's
      // included: a row of compact cards is the one row of cards that may
      // shrink (see `fitLayoutHeights`).
      const styled = members.map((m) => withSectionStyles(m, spec));
      const sized = readOnly
        ? fitLayoutHeights(styled, toSplitRows(mine), autoHeights, fitted && autofit, SPLIT_ROW_PX)
        : fitLayoutHeights(styled, mine, autoHeights, fitted && autofit);
      const packed = compactVerticallyForStatic(sized);
      // Lone-row widening runs HERE, against the section's own members — never
      // against the flat union, where co-authored rows from sibling sections
      // overlap and shove each other apart (see `normalizeLayout`'s pack flag).
      // Gated on `mine`, i.e. the section's positions as stored: an item the
      // author left alone on its row keeps its width, only one that lost a
      // neighbour gets widened.
      return readOnly ? widenLoneRows(packed, rowMateSet(mine)) : packed;
    },
    [layouts, readOnly, autoHeights, autofit, onGrid],
  );

  // Record cards laid out as their source's side panel (`recordPanelLayout.ts`).
  // Reading only: the editor always shows the author's own geometry, so a
  // panel never folds while the layout can be dragged or resized.
  const panelsEnabled = !editMode && !isDraggable && !isResizable;
  const recordLinks = useMemo(() => recordPanelLinks(metadataList), [metadataList]);
  // A linked view (`display: 'linked'`, sectionGroups.ts) needs the 8-column
  // layout. Below it (a phone, a narrow pane) its tiles stack as in any other
  // section.
  const groupsWide = breakpointForWidth(containerWidth) === GRID_WIDEST_BREAKPOINT;
  const sidePanels = useMemo(() => {
    const byCard = new Map<string, RecordSidePanel>();
    if (!panelsEnabled || recordLinks.size === 0) return byCard;
    for (const section of sections) {
      const base = baseLayoutForSection(section.members, section.spec);
      const override = arranging.has(section.key) ? 'classic' : layoutOverride;
      const linkedView = groupDisplay(section, override, groupsWide, onGrid) === 'linked';
      for (const panel of sectionSidePanels(base, recordLinks, linkedView)) {
        byCard.set(panel.cardId, panel);
      }
    }
    return byCard;
  }, [
    panelsEnabled,
    recordLinks,
    sections,
    baseLayoutForSection,
    layoutOverride,
    arranging,
    groupsWide,
    onGrid,
  ]);

  // Folded while the source holds no pick, unfolded while it does; a reader's
  // toggle wins until the source's pick appears or goes away.
  const selectionActive = useMemo(() => {
    const active: Record<string, boolean> = {};
    for (const panel of sidePanels.values()) {
      active[panel.cardId] = linkedSelectionActive(filters, panel.sourceId);
    }
    return active;
  }, [sidePanels, filters]);
  const [panelOverrides, setPanelOverrides] = useState<Record<string, boolean>>({});
  const previousActiveRef = useRef<Record<string, boolean>>({});
  useEffect(() => {
    const previous = previousActiveRef.current;
    previousActiveRef.current = selectionActive;
    setPanelOverrides((current) => reconcileOverrides(current, previous, selectionActive));
  }, [selectionActive]);

  const recordPanelState = useMemo<RecordPanelState>(() => {
    const expanded = (cardId: string) =>
      panelExpanded(Boolean(selectionActive[cardId]), panelOverrides[cardId]);
    const foldedBySource = new Map<string, FoldedRecordPanel>();
    for (const panel of sidePanels.values()) {
      if (expanded(panel.cardId)) continue;
      const card = metadataList.find((m) => m.index === panel.cardId);
      foldedBySource.set(panel.sourceId, { panel, title: card?.title || 'Record' });
    }
    return {
      panel: (cardId) => sidePanels.get(cardId),
      expanded,
      toggle: (cardId) =>
        setPanelOverrides((current) => ({ ...current, [cardId]: !expanded(cardId) })),
      foldedFor: (sourceId) => foldedBySource.get(sourceId),
    };
  }, [sidePanels, selectionActive, panelOverrides, metadataList]);
  const recordSources = useMemo(() => new Set(recordLinks.values()), [recordLinks]);

  // A fold changes two tiles' widths without the window changing, and Plotly
  // only re-flows on a window `resize`. Pump it for the length of RGL's width
  // transition so a widened chart follows the tile; AG Grid watches its own
  // container and re-fits its columns on its own.
  const foldSignature = [...sidePanels.keys()]
    .map((id) => `${id}:${recordPanelState.expanded(id) ? 1 : 0}`)
    .join(' ');
  const firstFoldRef = useRef(true);
  useEffect(() => {
    if (firstFoldRef.current) {
      firstFoldRef.current = false;
      return;
    }
    if (typeof window === 'undefined') return;
    const until = performance.now() + 300;
    let rafId: number | null = null;
    const tick = () => {
      window.dispatchEvent(new Event('resize'));
      rafId = performance.now() < until ? requestAnimationFrame(tick) : null;
    };
    rafId = requestAnimationFrame(tick);
    return () => {
      if (rafId != null) cancelAnimationFrame(rafId);
    };
  }, [foldSignature]);

  const layoutsForSection = useCallback(
    (members: StoredMetadata[], spec?: FilterSectionSpec, fitted = true): Layout[] => {
      const base = baseLayoutForSection(members, spec, fitted);
      if (sidePanels.size === 0) return base;
      const panels = findSidePanels(base, recordLinks).filter((p) => sidePanels.has(p.cardId));
      return applyRecordPanels(base, panels, (cardId) => !recordPanelState.expanded(cardId));
    },
    [baseLayoutForSection, sidePanels, recordLinks, recordPanelState],
  );

  const handleSectionLayoutChange = useCallback(
    (sectionKey: string, current: Layout[], width: number) => {
      // `onLayoutChange` also fires on a breakpoint switch, and on mount,
      // carrying the narrowed layout. Persisting that would silently overwrite
      // the desktop arrangement with its 2-column fallback the first time
      // someone opened the editor on a small screen. The breakpoint is the
      // grid's width's (see `breakpointForWidth`).
      if (breakpointForWidth(width) !== GRID_WIDEST_BREAKPOINT) return;
      // A read-only grid counts in half rows: what it reports is not a layout
      // that could be stored.
      if (readOnly) return;
      // What react-grid-layout hands back carries the FITTED heights, because
      // that is what it was rendered with. Persisting those would freeze one
      // reader's viewport into the dashboard and make the next content change
      // unable to move the tile. Put the stored height back on every tile that
      // follows its content, except the one the user is resizing right now,
      // whose whole point is the new height.
      const asStored = current.map((item) => {
        if (!autofittedIds.has(item.i) || resizedByHand.current.has(item.i)) return item;
        const stored = storedHeights.get(item.i);
        return stored === undefined || stored === item.h ? item : { ...item, h: stored };
      });
      resizedByHand.current.clear();
      // Re-close the gaps the restored heights leave behind, so the array we
      // persist is a layout in its own right rather than one that only packs
      // correctly at the viewport it was measured in.
      sectionLayoutsRef.current.set(sectionKey, compactVerticallyForStatic(asStored));

      const merged: Layout[] = [];
      // Sections stack, so each one's rows are offset past everything above it.
      // That keeps the persisted array valid as a single flat grid too — which
      // is what a dashboard falls back to if its sections are ever removed.
      let yOffset = 0;
      for (const section of sections) {
        // Fall back to what that section is actually *rendering*, not to a raw
        // slice of `layouts`: `layoutsForSection` re-packs a section to the top
        // of its own grid, so slicing here would persist the un-rebased
        // positions for every section the user hasn't dragged yet.
        // `fitted: false`, for the same reason the touched section's heights
        // are put back: a section the user never opened must be persisted at
        // the heights it is stored with, not at the ones its content asked for.
        const remembered =
          section.key !== sectionKey && splitSectionsRef.current.has(section.key)
            ? undefined
            : sectionLayoutsRef.current.get(section.key);
        const sectionLayout =
          remembered ?? baseLayoutForSection(section.members, section.spec, false);

        let sectionBottom = 0;
        for (const item of sectionLayout) {
          merged.push({ ...item, y: item.y + yOffset });
          sectionBottom = Math.max(sectionBottom, item.y + item.h);
        }
        yOffset += sectionBottom;
      }
      onLayoutChange?.(merged);
    },
    [onLayoutChange, baseLayoutForSection, sections, readOnly, autofittedIds, storedHeights],
  );

  /** A height the user dragged to outranks anything the content asks for, so
   *  the tile leaves autofit. A drag moves the tile without resizing it and is
   *  deliberately not a gesture here. Neither is a resize below the widest
   *  breakpoint (the grid's width's, as in `handleSectionLayoutChange`): that
   *  layout is never persisted, so pinning the tile there would save
   *  `fit: fixed` without the height that justified it, and the tile would lose
   *  autofit at its old stored height. */
  const handleResizeStop = useCallback(
    (oldItem: Layout, newItem: Layout, width: number) => {
      if (!onTileFixed || newItem.h === oldItem.h) return;
      if (breakpointForWidth(width) !== GRID_WIDEST_BREAKPOINT) return;
      resizedByHand.current.add(newItem.i);
      onTileFixed(newItem.i, newItem.h);
    },
    [onTileFixed],
  );

  // ---- Linked view sections (`display`, see sectionGroups.ts) ----
  //
  // Linked tiles that stay close enough for a brush on one to show on the others
  // without scrolling. A linked view is a view of the stored layout, which it never
  // rewrites: the section is laid out at a row height that fits the screen. Its
  // record side panels never fold (`sidePanels`), so a pick moves no pane.
  // `groupsWide` is declared with the side panels, above.

  /** How a section is drawn: its `display`, the reader's `?layout=` and the
   *  room there is deciding. Anything this cannot place is an ordinary section. */
  const kindOf = (section: ComponentSection): 'grid' | 'linked' =>
    groupDisplay(
      section,
      arranging.has(section.key) ? 'classic' : layoutOverride,
      groupsWide,
      onGrid,
    ) ?? 'grid';
  const hasLinkedView = sections.some((s) => kindOf(s) === 'linked');

  // The part of the scrolling container a reader sees, which is what a linked view
  // is fitted to. The container is the nearest ancestor that scrolls (the app's
  // dashboard body), the window when none does. What its padding and its
  // `scroll-padding` set aside (a gutter, the glass shell's floating dock) is not
  // visible room, so the height excludes both, whichever is larger on each edge.
  const [viewportHeight, setViewportHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!hasLinkedView) return;
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const scroller = scrollParentOf(wrapper);
    const read = () => {
      const style = scroller ? getComputedStyle(scroller) : null;
      const keepTop = style
        ? Math.max(pxOf(style.paddingTop), pxOf(style.scrollPaddingTop))
        : 0;
      const keepBottom = style
        ? Math.max(pxOf(style.paddingBottom), pxOf(style.scrollPaddingBottom))
        : 0;
      const height = Math.floor(
        (scroller ? scroller.clientHeight : window.innerHeight) - keepTop - keepBottom,
      );
      const next = height >= MIN_FIT_VIEWPORT_PX ? height : null;
      setViewportHeight((prev) => (prev === next ? prev : next));
    };
    read();
    const observer =
      scroller && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(read) : null;
    if (scroller) observer?.observe(scroller);
    window.addEventListener('resize', read);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', read);
    };
  }, [hasLinkedView]);

  // What a linked view's frame costs in height (header, paddings, borders, the
  // section's own filter bar): the tiles get what is left of the visible height.
  // Read from the DOM after every render, since it depends on the theme and on
  // which sections are open, and kept only when it changed.
  const [linkedViewChrome, setLinkedViewChrome] = useState(0);
  useLayoutEffect(() => {
    if (!hasLinkedView) return;
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    let chrome = 0;
    wrapper.querySelectorAll('[data-linked-view-grid]').forEach((grid) => {
      const item = grid.closest('.depictio-section-item');
      if (item) chrome = Math.max(chrome, frameHeight(item));
    });
    setLinkedViewChrome((prev) => (prev === chrome ? prev : chrome));
  });

  // A linked view fills the visible height: its rows (the layout's, counted in the
  // unit the grid lays out in) and the gaps between them share what the frame
  // leaves. Never less than its tiles need to keep their own minimum
  // (`floorRowPx`): a stack of three is taller than a laptop's screen, and the
  // reader scrolls a little instead of reading three slivers.
  const normalRowPx = readOnly ? SPLIT_ROW_PX : GRID_ROW_PX;
  const linkedViewRowPx = (layout: Layout[], floorRowPx: number) =>
    viewportHeight
      ? fitRowPx(
          layoutRows(layout),
          viewportHeight - (linkedViewChrome || FALLBACK_CHROME_PX),
          GRID_ROW_GAP_PX,
          normalRowPx,
          1,
          floorRowPx,
        )
      : Math.max(normalRowPx, floorRowPx);

  const showOverlays = editMode && typeof renderItemOverlay === 'function';
  const rootClass =
    'depictio-dashboard-grid' + (editMode ? ' depictio-edit-mode' : '');

  // The grid cells, memoised per section and deliberately NOT keyed on
  // `containerWidth`.
  //
  // React bails out of re-rendering a subtree whose element is referentially
  // unchanged. Building these inline meant every `DashboardGrid` render — a
  // panel slide, a section toggle — produced a fresh element for all of them, so
  // React re-rendered every Plotly figure and AG Grid on the dashboard to reach
  // the one cell that actually changed. Item geometry is RGL's business and
  // travels through `layouts`, not through these children.
  // The filters each section's cells see: the tab's, plus the section's own
  // bar's (see `filterScope.ts`). The same array as `filters` wherever nothing
  // is scoped away, so a dashboard without section bars renders as before.
  const filtersBySection = useMemo(() => {
    const byKey = new Map<string, InteractiveFilter[]>();
    for (const section of sections) {
      byKey.set(section.key, filtersInScope(filters, scopes, section.sectionName ?? null));
    }
    return byKey;
  }, [sections, filters, scopes]);

  const cellsBySection = useMemo(() => {
    const byKey = new Map<string, { id: string; node: React.ReactNode }[]>();
    // The renderer inside a cell that drives a record side panel: wrapped so
    // the folded card's rail can sit on its edge (`RecordPanelSource`).
    const panelSource = (m: StoredMetadata, node: React.ReactNode) =>
      recordSources.has(m.index) ? (
        <RecordPanelSource sourceId={m.index}>{node}</RecordPanelSource>
      ) : (
        node
      );
    for (const section of sections) {
      const sectionFilters = filtersBySection.get(section.key) ?? filters;
      byKey.set(
        section.key,
        section.members.filter(onGrid).map((m) => ({ id: m.index, node: (
          // Outer div = the cloned target react-resizable injects the
          // resize-handle <span>s into. It must NOT clip overflow or the
          // top-edge handles (nw/n/ne) get sliced off — the inner div clips
          // content (Plotly modebar, AG Grid scroll shadow, ...) instead.
          <div
            key={m.index}
            data-component-id={m.index}
            style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                overflow: 'hidden',
                flex: 1,
                minHeight: 0,
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {recordLinks.has(m.index) ? (
                // A folded card leaves the grid altogether (its rail is drawn
                // by the source's cell), so only the unfolded card is here.
                <ComponentRenderer
                  dashboardId={dashboardId}
                  metadata={withSectionStyles(m, section.spec)}
                  filters={sectionFilters}
                  onFilterChange={onFilterChange}
                  refreshTick={refreshTick}
                  activeHighlight={activeHighlight}
                  groupRender={groupRender}
                  extraActions={
                    showOverlays ? (
                      renderItemOverlay!(m.index, m)
                    ) : (
                      <RecordPanelToggle cardId={m.index} />
                    )
                  }
                  showDragHandle={editMode && isDraggable}
                />
              ) : panelSource(m, (
                <ComponentRenderer
                  dashboardId={dashboardId}
                  // A card or figure that sets no style of its own takes its section's.
                  // Resolved here, where the section is known, rather than
                  // written onto the card: a card added to the section later, or
                  // a section restyled later, follows without a migration.
                  metadata={withSectionStyles(m, section.spec)}
                  filters={sectionFilters}
                  onFilterChange={onFilterChange}
                  cardValue={cardValues?.[m.index]}
                  cardSecondaryValues={cardSecondaryValues?.[m.index]}
                  cardLoading={cardValuesLoading}
                  refreshTick={refreshTick}
                  activeHighlight={activeHighlight}
                  groupRender={groupRender}
                  extraActions={showOverlays ? renderItemOverlay!(m.index, m) : undefined}
                  showDragHandle={editMode && isDraggable}
                />
              ))}
            </div>
          </div>
        ) })),
      );
    }
    return byKey;
  }, [
    sections,
    dashboardId,
    filters,
    filtersBySection,
    onFilterChange,
    cardValues,
    cardSecondaryValues,
    cardValuesLoading,
    refreshTick,
    activeHighlight,
    groupRender,
    showOverlays,
    renderItemOverlay,
    editMode,
    isDraggable,
    onGrid,
    recordLinks,
    recordSources,
  ]);

  // Explicit width rather than `WidthProvider`: that HOC installs its own
  // window listener, which would fight `lockedWidthRef` and undo the
  // panel-transition sync above. Sectioned grids sit inside the section box
  // and get the room left inside it; the unsectioned bucket has no box and
  // spans the wrapper.
  // A filter bar's other members sit under the bar, outside any section box.
  const gridWidth = (section: ComponentSection) =>
    section.sectionName && !isStripSection(section.spec)
      ? Math.max(
          100,
          containerWidth -
            (kindOf(section) === 'linked' ? (linkedViewInset ?? sectionInset) : sectionInset),
        )
      : containerWidth;

  /**
   * One react-grid-layout over `layouts`, which every grid of the dashboard is
   * drawn with. `persistKey` is the section whose layout it reports to the
   * editor's save path.
   */
  const renderTiles = (o: {
    layouts: Record<string, Layout[]>;
    rowHeight: number;
    width: number;
    persistKey: string;
    children: React.ReactNode;
  }) => (
    <ResponsiveGridLayout
      className="layout"
      layouts={o.layouts}
      // Shared geometry (see gridConfig.ts): `lg` keeps the authoring 8-column
      // grid down to narrow content widths so opening the panels shrinks
      // components instead of wrapping them; fewer columns are a phone-only
      // fallback.
      breakpoints={GRID_BREAKPOINTS}
      cols={GRID_COL_COUNTS}
      // Half rows when read-only: the unit `layoutsForSection` counts in.
      rowHeight={o.rowHeight}
      width={o.width}
      // Asymmetric grid gap: horizontal stays at 12 px (visual breathing room
      // between side-by-side cards / plots) but vertical drops to 4 px so
      // stacked rows feel tightly packed — short text intros, Manhattan→
      // filter-strip transitions, etc. no longer have a wasteful gap.
      margin={[12, GRID_ROW_GAP_PX]}
      containerPadding={[0, 0]}
      isDraggable={isDraggable}
      isResizable={isResizable}
      compactType="vertical"
      onLayoutChange={(current) => handleSectionLayoutChange(o.persistKey, current, o.width)}
      // Live-resize: Plotly's useResizeHandler and AG Grid only listen to
      // the WINDOW ``resize`` event, not container size changes. While the
      // user is dragging a resize handle the cell DIM changes but the
      // window doesn't, so Plotly/AG Grid never re-flow until release.
      // Dispatch a synthetic resize event on every onResize tick so the
      // figure / table tracks the cell size live.
      onResize={() => {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new Event('resize'));
        }
      }}
      // Fires before the `onLayoutChange` of the same gesture (RGL calls the
      // prop, then `onLayoutMaybeChanged`), which is what lets the merge tell
      // this tile's new height apart from every other tile's fitted one on
      // that pass.
      onResizeStop={(_layout, oldItem, newItem) => handleResizeStop(oldItem, newItem, o.width)}
      // Drag is gated to a dedicated handle (see ComponentChrome's
      // `react-grid-dragHandle` action). Cells themselves are NOT draggable
      // — the user can interact with content (Plotly modebar, AG Grid
      // selectors, etc.) without accidentally starting a drag.
      draggableHandle=".react-grid-dragHandle"
      resizeHandles={['s', 'e', 'w', 'n', 'sw', 'se', 'nw', 'ne']}
    >
      {o.children}
    </ResponsiveGridLayout>
  );

  /** The cells of `section` that `layout` places, in the order they were built. */
  const cellsFor = (section: ComponentSection, layout: Layout[]) => {
    const placed = new Set(layout.map((l) => l.i));
    return (cellsBySection.get(section.key) ?? [])
      .filter((cell) => placed.has(cell.id))
      .map((cell) => cell.node);
  };

  const renderGrid = (section: ComponentSection) =>
    !section.members.some(onGrid) ? (
      // Only shown in edit mode (`includeEmpty`). Without a body a freshly
      // created section is an accordion item that opens onto nothing, which
      // reads as broken rather than as empty. A section holding only its bar's
      // filters has no tiles either, and readers see just the bar.
      editMode ? (
        <Paper withBorder radius="md" p="lg" bg="var(--mantine-color-default-hover)">
          <Text size="sm" c="dimmed" ta="center">
            No components yet — move one here from its ⋮ menu, or pick this section
            while creating one.
          </Text>
        </Paper>
      ) : null
    ) : (
    renderTiles({
      layouts: responsiveLayouts(layoutsForSection(section.members, section.spec)),
      rowHeight: normalRowPx,
      width: gridWidth(section),
      persistKey: section.key,
      children: (cellsBySection.get(section.key) ?? [])
        // A folded record card has no layout item (`applyRecordPanels`), and
        // react-grid-layout would place a child without one on its own.
        .filter((cell) => !sidePanels.has(cell.id) || recordPanelState.expanded(cell.id))
        .map((cell) => cell.node),
    })
    );

  const leadBucket = sections.find((s) => !s.sectionName && s.key !== UNSECTIONED_REST_KEY);
  const restBucket = sections.find((s) => s.key === UNSECTIONED_REST_KEY);
  const named = sections.filter((s) => s.sectionName);
  // A persistent section is family-wide content: it has to land in the same
  // place on the tab that owns it and on every tab it fans out to. On a foreign
  // tab it arrives through `beforeSections`; here it would otherwise keep its
  // declared position among this tab's own sections, which on a tab with no
  // sections is below everything. Hoisting it out of `named` puts both copies
  // in the one place: under the tab's opening text, above everything else.
  const isPinnedTop = (s: ComponentSection) =>
    Boolean(s.spec?.persistent) && s.spec?.pin !== 'bottom';
  const pinnedTop = named.filter(isPinnedTop);
  const ownSections = named.filter((s) => !isPinnedTop(s));
  // Drives one button rather than a pair: "collapse all" until nothing is open,
  // then "expand all". A single control can't be in the dead state where the
  // one you want is the one already applied.
  // Plain sections have no fold, so they neither count nor get the button.
  const isPlain = (s: ComponentSection) => s.spec?.appearance === 'plain';
  // A filter bar is neither: no header, no fold.
  const isStrip = (s: ComponentSection) => isStripSection(s.spec);
  const foldable = named.filter((s) => !isPlain(s) && !isStrip(s));
  const anySectionOpen = foldable.some((s) => sectionCollapse.isOpen(s.key));

  // A bar's "Reset": clears its own controls, and only those.
  const resetFor = (members: StoredMetadata[]) =>
    onResetFilters ? () => onResetFilters(members.map((m) => m.index)) : undefined;

  const renderStripSection = (section: ComponentSection) => {
    const rest = section.members.filter(onGrid);
    const members = section.members.filter((m) => !onGrid(m));
    return (
      <FilterStripSection
        key={section.key}
        name={section.sectionName ?? ''}
        spec={section.spec}
        members={members}
        filters={shownFilters}
        onFilterChange={onFilterChange}
        onReset={resetFor(members)}
        editMode={editMode}
        actions={editMode ? renderSectionActions?.(section.sectionName ?? null) : undefined}
        renderItemActions={editMode ? renderStripItemOverlay : undefined}
        rest={rest.length > 0 ? renderGrid(section) : null}
      />
    );
  };

  // A section's own bar, drawn under its heading; its filters reach this
  // section's cells only (`filtersBySection`).
  const renderSectionBar = (section: ComponentSection) => {
    if (!hasSectionBar(section.spec)) return null;
    const members = section.members.filter((m) => !onGrid(m));
    return (
      <SectionFilterBar
        name={section.sectionName ?? ''}
        spec={section.spec}
        members={members}
        filters={shownFilters}
        onFilterChange={onFilterChange}
        onReset={resetFor(members)}
        editMode={editMode}
        renderItemActions={editMode ? renderStripItemOverlay : undefined}
      />
    );
  };

  // Filter bars break the accordion: each renders on its own, and the
  // sections between two bars share one accordion as before.
  const renderSections = (list: ComponentSection[]) =>
    list.length === 0
      ? null
      : sectionRuns(list, isStrip).map((run) =>
          run.strip
            ? renderStripSection(run.section)
            : renderAccordion(run.sections),
        );

  /** How a linked view section is laid out: shared by its body and its header's
   *  controls, so both see one answer per render. */
  const linkedViewPlans = new Map<string, LinkedViewPlan>();
  const planFor = (section: ComponentSection): LinkedViewPlan => {
    const cached = linkedViewPlans.get(section.key);
    if (cached) return cached;
    const layout = layoutsForSection(section.members, section.spec, false);
    const width = gridWidth(section);
    const found = buildSplitTree(layout);
    const mode: LinkedViewPanesMode | null =
      !found || found.root.kind !== 'split'
        ? null
        : readOnly
          ? 'view'
          : isResizable && breakpointForWidth(width) === GRID_WIDEST_BREAKPOINT
            ? 'edit'
            : null;
    const tree = mode ? found : null;
    // What each tile keeps by default: a view its minimum, a card or a line of
    // text only the height it was given.
    const types = new Map(section.members.map((m) => [m.index, m.component_type]));
    const floors: Record<string, number> = {};
    for (const l of layout) {
      const type = types.get(l.i);
      floors[l.i] = type === 'card' || type === 'text' ? 0 : LINKED_VIEW_MIN_PANE_PX;
    }
    const floorOf = (key: string) => floors[key] ?? LINKED_VIEW_MIN_PANE_PX;
    // The row height the tiles' floors ask for: summed down each stack of panes,
    // or the tightest tile where react-grid-layout draws it.
    const floorRowPx = tree
      ? rowFloorPx(treeMinHeightPx(tree, floorOf, LINKED_VIEW_GUTTER_PX), tree.h, GRID_ROW_GAP_PX)
      : minRowPxForTiles(layout, floorOf, GRID_ROW_GAP_PX);
    const rowPx = linkedViewRowPx(layout, floorRowPx);

    let baseline: SplitTree | null = null;
    const id = `${dashboardId}:${section.key}`;
    if (tree && mode === 'edit') {
      const structure = splitSignature(tree);
      const seen = JSON.stringify(tree.root);
      let held = linkedViewBaselines.current.get(id);
      if (!held || held.structure !== structure) {
        held = { structure, baseline: tree, seen, ours: false };
        linkedViewBaselines.current.set(id, held);
      } else if (held.seen !== seen) {
        // Moved by one of this section's gutters (or its Reset), or from outside.
        if (!held.ours) held.baseline = tree;
        held.seen = seen;
        held.ours = false;
      }
      baseline = held.baseline;
    }

    // Written like a resize of the grid: a tile whose height changed leaves
    // autofit (`handleResizeStop`), then the section's layout is reported.
    const commit = (next: SplitTree) => {
      const held = linkedViewBaselines.current.get(id);
      if (held) held.ours = true;
      const moved = treeLayouts(next, layout);
      const was = new Map(layout.map((l) => [l.i, l]));
      for (const item of moved) {
        const old = was.get(item.i);
        if (old) handleResizeStop(old, item, width);
      }
      handleSectionLayoutChange(section.key, moved, width);
    };
    const plan: LinkedViewPlan = {
      layout,
      width,
      rowPx,
      tree,
      mode,
      floors,
      // What the grid would be: the rows and the gaps between them.
      height: tree ? tree.h * rowPx + (tree.h - 1) * GRID_ROW_GAP_PX : 0,
      baseline,
      commit,
    };
    linkedViewPlans.set(section.key, plan);
    return plan;
  };

  /** A linked view: the section's stored layout at a row height that fits the
   *  visible screen, and tall enough that each tile keeps its minimum. Not
   *  autofitted (growing a tile would push the section off the screen it was
   *  fitted to).
   *
   *  A layout that cuts into its tiles by straight edge-to-edge lines (every
   *  shipped linked view does) is drawn as split panes with a draggable gutter
   *  between neighbours (`LinkedViewPanes`): one drag moves a shared edge, so a
   *  stack of tiles is resized in one go. A reader's gutters are their own
   *  (this browser's storage, never the dashboard); the editor's snap to grid
   *  units and are saved like a resize of the grid. Tiles are not moved to
   *  other positions there: `?layout=classic` draws the section as the plain
   *  grid, which does. A layout that cannot be cut (a pinwheel, a gap), or a
   *  grid too narrow to save, stays on react-grid-layout as before: its units
   *  and columns are the stored ones, so a drag still writes the right
   *  position. */
  const renderLinkedView = (section: ComponentSection) => {
    const plan = planFor(section);
    if (!plan.tree || !plan.mode) {
      splitSectionsRef.current.delete(section.key);
      return (
        <DensityContext.Provider value="compact">
          {renderTiles({
            layouts: responsiveLayouts(plan.layout),
            rowHeight: plan.rowPx,
            width: plan.width,
            persistKey: section.key,
            children: cellsFor(section, plan.layout),
          })}
        </DensityContext.Provider>
      );
    }
    splitSectionsRef.current.add(section.key);
    const cells = new Map<string, React.ReactElement>();
    for (const cell of cellsBySection.get(section.key) ?? []) {
      cells.set(cell.id, cell.node as React.ReactElement);
    }
    return (
      <DensityContext.Provider value="compact">
        <LinkedViewPanes
          tree={plan.tree}
          cells={cells}
          height={plan.height}
          floors={plan.floors}
          // A read-only grid counts in half rows; the least a tile keeps and a
          // keyboard step are one stored row either way.
          unit={{ x: 1, y: readOnly ? ROW_SPLIT : 1 }}
          mode={plan.mode}
          onCommit={plan.commit}
          storageKey={linkedViewSplitStorageKey(dashboardId, section.key)}
        />
      </DensityContext.Provider>
    );
  };

  /** Reset and Autofit, in the header of a linked view drawn as panes. */
  const renderLinkedViewControls = (section: ComponentSection) => {
    const plan = planFor(section);
    if (!plan.tree || !plan.mode) return null;
    return (
      <LinkedViewControls
        tree={plan.tree}
        baseline={plan.baseline}
        height={plan.height}
        floors={plan.floors}
        demands={autoHeights}
        mode={plan.mode}
        onCommit={plan.commit}
        storageKey={linkedViewSplitStorageKey(dashboardId, section.key)}
      />
    );
  };

  /** Edit mode: move a linked view's tiles on the plain grid, and back. Offered
   *  on a section that declares a linked view and is drawn as one here (not
   *  under `?layout=classic`, not on a narrow screen). */
  const renderArrangeToggle = (section: ComponentSection) => {
    if (readOnly || layoutOverride === 'classic') return null;
    if (groupDisplay(section, null, groupsWide, onGrid) !== 'linked') return null;
    const on = arranging.has(section.key);
    const label = on ? 'Back to the linked view' : 'Arrange tiles';
    const tip = on
      ? 'Show the section as a linked view again, built from the positions set here'
      : 'Show the section as a plain grid to move and resize its tiles; the linked view follows their positions';
    return (
      <Tooltip label={tip} withArrow multiline w={240} openDelay={300}>
        <ActionIcon
          size="sm"
          variant={on ? 'filled' : 'subtle'}
          color={on ? undefined : 'gray'}
          aria-label={label}
          aria-pressed={on}
          data-testid="linked-view-arrange"
          onClick={(event) => {
            event.stopPropagation();
            toggleArranging(section.key);
          }}
        >
          <Icon icon="mdi:cursor-move" width={16} />
        </ActionIcon>
      </Tooltip>
    );
  };

  /** What sits beside a section's fold control: the host's (the editor's "…")
   *  and, for an open linked view, its own Reset and Autofit before it. */
  const sectionActions = (section: ComponentSection, kind: 'grid' | 'linked') => {
    const host = renderSectionActions?.(section.sectionName ?? null);
    const open = sectionCollapse.isOpen(section.key);
    const linked = kind === 'linked' && open ? renderLinkedViewControls(section) : null;
    // Offered once two of the section's tiles can zoom together; a folded
    // section has none mounted, so none registered.
    const syncTiles = section.members
      .map((m) => String(m.index))
      .filter((i) => zoomSyncable.has(i));
    const sync = syncTiles.length >= 2 ? <ZoomSyncSectionButton tiles={syncTiles} /> : null;
    const arrange = open ? renderArrangeToggle(section) : null;
    return sync || linked || arrange ? (
      <Group gap={4} wrap="nowrap" align="center">
        {sync}
        {arrange}
        {linked}
        {host}
      </Group>
    ) : (
      host
    );
  };

  const renderAccordion = (list: ComponentSection[]) =>
    list.length === 0 ? null : (
      <SectionAccordion
        key={list[0].key}
        // A plain section has no fold: always open, and left out of the
        // persisted collapse state.
        value={list
          .filter((s) => isPlain(s) || sectionCollapse.isOpen(s.key))
          .map((s) => s.key)}
        onChange={(open) =>
          applyAccordionValue(
            open,
            list.filter((s) => !isPlain(s)).map((s) => s.key),
            sectionCollapse,
          )
        }
      >
        {list.map((section) => {
          const kind = kindOf(section);
          const badge = (
            <SectionFilteredBadge section={section} filters={shownFilters} onGrid={onGrid} />
          );
          // Only while folded: expanded, these numbers are already on
          // screen as the cards themselves. Folding a section must not
          // cost you the figures it was showing.
          const trailing =
            !isPlain(section) && !sectionCollapse.isOpen(section.key) ? (
              <SectionSummary
                section={{ ...section, members: section.members.filter(onGrid) }}
                cardValues={cardValues}
              />
            ) : undefined;
          return (
            <SectionAccordionItem
              key={section.key}
              value={section.key}
              color={resolveSectionColor(section.spec?.color, section.sectionName)}
              actions={sectionActions(section, kind)}
              plain={isPlain(section)}
              className={kind === 'linked' ? 'is-linked-view' : undefined}
              name={section.sectionName}
            >
              <Accordion.Control>
                {kind === 'grid' ? (
                  <SectionHeader
                    spec={section.spec}
                    name={section.sectionName}
                    badge={badge}
                    trailing={trailing}
                  />
                ) : (
                  <GroupSectionHeader section={section} badge={badge} trailing={trailing} />
                )}
              </Accordion.Control>
              <Accordion.Panel>
                {renderSectionBar(section)}
                {/* Plain wrapper so the width available inside the section box
                    can be read off the DOM — see `sectionInset`. Absent until
                    the section has been opened once: see `renderedSections`. */}
                {(isPlain(section) || renderedSections.has(section.key)) &&
                  (kind === 'linked' ? (
                    <div data-section-grid data-linked-view-grid>
                      {renderLinkedView(section)}
                    </div>
                  ) : (
                    <div data-section-grid>{renderGrid(section)}</div>
                  ))}
              </Accordion.Panel>
            </SectionAccordionItem>
          );
        })}
      </SectionAccordion>
    );

  return (
    // One hover-highlight bus per dashboard view: the protein tiles (3D
    // structure, MSA, sequence track, lollipop, profile) point at the same
    // residues through it without a filter round-trip. See highlight/bus.ts.
    <HighlightProvider>
    <RecordPanelContext.Provider value={recordPanelState}>
    <div
      ref={wrapperRef}
      className={rootClass}
      style={{ width: '100%', overflowX: 'hidden' }}
    >
      {leadBucket && renderGrid(leadBucket)}
      {foldable.length > 0 && (
        <Group justify="flex-end" mb={4}>
          <Button
            variant="subtle"
            color="gray"
            size="compact-xs"
            leftSection={
              <Icon icon={anySectionOpen ? 'mdi:unfold-less-horizontal' : 'mdi:unfold-more-horizontal'} width={14} />
            }
            onClick={() =>
              sectionCollapse.setAll(
                foldable.map((s) => s.key),
                anySectionOpen,
              )
            }
          >
            {anySectionOpen ? 'Collapse all' : 'Expand all'}
          </Button>
        </Group>
      )}
      {/* Straight after the tab's opening text and the section toolbar that
          governs it too, ahead of everything else the tab draws — whether the
          pinned section is owned here (`pinnedTop`) or fanned out from a
          sibling tab (`beforeSections`). Spaced from what follows so the two
          don't read as one stack. */}
      {(beforeSections || pinnedTop.length > 0) && (
        <div style={{ marginBottom: 10 }}>
          {beforeSections}
          {renderSections(pinnedTop)}
        </div>
      )}
      {restBucket && renderGrid(restBucket)}
      {renderSections(ownSections)}
    </div>
    </RecordPanelContext.Provider>
    </HighlightProvider>
  );
};

export default DashboardGrid;

/**
 * "Filtered", beside the heading of a section whose own bar is narrowing it:
 * the cue that these tiles show a subset, and that the rest of the tab does
 * not. Nothing for a section without a bar, or with its bar at rest.
 */
const SectionFilteredBadge: React.FC<{
  section: ComponentSection;
  filters: InteractiveFilter[];
  onGrid: (m: StoredMetadata) => boolean;
}> = ({ section, filters, onGrid }) => {
  if (!hasSectionBar(section.spec)) return null;
  const bar = new Set(section.members.filter((m) => !onGrid(m)).map((m) => m.index));
  const active = filters.filter(
    (f) => bar.has(f.index) && f.source === undefined && isFilterActive(f),
  ).length;
  if (active === 0) return null;
  return (
    <Tooltip
      label={`${active} filter${active === 1 ? '' : 's'} of this section's bar narrow${
        active === 1 ? 's' : ''
      } these tiles. The rest of the tab is not affected.`}
      withArrow
      multiline
      w={260}
    >
      <Badge
        size="sm"
        variant="light"
        radius="sm"
        leftSection={<Icon icon="mdi:filter-variant" width={12} height={12} />}
        style={{ flexShrink: 0, pointerEvents: 'auto' }}
        data-testid="section-filtered-badge"
      >
        Filtered
      </Badge>
    </Tooltip>
  );
};

/**
 * The heading of a linked view section: the same `SectionHeader`, on one line.
 * The description moves into a tooltip on an info glyph (a linked view spends its
 * height on its tiles).
 */
const GroupSectionHeader: React.FC<{
  section: ComponentSection;
  badge?: React.ReactNode;
  trailing?: React.ReactNode;
}> = ({ section, badge, trailing }) => {
  const description = section.spec?.description;
  return (
    <SectionHeader
      spec={section.spec ? { ...section.spec, description: undefined } : section.spec}
      name={section.sectionName}
      badge={
        <>
          {description ? (
            <Tooltip label={description} withArrow multiline w={260} openDelay={400}>
              <Icon
                icon="mdi:information-outline"
                width={14}
                height={14}
                color="var(--mantine-color-dimmed)"
                style={{ flexShrink: 0 }}
              />
            </Tooltip>
          ) : null}
          {badge}
        </>
      }
      trailing={trailing}
    />
  );
};

/** How many metric chips a folded section header shows before it gives up and
 *  falls back to a plain count. Four fits a narrow viewport without wrapping. */
const SUMMARY_CHIP_LIMIT = 4;

/**
 * The numbers a folded section keeps on screen.
 *
 * Deliberately not a new authoring concept: it surfaces the section's own card
 * components, which the dashboard already computes and the grid already
 * receives. A section holding "24 samples" and "98.2% mean coverage" still
 * reads as those two numbers once folded — which is what makes folding a
 * section a way to simplify the dashboard rather than to hide it.
 */
export const SectionSummary: React.FC<{
  section: ComponentSection;
  cardValues?: Record<string, unknown>;
  /** The same cards computed without filters. Where a value differs, the
   *  chip reads "14 / 85": how much of the whole the filters leave. */
  baseValues?: Record<string, unknown>;
}> = ({ section, cardValues, baseValues }) => {
  const cards = section.members.filter(
    (m) => m.component_type === 'card' && cardValues?.[m.index] !== undefined,
  );

  if (cards.length === 0) {
    return (
      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
        {section.members.length} component{section.members.length === 1 ? '' : 's'}
      </Text>
    );
  }

  const shown = cards.slice(0, SUMMARY_CHIP_LIMIT);
  return (
    <Group gap="md" wrap="nowrap">
      {shown.map((m) => (
        // A readout, not a tag. Four identical filled pills read as decoration;
        // a dimmed label over a prominent value reads as the number the card was
        // showing, which is the only reason the summary exists. Each keeps its
        // own card's icon and colour so the folded header still maps onto the
        // cards underneath it.
        <Group key={m.index} gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          {m.icon_name && (
            // A card's own `icon_color` is a free-form value from its builder;
            // the section's colour is a palette name. Either way this is a bare
            // glyph, matching how the card itself draws it.
            <Icon
              icon={m.icon_name}
              width={20}
              height={20}
              style={{
                flexShrink: 0,
                color:
                  m.icon_color ||
                  sectionColorVar(resolveSectionColor(section.spec?.color, section.sectionName)),
              }}
            />
          )}
          <div style={{ minWidth: 0 }}>
            <Text size="xs" c="dimmed" truncate lh={1.2}>
              {(m.title as string) || inferCardTitle(m)}
            </Text>
            <Text size="md" fw={700} lh={1.2} style={{ whiteSpace: 'nowrap' }}>
              {formatValue(cardValues?.[m.index])}
              {baseValues?.[m.index] !== undefined &&
              baseValues[m.index] !== cardValues?.[m.index] ? (
                <Text span size="sm" fw={500} c="dimmed">
                  {' / '}
                  {formatValue(baseValues[m.index])}
                </Text>
              ) : null}
            </Text>
          </div>
        </Group>
      ))}
      {cards.length > shown.length && (
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          +{cards.length - shown.length}
        </Text>
      )}
    </Group>
  );
};

export function normalizeLayout(
  metadataList: StoredMetadata[],
  layoutData: unknown,
  interactive: boolean,
  /**
   * Whether to shelf-pack and widen the flat array here. DashboardGrid passes
   * `false`: its sections each render their own grid, and the stored y values
   * REPEAT across sections (every section starts near y=0 of its own canvas),
   * so packing the flat union makes items from different sections collide,
   * shove each other down, and leave singletons for `widenLoneRows` to blow up
   * to full width. It packs per section instead (`layoutsForSection`).
   */
  pack = true,
): Layout[] {
  // Dash stores layouts as a list of { i: "box-<index>", x, y, w, h } OR as
  // { breakpoint: [...] } keyed dict. Try both shapes.
  const items = extractLayoutItems(layoutData);
  const indexSet = new Set(metadataList.map((m) => m.index));
  // Always override `static` based on the interactive flag — legacy
  // dash-dynamic-grid-layout entries can have static:true baked in, which
  // would lock items even when the editor caller asked for drag/resize.
  // Also clamp w/x into the 8-col grid: positions saved by an earlier React
  // editor pass (when we briefly used cols=12) would be off-grid otherwise
  // and react-grid-layout would stack everything at y=0.
  const COLS = GRID_MAX_COLS;
  const normalized = items
    .map((it) => {
      const w = Math.max(1, Math.min(it.w ?? 1, COLS));
      const x = Math.max(0, Math.min(it.x ?? 0, COLS - w));
      const h = Math.max(1, it.h ?? 1);
      const y = Math.max(0, it.y ?? 0);
      // Strip the per-item ``resizeHandles`` override. Older editor passes
      // baked an incomplete handle list (missing the top edges — n/nw/ne)
      // into stored_layout_data for figure/table cells, which permanently
      // disabled the top resize handles regardless of the GridLayout
      // global default. Card cells never had it set, which is why they
      // always rendered all 8 handles. Removing it lets the global
      // ``resizeHandles`` prop on <GridLayout> apply uniformly.
      const {
        resizeHandles: _strippedHandles,
        ...rest
      } = it as Layout & { resizeHandles?: string[] };
      return {
        ...rest,
        i: stripBoxPrefix(it.i),
        x,
        y,
        w,
        h,
        static: !interactive,
      };
    });
  const matched = normalized.filter((it) => indexSet.has(it.i));
  const matchedIds = new Set(matched.map((it) => it.i));
  // Which items shared a row in the *stored* layout, before anything was
  // filtered out. This is what tells "alone because a neighbour was hidden at
  // render time" apart from "alone because that is the layout" — see
  // widenLoneRows, which may only touch the first kind.
  const hadRowMate = rowMateSet(normalized);

  // Place missing items (e.g. cards never recorded in right_panel_layout_data)
  // immediately below the lowest existing row in a 2-column auto-flow. We
  // never mark items `static: true` when the grid is interactive — that would
  // lock them in place even though the caller asked for editing.
  const baselineY = matched.reduce(
    (max, it) => Math.max(max, (it.y ?? 0) + (it.h ?? 4)),
    0,
  );
  const missing = metadataList.filter((m) => !matchedIds.has(m.index));
  const missingLayout = missing.map((m, idx) => {
    // Defaults mirror depictio/dash/component_metadata.py:DUAL_PANEL_DIMENSIONS
    // (8-col grid, rowHeight=100). Card 25% width, figure 50%, table/map/image
    // full row.
    const dims = defaultDimsFor(m.component_type);
    const colsPerRow = Math.max(1, Math.floor(8 / dims.w));
    return {
      i: m.index,
      x: (idx % colsPerRow) * dims.w,
      y: baselineY + Math.floor(idx / colsPerRow) * dims.h,
      w: dims.w,
      h: dims.h,
      static: !interactive,
    };
  });

  if (matched.length === 0 && missingLayout.length === 0) return [];
  const merged = [...matched, ...missingLayout];
  // In view mode every item is `static: true` so react-grid-layout's built-in
  // vertical compaction is a no-op — gaps left behind by filtered-out items
  // (interactive components routed to the left rail rather than the main grid)
  // stay in the layout. Run a one-shot manual compaction so y values close up,
  // then widen any card left alone on its row so dropped components never leave
  // a half-empty row. (The server re-packs on import; this catches layouts
  // already stored before that pass and anything hidden only at render time.)
  // In editor mode (interactive=true) we leave the layout untouched: items are
  // non-static there, RGL compacts naturally after every drag/resize.
  if (interactive || !pack) return merged;
  return widenLoneRows(compactVerticallyForStatic(merged), hadRowMate);
}

/**
 * Whether a section draws as a linked view, from its `display` and the reader's
 * `?layout=`. Null for everything else: a section needs a name, tiles of its
 * own, and a layout wide enough to hold a linked view; a plain heading and a
 * persistent section (also drawn by other tabs' hosts, which know no
 * linked views) stay as they are.
 */
function groupDisplay(
  section: ComponentSection,
  override: LayoutOverride,
  wide: boolean,
  onGrid: (m: StoredMetadata) => boolean,
): 'linked' | null {
  const spec = section.spec;
  if (!wide || !section.sectionName || !section.members.some(onGrid)) return null;
  if (spec?.appearance === 'plain' || spec?.persistent) return null;
  return effectiveDisplay(spec, override) === 'linked' ? 'linked' : null;
}

/** A computed length in px; 0 for `auto`, empty or anything that is not one. */
function pxOf(value: string | null | undefined): number {
  const n = parseFloat(value ?? '');
  return Number.isFinite(n) ? n : 0;
}

/** The nearest ancestor that scrolls vertically, null when the page does. */
function scrollParentOf(el: HTMLElement): HTMLElement | null {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const overflowY = getComputedStyle(node).overflowY;
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') return node;
  }
  return null;
}

/**
 * The height a section item spends on everything but its tiles: borders, the
 * header and, while open, the body's paddings and whatever sits above the grid
 * (a section's own filter bar). Summed from parts that do not move while the
 * body folds, so it is stable through the accordion's own height transition.
 */
function frameHeight(item: Element): number {
  const style = getComputedStyle(item);
  let height = pxOf(style.borderTopWidth) + pxOf(style.borderBottomWidth);
  height += item.querySelector<HTMLElement>('.depictio-section-control')?.offsetHeight ?? 0;
  if (!item.hasAttribute('data-active')) return height;
  const content = item.querySelector<HTMLElement>('.depictio-section-content');
  if (!content) return height;
  const padding = getComputedStyle(content);
  height += pxOf(padding.paddingTop) + pxOf(padding.paddingBottom);
  for (const child of Array.from(content.children) as HTMLElement[]) {
    if (!child.hasAttribute('data-section-grid')) height += child.offsetHeight;
  }
  return height;
}

/**
 * Shelf-pack `items` vertically so each one sits at the lowest non-colliding y.
 * Only used in view mode where every item is `static: true` and RGL's built-in
 * `compactType="vertical"` is skipped. Mirrors RGL's compaction semantics:
 * items keep their x/w, sort by current (y, x) for stability, then snap up.
 */
function compactVerticallyForStatic(items: Layout[]): Layout[] {
  const sorted = [...items].sort((a, b) => (a.y - b.y) || (a.x - b.x));
  const placed: Layout[] = [];
  for (const item of sorted) {
    let y = 0;
    for (const p of placed) {
      const xOverlap = !(p.x + p.w <= item.x || item.x + item.w <= p.x);
      if (xOverlap) y = Math.max(y, p.y + p.h);
    }
    placed.push({ ...item, y });
  }
  return placed;
}

/** Do two layout items share a horizontal band? */
function overlapsVertically(a: Layout, b: Layout): boolean {
  return !(a.y + a.h <= b.y || b.y + b.h <= a.y);
}

/** Which of `items` share a row with at least one other? The gate for
 *  `widenLoneRows` — pass the layout as *stored*, before anything is dropped. */
function rowMateSet(items: Layout[]): Set<string> {
  return new Set(
    items
      .filter((it) => items.some((o) => o.i !== it.i && overlapsVertically(it, o)))
      .map((it) => it.i),
  );
}

/**
 * Widen an item that ends up alone on its row *because a neighbour was dropped*,
 * so a hidden component never leaves a half-width card sitting beside an empty
 * gap. Mirrors the server's `_recompact_main_grid` lone-row rule for layouts the
 * server didn't re-pack.
 *
 * `hadRowMate` is the gate, and it is the whole point: an item the author left
 * alone on its row at half width must keep that width. Widening every lone item
 * made the viewer disagree with the editor about the size of the same tile —
 * the editor leaves the layout untouched, so a `w: 4` figure was half a row
 * there and a full row here.
 */
function widenLoneRows(
  items: Layout[],
  hadRowMate: Set<string>,
  cols = GRID_MAX_COLS,
): Layout[] {
  return items.map((item) => {
    if (item.w >= cols || !hadRowMate.has(item.i)) return item;
    const stillHasRowMate = items.some(
      (other) => other !== item && overlapsVertically(item, other),
    );
    return stillHasRowMate ? item : { ...item, x: 0, w: cols };
  });
}

/** Default w/h per component_type — mirrors Dash's DUAL_PANEL_DIMENSIONS. */
function defaultDimsFor(componentType: string | undefined): { w: number; h: number } {
  switch (componentType) {
    case 'card':
      return { w: 2, h: 2 };
    case 'figure':
    case 'multiqc':
      return { w: 4, h: 4 };
    case 'table':
      return { w: 8, h: 6 };
    case 'map':
      return { w: 8, h: 6 };
    case 'image':
      return { w: 8, h: 7 };
    case 'jbrowse':
      return { w: 8, h: 6 };
    default:
      return { w: 4, h: 4 };
  }
}

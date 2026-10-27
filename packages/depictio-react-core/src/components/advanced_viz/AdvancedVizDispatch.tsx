import React from 'react';
import { Center, Loader } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { wrapWithChrome } from '../chrome';
import { clearedSelectionFilters, ownSelection } from '../../selection';
import { defaultRegionKey, withoutDefaultRegion } from './genomespy/defaultRegionMemo';
import { HideLegendContext } from './LegendAwarePlot';
import VolcanoRenderer from './VolcanoRenderer';
import EmbeddingRenderer from './EmbeddingRenderer';
import ManhattanRenderer from './ManhattanRenderer';
import StackedTaxonomyRenderer from './StackedTaxonomyRenderer';
import PhylogeneticRenderer from './PhylogeneticRenderer';
import RarefactionRenderer from './RarefactionRenderer';
import DaBarplotRenderer from './DaBarplotRenderer';
import EnrichmentRenderer from './EnrichmentRenderer';
import ComplexHeatmapRenderer from './ComplexHeatmapRenderer';
import UpsetRenderer from './UpsetRenderer';
import MARenderer from './MARenderer';
import DotPlotRenderer from './DotPlotRenderer';
import LollipopRenderer from './LollipopRenderer';
import QQRenderer from './QQRenderer';
import SunburstRenderer from './SunburstRenderer';
import OncoplotRenderer from './OncoplotRenderer';
import CoverageTrackRenderer from './CoverageTrackRenderer';
import SankeyRenderer from './SankeyRenderer';
import PrBenchmarkRenderer from './PrBenchmarkRenderer';
import RocPrCurveRenderer from './RocPrCurveRenderer';
import ConfusionMatrixRenderer from './ConfusionMatrixRenderer';
import MetricCiBarsRenderer from './MetricCiBarsRenderer';
import ProfileRenderer from './ProfileRenderer';
import SignalMatrixRenderer from './SignalMatrixRenderer';
import FusionStructureRenderer from './FusionStructureRenderer';
import GeneArrowTrackRenderer from './GeneArrowTrackRenderer';
import GseaRunningScoreRenderer from './GseaRunningScoreRenderer';
import SashimiRenderer from './SashimiRenderer';
import ScatterXyRenderer from './ScatterXyRenderer';
import SpatialCellsRenderer from './SpatialCellsRenderer';
import ContactMapRenderer from './ContactMapRenderer';
import KneePlotRenderer from './KneePlotRenderer';
import DamageProfileRenderer from './DamageProfileRenderer';
import GenomeViewRenderer from './GenomeViewRenderer';
import GroupCompareRenderer from './GroupCompareRenderer';
import TranscriptStructureRenderer from './TranscriptStructureRenderer';
import CnvProfileRenderer from './CnvProfileRenderer';
import GenomeChordRenderer from './GenomeChordRenderer';
import IdeogramRenderer from './IdeogramRenderer';
import AlleleGridRenderer from './AlleleGridRenderer';
import RecordCardRenderer from './RecordCardRenderer';
import ParallelCoordinatesRenderer from './ParallelCoordinatesRenderer';
import RankedDistributionRenderer from './RankedDistributionRenderer';
import MsaRenderer from './MsaRenderer';
import SequenceTrackRenderer from './SequenceTrackRenderer';
import {
  AdvancedVizDataPopover,
  AdvancedVizDockToggle,
  AdvancedVizExtrasProvider,
  AdvancedVizSettingsPopover,
  AdvancedVizZoomSyncToggle,
} from './AdvancedVizExtras';
import OpenInGenomeBrowserButton from './OpenInGenomeBrowserButton';
import { vizKindLabel } from './vizKindTag';
import { AdvancedVizKindContext } from './VizKindBadge';
import { useDensity } from '../density';
import { ControlsDockContext, isControlsPlacement } from './controlsDock';
import type { ControlsDockState } from './controlsDock';
import type { AdvancedVizExtrasPayload } from './AdvancedVizExtras';
import { useAdvancedVizInspector } from './AdvancedVizInspectorBridge';
import {
  AdvancedVizRegionEchoContext,
  ControlsPlacementContext,
  ControlsPlacementPicker,
  genomeRegionEcho,
  resolveControlsPlacement,
  useAdvancedVizPlacementDefault,
  type ControlsPlacement,
  type ControlsPlacementState,
} from './AdvancedVizInlineControls';
import { useVizConfigWriter } from './usePersistedVizControl';
import LoadAllButton from '../chrome/LoadAllButton';
import { ComponentIndexContext } from '../DashboardLoadingProvider';
import type { GroupRenderState } from '../../selectionGroups';
import SplitPanels from './SplitPanels';
import { groupingModeForKind, panelsForGrouping, shouldSplitIntoPanels } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';
import {
  advancedVizGroupOutcome,
  groupKindNotSplitReasons,
  groupUnmatchedReasons,
  groupUnreachableReasons,
} from '../../groupStatus';
import type { AdvancedVizGroupBadge } from '../../groupStatus';
import {
  GroupColouringReportContext,
  groupColouringActive,
  useReportGroupReach,
} from '../../groupReach';
import GroupStatusBadge, { GroupStatusBadgeContext } from '../GroupStatusBadge';
import { useTabLinkResolver, type TabLinkTarget } from '../tabLinks';
import {
  AdvancedVizCaptionContext,
  AdvancedVizShowcaseContext,
  advancedVizShowcase,
  tabLinkName,
} from './advancedVizShowcase';
import { describeFilters, traceGenome } from '../genomeLink/genomeDebug';

/** The viewer's fold of a tile's docked controls, kept per component in this
 *  browser. Storage can be missing or refuse (a private window): then the
 *  fold lasts as long as the page. */
const DOCK_FOLD_KEY = (index: string) => `depictio.vizControls.folded.${index}`;
function readFolded(index: string): boolean {
  try {
    return window.localStorage.getItem(DOCK_FOLD_KEY(index)) === '1';
  } catch {
    return false;
  }
}
function writeFolded(index: string, folded: boolean): void {
  try {
    if (folded) window.localStorage.setItem(DOCK_FOLD_KEY(index), '1');
    else window.localStorage.removeItem(DOCK_FOLD_KEY(index));
  } catch {
    // Not remembered; the fold still applies to this page.
  }
}

/** The hover line behind each way an advanced viz ends up "not grouped". */
const NOT_GROUPED_REASONS: Record<AdvancedVizGroupBadge, () => string[]> = {
  kind: groupKindNotSplitReasons,
  unreachable: groupUnreachableReasons,
  unmatched: groupUnmatchedReasons,
};

interface AdvancedVizDispatchProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Selection-as-filter callback, forwarded to renderers that emit one: the
   *  phylogeny's subtree filter, and the embedding / Manhattan scatters when
   *  their config opts into selection (see `advancedVizSelectionColumn`).
   *  Other renderers ignore it. Its absence is also the signal that the host
   *  is read-only, which is what keeps the lasso out of the catalog and the
   *  project previews. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
  /** The tab a highlight's source lives on: the header links it in the
   *  `minimal` style, as a figure highlight's does. Wins over `link`. */
  sourceLink?: TabLinkTarget | null;
  /** Dashboard-wide analysis grouping. Renderers whose points map one-to-one
   *  onto rows apply it to their finished figure with `splitFigureByGroups`;
   *  the aggregating ones (UpSet, sunburst, stacked taxonomy) ignore it,
   *  because a group cannot be attributed to a bar that is already a sum. */
  groupRender?: GroupRenderState;
}

// 3Dmol.js is heavy and only a protein tab needs it, so the molecule_3d
// renderer is its own async chunk rather than part of this one, the same way
// ComponentRenderer lazy-loads JBrowse. The Suspense boundary keeps the
// fallback inside the tile instead of blanking the whole dispatch.
const Molecule3DRendererLazy = React.lazy(() => import('./Molecule3DRenderer'));
const Molecule3DRenderer: React.FC<any> = (props) => (
  <React.Suspense
    fallback={
      <Center h="100%">
        <Loader size="sm" />
      </Center>
    }
  >
    <Molecule3DRendererLazy {...props} />
  </React.Suspense>
);

// The five newer protein kinds are lazy chunks too, so a dashboard without one
// pays nothing for them. Same shape as molecule_3d above, built by one helper,
// and each wrapper keeps its renderer's file name:
// `test_advanced_viz_config_alignment` resolves a kind to its source file from
// the name the RENDERERS table below uses.
const lazyTile = (
  Lazy: React.LazyExoticComponent<React.ComponentType<any>>,
): React.FC<any> => {
  const Tile: React.FC<any> = (props) => (
    <React.Suspense
      fallback={
        <Center h="100%">
          <Loader size="sm" />
        </Center>
      }
    >
      <Lazy {...props} />
    </React.Suspense>
  );
  return Tile;
};
const HmmLogoRenderer = lazyTile(React.lazy(() => import('./HmmLogoRenderer')));
const SecondaryStructureRenderer = lazyTile(
  React.lazy(() => import('./SecondaryStructureRenderer')),
);
const DomainArchitectureRenderer = lazyTile(
  React.lazy(() => import('./DomainArchitectureRenderer')),
);
const PaeMatrixRenderer = lazyTile(React.lazy(() => import('./PaeMatrixRenderer')));
const RamachandranRenderer = lazyTile(React.lazy(() => import('./RamachandranRenderer')));

/**
 * `viz_kind` → renderer. Every renderer takes the same
 * `{ metadata, filters, refreshTick, onFilterChange?, groupRender? }` props, so the dispatch
 * is a lookup rather than a chain of comparisons. `ancombc_differentials` was collapsed
 * into `da_barplot` — legacy persisted dashboards still carry the old kind
 * string and need the same renderer.
 */
const RENDERERS: Record<string, React.ComponentType<any>> = {
  // A volcano that binds an MA or QQ view switches between them in place
  // (see deViews.ts).
  volcano: VolcanoRenderer,
  embedding: EmbeddingRenderer,
  manhattan: ManhattanRenderer,
  stacked_taxonomy: StackedTaxonomyRenderer,
  phylogenetic: PhylogeneticRenderer,
  rarefaction: RarefactionRenderer,
  da_barplot: DaBarplotRenderer,
  ancombc_differentials: DaBarplotRenderer,
  // The four retired kinds (`enrichment`, `ma`, `qq`, `roc_pr_curve`) resolve
  // to a surviving renderer through a one-screen wrapper rather than by
  // pointing this map straight at it. The backend rewrites a stored config
  // into the survivor plus a `view`, but `stored_metadata` reaches the client
  // unvalidated, so a config that never went through the model would land on
  // the survivor with no view at all and be drawn as the wrong plot. The
  // wrapper is what pins the view; it reads no config key of its own, which is
  // also what keeps the alignment tests honest.
  enrichment: EnrichmentRenderer,
  complex_heatmap: ComplexHeatmapRenderer,
  upset_plot: UpsetRenderer,
  ma: MARenderer,
  dot_plot: DotPlotRenderer,
  lollipop: LollipopRenderer,
  qq: QQRenderer,
  sunburst: SunburstRenderer,
  oncoplot: OncoplotRenderer,
  coverage_track: CoverageTrackRenderer,
  sankey: SankeyRenderer,
  pr_benchmark: PrBenchmarkRenderer,
  roc_pr_curve: RocPrCurveRenderer,
  confusion_matrix: ConfusionMatrixRenderer,
  metric_ci_bars: MetricCiBarsRenderer,
  profile: ProfileRenderer,
  signal_matrix: SignalMatrixRenderer,
  fusion_structure: FusionStructureRenderer,
  gene_arrow_track: GeneArrowTrackRenderer,
  gsea_running_score: GseaRunningScoreRenderer,
  sashimi: SashimiRenderer,
  scatter_xy: ScatterXyRenderer,
  contact_map: ContactMapRenderer,
  knee_plot: KneePlotRenderer,
  damage_profile: DamageProfileRenderer,
  genome_view: GenomeViewRenderer,
  group_compare: GroupCompareRenderer,
  transcript_structure: TranscriptStructureRenderer,
  cnv_profile: CnvProfileRenderer,
  genome_chord: GenomeChordRenderer,
  ideogram: IdeogramRenderer,
  record_card: RecordCardRenderer,
  parallel_coordinates: ParallelCoordinatesRenderer,
  ranked_distribution: RankedDistributionRenderer,
  molecule_3d: Molecule3DRenderer,
  msa: MsaRenderer,
  sequence_track: SequenceTrackRenderer,
  hmm_logo: HmmLogoRenderer,
  secondary_structure: SecondaryStructureRenderer,
  domain_architecture: DomainArchitectureRenderer,
  pae_matrix: PaeMatrixRenderer,
  ramachandran: RamachandranRenderer,
  spatial_cells: SpatialCellsRenderer,
  allele_grid: AlleleGridRenderer,
};

/**
 * Per-component sub-renderer for the advanced_viz family.
 *
 * Split into its own module (rather than living inline in ComponentRenderer)
 * so the whole advanced_viz family — all ~17 plotly-heavy renderers plus the
 * ag-grid the data popover in AdvancedVizExtras pulls in — is `React.lazy`'d
 * from ComponentRenderer as a single async chunk. A dashboard with no
 * advanced_viz component never loads any of it.
 *
 * Holds the payload the framed renderer publishes via
 * AdvancedVizExtrasContext, and turns it into the Settings + Show-data
 * popovers. Those are appended to the standard chrome icons (metadata +
 * fullscreen + reset) via the `extraActions` slot so all the action icons land
 * in the same hover-revealed row with matching Mantine styling.
 *
 * The same payload is forwarded to the app's inspector when one is mounted, so
 * the docked panel can present the identical controls and data. Both surfaces
 * read one payload — the popovers keep working unchanged with the inspector
 * off, which is what makes the feature safe to ship behind a flag.
 */
const AdvancedVizDispatch: React.FC<AdvancedVizDispatchProps> = ({
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  extraActions,
  showDragHandle,
  sourceLink,
  groupRender,
}) => {
  const [published, setPublished] = React.useState<AdvancedVizExtrasPayload | null>(null);
  // Where a `popover` tile docks its controls (`controls_placement` on the
  // component, see controlsDock.ts); null when the author left it unsaid.
  // A linked view cell has little room: unless the author placed them, its
  // controls stay behind the settings icon of the hover row, whose popover
  // heads them with the usual placement picker (popover, rail, under the
  // title). Everywhere else an unsaid placement docks where it fits.
  const compact = useDensity() === 'compact';
  const ownDock = isControlsPlacement(metadata.controls_placement)
    ? metadata.controls_placement
    : null;
  const dockPlacement = ownDock ?? (compact ? 'popover' : null);
  const [folded, setFolded] = React.useState(() => readFolded(String(metadata.index ?? '')));
  const toggleFolded = React.useCallback(() => {
    setFolded((f) => {
      writeFolded(String(metadata.index ?? ''), !f);
      return !f;
    });
  }, [metadata.index]);

  // Forward to the inspector, when the app mounted one. Keyed by component so
  // the panel can show whichever component is selected.
  const publishToInspector = useAdvancedVizInspector();
  React.useEffect(() => {
    if (!publishToInspector) return;
    publishToInspector(metadata.index, published);
    return () => publishToInspector(metadata.index, null);
  }, [publishToInspector, metadata.index, published]);

  // Where this tile's controls are drawn: its own config wins, the
  // dashboard-level default applies when it says nothing, `popover` (today's
  // behaviour) is the floor. Resolved here rather than in the frame because
  // this is the component that holds the metadata and the config sink, and
  // because the popover content depends on the same answer.
  const dashboardPlacement = useAdvancedVizPlacementDefault();
  const storedPlacement = resolveControlsPlacement(metadata.config, dashboardPlacement);
  // The pin is a view control everywhere and an authoring control where a
  // config sink is mounted: local state moves the controls immediately, and
  // `useVizConfigWriter` persists the same value on the surfaces that own the
  // component's config (the editor, the builder preview). Dropped as soon as
  // the stored value catches up, so a saved placement is read from one place.
  const [placementOverride, setPlacementOverride] = React.useState<ControlsPlacement | null>(
    null,
  );
  React.useEffect(() => setPlacementOverride(null), [storedPlacement]);
  const placement = placementOverride ?? storedPlacement;
  const writeConfig = useVizConfigWriter(metadata);
  const setPlacement = React.useCallback(
    (next: ControlsPlacement) => {
      setPlacementOverride(next);
      writeConfig({ controls_placement: next });
    },
    [writeConfig],
  );
  const placementState = React.useMemo<ControlsPlacementState>(
    () => ({ placement, setPlacement }),
    [placement, setPlacement],
  );
  // The region a `genome_selection` filter carries into this tile, echoed under
  // its title. The dispatch is the only place that sees the dashboard filters.
  const regionEcho = React.useMemo(() => genomeRegionEcho(filters), [filters]);

  // Rebuild the popovers from the payload — byte-for-byte what the frame used
  // to publish ready-made, minus whatever the tile now draws inline.
  const popovers = React.useMemo<React.ReactNode>(() => {
    if (!published) return null;
    const nodes: React.ReactNode[] = [];
    if (published.zoomSync) {
      nodes.push(<AdvancedVizZoomSyncToggle key="zoom-sync" index={String(metadata.index)} />);
    }
    // `rail` draws both tiers in the tile, so there is nothing left to open;
    // `header` draws the encoding tier and leaves the cosmetic one here.
    const popoverControls =
      placement === 'rail' ? null : placement === 'header' ? (
        published.controls
      ) : published.primaryControls && published.controls ? (
        <>
          {published.primaryControls}
          {published.controls}
        </>
      ) : (
        published.primaryControls ?? published.controls
      );
    if (popoverControls) {
      // Docked beside or above the plot (a `popover` tile with room for it),
      // the controls are already on screen: the icon folds them away instead.
      nodes.push(
        published.docked ? (
          <AdvancedVizDockToggle key="settings" open={!folded} onToggle={toggleFolded} />
        ) : (
          <AdvancedVizSettingsPopover
            key="settings"
            controls={popoverControls}
            headerAction={<ControlsPlacementPicker state={placementState} />}
          />
        ),
      );
    }
    if (published.data) {
      nodes.push(
        <AdvancedVizDataPopover
          key="data"
          dataRows={published.data.rows}
          dataColumns={published.data.columns}
          tierAnnotation={published.data.tierAnnotation}
        />,
      );
    }
    if (published.reduction) {
      nodes.push(<LoadAllButton key="load-all" state={published.reduction} />);
    }
    // Data and reduction stay in the chrome whatever the placement: they are
    // about the rows behind the figure, not about how it is drawn. Where the
    // controls live is picked in the header of the controls block itself
    // (popover, strip or rail), not from a separate chrome icon.
    return nodes.length ? <>{nodes}</> : null;
  }, [published, placement, placementState, folded, toggleFolded, metadata.index]);

  const vizKind = (metadata.viz_kind as string) || '';
  const kindLabel = vizKindLabel(vizKind);
  const Renderer = RENDERERS[vizKind];
  // "Split" is one component per group, each built from that group's rows;
  // see SplitPanels for why it is not a cut through the finished figure.
  // Panels are read-only: a lasso inside one would be a selection over an
  // already-narrowed frame, which is not what saving a group means.
  // Panels that turn out to hold identical data mean the group filter found
  // nothing to narrow here — a volcano keyed per taxon has no sample column to
  // match on. Remembered per component so the whole view is drawn once and
  // does not oscillate.
  const [splitIneffective, setSplitIneffective] = React.useState(false);
  // `filters` is a fresh array on every render, so memoise on the panel set's
  // content rather than its identity: an unstable `panels` would re-run every
  // panel's fetch and clear the flag below on each render.
  const panelKey = JSON.stringify(panelsForGrouping(groupRender, filters));
  const panels = React.useMemo(() => JSON.parse(panelKey) as PanelSpec[], [panelKey]);
  React.useEffect(() => setSplitIneffective(false), [metadata.dc_id, panelKey]);
  const split = Boolean(Renderer) && !splitIneffective && shouldSplitIntoPanels(panels, vizKind);
  const handleIneffective = React.useCallback(() => setSplitIneffective(true), []);
  // Split into panels, each would dock its own copy of the controls: they
  // stay behind the icon instead.
  const dockState = React.useMemo<ControlsDockState>(
    () => ({ placement: split ? 'popover' : dockPlacement, collapsed: folded }),
    [split, dockPlacement, folded],
  );
  // A kind that takes the groups neither as panels nor as colour (see
  // `groupingModeForKind`). Only a Split display asks the question: in the
  // colour overlay every kind is drawn whole with the groups, as before.
  const kindDeclinesSplit =
    groupRender?.display === 'facet' && groupingModeForKind(vizKind) === 'none';
  // Not handed the groups either, so the tile matches its badge: a renderer
  // that could still colour on its own would otherwise contradict it.
  const wholeGroupRender = kindDeclinesSplit ? undefined : groupRender;

  // What the renderer drawn whole reported after recolouring its figure by the
  // groups (see `useReportGroupColouring`): whether any point belonged to one.
  // Dropped when the dataset or the panel set changes, like `splitIneffective`,
  // but by tagging the report with both rather than resetting it from an
  // effect: the renderer's own report effect runs first in the same commit, so
  // a reset after it would erase the fresh answer. A new key also hands the
  // renderer a new callback, which is what makes it report again.
  const colouringKey = `${metadata.dc_id}|${panelKey}`;
  const [colouring, setColouring] = React.useState<{ key: string; matched: boolean | null }>({
    key: colouringKey,
    matched: null,
  });
  const reportColouring = React.useCallback(
    (matched: boolean | null) =>
      setColouring((prev) =>
        prev.key === colouringKey && prev.matched === matched ? prev : { key: colouringKey, matched },
      ),
    [colouringKey],
  );
  const colouringMatched = colouring.key === colouringKey ? colouring.matched : null;

  // Saying so when the groups do not reach this component. A split that came
  // back identical in every panel falls back to the whole render above, which
  // on its own looks exactly like a component that ignores grouping, and so
  // does a kind that is never split, or a whole render whose recolour matched
  // no point. The badge is the figure's "not grouped", handed to the frame
  // through context, with the reason that applies.
  //
  // What the Analysis panel pools comes out of the same decision: a drawing
  // split counts as reached until it proves ineffective, a kind that is never
  // split never counts, and a whole render counts as its recolour reported.
  // Only a renderer that reports nothing falls back to vouching for groups
  // drawn on its own dataset.
  const groupsActive = groupColouringActive(groupRender);
  const drawnHere =
    groupsActive &&
    (groupRender?.groups ?? []).some((g) => Boolean(g.dc_id) && g.dc_id === metadata.dc_id);
  const groupOutcome = advancedVizGroupOutcome({
    groupsActive,
    split,
    declinedByKind: kindDeclinesSplit,
    splitIneffective,
    coloured: colouringMatched,
    drawnHere,
  });
  const groupBadge = React.useMemo(
    () =>
      groupOutcome.badge ? (
        <GroupStatusBadge
          label="not grouped"
          colored={false}
          reasons={NOT_GROUPED_REASONS[groupOutcome.badge]()}
        />
      ) : null,
    [groupOutcome.badge],
  );
  useReportGroupReach(metadata.index, groupOutcome.reach);
  // Memoised so that `published` changing — which is this component's own
  // state, and says nothing about what the renderer should draw — hands React
  // the same element and it skips the whole subtree. Without that, every
  // publish re-renders the renderer, several of which build their `controls`
  // JSX inline: a fresh node makes the frame's payload look new, so it
  // publishes again, and the two setStates chase each other until React gives
  // up. `filters` is a fresh array per parent render, but it is stable across
  // the re-renders this is defending against, which is the point.
  const inner = React.useMemo(
    () =>
      !Renderer ? (
        <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
          Unknown advanced viz kind: "{vizKind}"
        </div>
      ) : split ? (
        <SplitPanels
          panels={panels}
          filters={filters}
          onIneffective={handleIneffective}
          renderPanel={(panelFilters, key) => (
            <Renderer
              key={key}
              metadata={metadata}
              filters={panelFilters}
              refreshTick={refreshTick}
            />
          )}
        />
      ) : (
        <Renderer
          metadata={metadata}
          filters={filters}
          refreshTick={refreshTick}
          onFilterChange={onFilterChange}
          groupRender={wholeGroupRender}
        />
      ),
    [
      Renderer,
      vizKind,
      split,
      panels,
      filters,
      handleIneffective,
      metadata,
      refreshTick,
      onFilterChange,
      wholeGroupRender,
    ],
  );

  // The tile's own selection (a lasso, a pick, a genome brush), read back from
  // the dashboard filters so the chrome can offer the same clear action a
  // table or a scatter figure has. Each renderer already undims itself when
  // its entry leaves the filters (see `useSelectionRevision`), so clearing the
  // filter is also what clears the picture. A genome view's opening region
  // (`default_region`) is not the reader's selection and does not count.
  const own = React.useMemo(
    () =>
      withoutDefaultRegion(
        ownSelection(filters, metadata.index),
        metadata.index,
        defaultRegionKey(metadata.index),
      ),
    [filters, metadata.index],
  );
  const onResetSelection =
    onFilterChange && own.filters.length > 0
      ? () => {
          const cleared = clearedSelectionFilters(own.filters);
          traceGenome(String(metadata.index), 'tile reset: own selection cleared', describeFilters(cleared));
          for (const filter of cleared) onFilterChange(filter);
        }
      : undefined;

  // "Open in genome browser": on a genomic tile that says where it is looking,
  // when the family has a browser (the button hides itself otherwise). Built
  // here rather than in `popovers` because it reads the dashboard filters.
  const openInBrowser = published?.openLocus ? (
    <OpenInGenomeBrowserButton
      key="open-genome-browser"
      reader={published.openLocus}
      vizKind={vizKind}
      config={metadata.config}
      index={String(metadata.index)}
      filters={filters}
    />
  ) : null;
  const combinedExtras = popovers || openInBrowser || extraActions ? (
    <>
      {popovers}
      {openInBrowser}
      {extraActions}
    </>
  ) : undefined;

  // The `minimal` style's card header, resolved once for the frame (see
  // advancedVizShowcase.ts). Null in the default style, which leaves every
  // renderer's frame exactly as it was.
  const resolveTab = useTabLinkResolver();
  const linkedTab = tabLinkName(metadata.link);
  const sourceTab = sourceLink ?? (linkedTab ? (resolveTab?.(linkedTab) ?? null) : null);
  const caption = typeof metadata.caption === 'string' ? metadata.caption.trim() : '';
  const showcase = React.useMemo(
    () => advancedVizShowcase(metadata, sourceTab),
    [
      metadata.figure_style,
      metadata.subtitle,
      metadata.icon_name,
      metadata.icon_color,
      sourceTab?.href,
      sourceTab?.label,
      sourceTab?.icon,
      sourceTab?.color,
    ],
  );

  return wrapWithChrome(
    'advanced_viz',
    metadata,
    undefined,
    <AdvancedVizExtrasProvider onChange={setPublished}>
      <ComponentIndexContext.Provider value={metadata.index}>
        <GroupStatusBadgeContext.Provider value={groupBadge}>
          <GroupColouringReportContext.Provider value={reportColouring}>
            <AdvancedVizShowcaseContext.Provider value={showcase}>
              <AdvancedVizCaptionContext.Provider value={caption}>
                <ControlsPlacementContext.Provider value={placementState}>
                  <ControlsDockContext.Provider value={dockState}>
                    <AdvancedVizKindContext.Provider value={kindLabel}>
                      <AdvancedVizRegionEchoContext.Provider value={regionEcho}>
                        <HideLegendContext.Provider value={Boolean(metadata.hide_legend)}>
                          {inner}
                        </HideLegendContext.Provider>
                      </AdvancedVizRegionEchoContext.Provider>
                    </AdvancedVizKindContext.Provider>
                  </ControlsDockContext.Provider>
                </ControlsPlacementContext.Provider>
              </AdvancedVizCaptionContext.Provider>
            </AdvancedVizShowcaseContext.Provider>
          </GroupColouringReportContext.Provider>
        </GroupStatusBadgeContext.Provider>
      </ComponentIndexContext.Provider>
    </AdvancedVizExtrasProvider>,
    {
      extraActions: combinedExtras,
      showDragHandle,
      onResetFilter: onResetSelection,
      sourceFilterActive: own.filters.length > 0,
      selectionCount: own.count,
    },
  );
};

export default AdvancedVizDispatch;

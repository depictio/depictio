import React from 'react';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { wrapWithChrome } from '../chrome';
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
import {
  AdvancedVizDataPopover,
  AdvancedVizDockToggle,
  AdvancedVizExtrasProvider,
  AdvancedVizSettingsPopover,
} from './AdvancedVizExtras';
import { ControlsDockContext, isControlsPlacement } from './controlsDock';
import type { ControlsDockState } from './controlsDock';
import type { AdvancedVizExtrasPayload } from './AdvancedVizExtras';
import { useAdvancedVizInspector } from './AdvancedVizInspectorBridge';
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
import { advancedVizChromeReset, isSourceFilterActive } from '../../selection';
import { useTabLinkResolver } from '../tabLinks';
import {
  AdvancedVizShowcaseContext,
  advancedVizShowcase,
  tabLinkName,
} from './advancedVizShowcase';

/** The hover line behind each way an advanced viz ends up "not grouped". */
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
  /** Dashboard-wide analysis grouping. Renderers whose points map one-to-one
   *  onto rows apply it to their finished figure with `splitFigureByGroups`;
   *  the aggregating ones (UpSet, sunburst, stacked taxonomy) ignore it,
   *  because a group cannot be attributed to a bar that is already a sum. */
  groupRender?: GroupRenderState;
}

/**
 * `viz_kind` → renderer. Every renderer takes the same
 * `{ metadata, filters, refreshTick, onFilterChange?, groupRender? }` props, so the dispatch
 * is a lookup rather than a chain of comparisons. `ancombc_differentials` was collapsed
 * into `da_barplot` — legacy persisted dashboards still carry the old kind
 * string and need the same renderer.
 */
const RENDERERS: Record<string, React.ComponentType<any>> = {
  volcano: VolcanoRenderer,
  embedding: EmbeddingRenderer,
  manhattan: ManhattanRenderer,
  stacked_taxonomy: StackedTaxonomyRenderer,
  phylogenetic: PhylogeneticRenderer,
  rarefaction: RarefactionRenderer,
  da_barplot: DaBarplotRenderer,
  ancombc_differentials: DaBarplotRenderer,
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
  groupRender,
}) => {
  const [published, setPublished] = React.useState<AdvancedVizExtrasPayload | null>(null);
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

  // Rebuild the popovers from the payload — byte-for-byte what the frame used
  // to publish ready-made.
  const popovers = React.useMemo<React.ReactNode>(() => {
    if (!published) return null;
    const nodes: React.ReactNode[] = [];
    if (published.controls) {
      nodes.push(
        published.docked ? (
          <AdvancedVizDockToggle key="settings" open={!folded} onToggle={toggleFolded} />
        ) : (
          <AdvancedVizSettingsPopover key="settings" controls={published.controls} />
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
    return nodes.length ? <>{nodes}</> : null;
  }, [published, folded, toggleFolded]);

  const vizKind = (metadata.viz_kind as string) || '';
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
  const placement = isControlsPlacement(metadata.controls_placement)
    ? metadata.controls_placement
    : null;
  const dockState = React.useMemo<ControlsDockState>(
    () => ({ placement: split ? 'popover' : placement, collapsed: folded }),
    [split, placement, folded],
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

  const combinedExtras = popovers || extraActions ? (
    <>
      {popovers}
      {extraActions}
    </>
  ) : undefined;

  // "Reset selection", for a kind that draws its selection from the filter
  // list (see `advancedVizChromeReset`); the same action and the same
  // persistent orange state a scatter figure's lasso gets.
  const onResetSelection =
    onFilterChange && advancedVizChromeReset(metadata)
      ? () => onFilterChange({ index: metadata.index, value: [], source: 'scatter_selection' })
      : undefined;
  const sourceFilterActive = isSourceFilterActive(filters, metadata.index, 'scatter_selection');
  // The `minimal` style's card header, resolved once for the frame (see
  // advancedVizShowcase.ts). Null in the default style, which leaves every
  // renderer's frame exactly as it was.
  const resolveTab = useTabLinkResolver();
  const linkedTab = tabLinkName(metadata.link);
  const sourceTab = linkedTab ? (resolveTab?.(linkedTab) ?? null) : null;
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
              <ControlsDockContext.Provider value={dockState}>{inner}</ControlsDockContext.Provider>
            </AdvancedVizShowcaseContext.Provider>
          </GroupColouringReportContext.Provider>
        </GroupStatusBadgeContext.Provider>
      </ComponentIndexContext.Provider>
    </AdvancedVizExtrasProvider>,
    { extraActions: combinedExtras, showDragHandle, onResetFilter: onResetSelection, sourceFilterActive },
  );
};

export default AdvancedVizDispatch;

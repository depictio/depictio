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
import {
  AdvancedVizDataPopover,
  AdvancedVizExtrasProvider,
  AdvancedVizSettingsPopover,
} from './AdvancedVizExtras';
import type { AdvancedVizExtrasPayload } from './AdvancedVizExtras';
import { useAdvancedVizInspector } from './AdvancedVizInspectorBridge';
import LoadAllButton from '../chrome/LoadAllButton';
import { ComponentIndexContext } from '../DashboardLoadingProvider';
import type { GroupRenderState } from '../../selectionGroups';
import SplitPanels, { shouldSplitIntoPanels } from './SplitPanels';
import { panelsForGrouping } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';

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
      nodes.push(<AdvancedVizSettingsPopover key="settings" controls={published.controls} />);
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
  }, [published]);

  const vizKind = (metadata.viz_kind as string) || '';
  const Renderer = RENDERERS[vizKind];
  // "Split" is one component per group, each built from that group's rows —
  // see GroupSplitPanels for why it is not a cut through the finished figure.
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
  const inner = !Renderer ? (
    <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
      Unknown advanced viz kind: "{vizKind}"
    </div>
  ) : split ? (
    <SplitPanels
      panels={panels}
      filters={filters}
      onIneffective={() => setSplitIneffective(true)}
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
      groupRender={groupRender}
    />
  );

  const combinedExtras = popovers || extraActions ? (
    <>
      {popovers}
      {extraActions}
    </>
  ) : undefined;

  return wrapWithChrome(
    'advanced_viz',
    metadata,
    undefined,
    <AdvancedVizExtrasProvider onChange={setPublished}>
      <ComponentIndexContext.Provider value={metadata.index}>
        {inner}
      </ComponentIndexContext.Provider>
    </AdvancedVizExtrasProvider>,
    { extraActions: combinedExtras, showDragHandle },
  );
};

export default AdvancedVizDispatch;

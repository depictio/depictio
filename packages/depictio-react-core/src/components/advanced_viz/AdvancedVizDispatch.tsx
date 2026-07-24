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
import { AdvancedVizExtrasProvider } from './AdvancedVizExtras';
import { ComponentIndexContext } from '../DashboardLoadingProvider';

interface AdvancedVizDispatchProps {
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
  extraActions?: React.ReactNode;
  showDragHandle?: boolean;
}

/**
 * `viz_kind` → renderer. Every renderer takes the same
 * `{ metadata, filters, refreshTick }` props, so the dispatch is a lookup
 * rather than a chain of comparisons. `ancombc_differentials` was collapsed
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
 * Holds a useState for the Settings + Show-data popovers the framed renderer
 * publishes via AdvancedVizExtrasContext. The published JSX is appended to
 * the standard chrome icons (metadata + fullscreen + reset) via the
 * `extraActions` slot so all the action icons land in the same hover-revealed
 * row with matching Mantine styling.
 */
const AdvancedVizDispatch: React.FC<AdvancedVizDispatchProps> = ({
  metadata,
  filters,
  refreshTick,
  extraActions,
  showDragHandle,
}) => {
  const [publishedExtras, setPublishedExtras] = React.useState<React.ReactNode>(null);

  const vizKind = (metadata.viz_kind as string) || '';
  const Renderer = RENDERERS[vizKind];
  const inner = Renderer ? (
    <Renderer metadata={metadata} filters={filters} refreshTick={refreshTick} />
  ) : (
    <div className="dashboard-error" style={{ fontSize: '0.75rem' }}>
      Unknown advanced viz kind: "{vizKind}"
    </div>
  );

  const combinedExtras = publishedExtras || extraActions ? (
    <>
      {publishedExtras}
      {extraActions}
    </>
  ) : undefined;

  return wrapWithChrome(
    'advanced_viz',
    metadata,
    undefined,
    <AdvancedVizExtrasProvider onChange={setPublishedExtras}>
      <ComponentIndexContext.Provider value={metadata.index}>
        {inner}
      </ComponentIndexContext.Provider>
    </AdvancedVizExtrasProvider>,
    { extraActions: combinedExtras, showDragHandle },
  );
};

export default AdvancedVizDispatch;

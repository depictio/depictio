/**
 * Seed depictio's builder store (imported via the depictio-builder alias) from
 * the in-memory fixture so the reused control panels work with no backend:
 *  - `cols` from the parsed fixture (+ precomputed specs for CardPreview);
 *  - `figureVisualizationList` + `figureParamSpecs` from the committed
 *    figureParams.json snapshot, so FigureUIMode renders its accordion offline
 *    (it only fetches on a store-cache miss).
 *
 * The viz list is restricted to the types the catalog `visu_type` enum accepts
 * (scatter/line/bar/box/histogram — heatmap has no plotly-express builder viz),
 * so the user can't author a figure the catalog can't express.
 */
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import type { ComponentType } from 'depictio-builder/store/useBuilderStore';
import type { ParsedFixture } from '../types';
import { fixtureToColumnSpecs } from './columnSpecs';

/** Catalog `visu_type` enum ∩ plotly-express builder visualizations. */
export const CATALOG_FIGURE_TYPES = ['scatter', 'line', 'bar', 'box', 'histogram'];

interface FigureParamsSnapshot {
  visualizations: Array<{ name: string; label: string; description: string; icon: string; group: string }>;
  params: Record<string, unknown>;
}

let snapshotPromise: Promise<FigureParamsSnapshot> | null = null;

function loadFigureParams(): Promise<FigureParamsSnapshot> {
  if (!snapshotPromise) {
    snapshotPromise = fetch(`${import.meta.env.BASE_URL}figureParams.json`)
      .then((r) => r.json())
      .catch(() => {
        // Degrade gracefully (builder opens with an empty viz list) but clear
        // the memo so a failed one-time fetch retries on the next seed instead
        // of poisoning the whole session.
        snapshotPromise = null;
        return { visualizations: [], params: {} };
      });
  }
  return snapshotPromise;
}

/** Reset + seed the store for a fresh "add component" session. */
export async function seedBuilderStore(
  fixture: ParsedFixture,
  componentType: ComponentType,
): Promise<void> {
  const cols = fixtureToColumnSpecs(fixture);
  const snap = await loadFigureParams();

  const vizList = snap.visualizations.filter((v) => CATALOG_FIGURE_TYPES.includes(v.name));
  const paramSpecs: Record<string, unknown> = {};
  for (const t of CATALOG_FIGURE_TYPES) {
    if (snap.params[t]) paramSpecs[t] = snap.params[t];
  }
  const firstViz = vizList.some((v) => v.name === 'scatter') ? 'scatter' : vizList[0]?.name || 'scatter';

  useBuilderStore.getState().reset();
  useBuilderStore.setState({
    mode: 'create',
    dashboardId: 'tool-studio',
    componentId: 'render',
    // Dummy binding ids so `ready`/preview guards pass; no network uses them.
    wfId: 'fixture',
    dcId: 'fixture',
    projectId: 'tool-studio',
    dcConfigType: 'table',
    cols,
    componentType,
    config: {},
    visuType: firstViz,
    dictKwargs: {},
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    figureVisualizationList: vizList as any,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    figureParamSpecs: paramSpecs as any,
    previewReady: true,
  });
}

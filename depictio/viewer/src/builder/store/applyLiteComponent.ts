/**
 * One mapping from a validated lite component dict to builder-store state.
 *
 * Two producers hand the builder a component that was not typed in by hand:
 * the AI (`/ai/component-from-prompt`, the Describe step and the "Refine with
 * AI" modal) and the catalog (`CatalogTab`, through its own render shape).
 * Both used to hydrate the store with their own copy of the per-type rules,
 * and the copies drifted: the AI path synced figure fields only, so an
 * advanced_viz answer never reached the binding form. Everything that is not
 * a plain `patchConfig` lives here now, so a catalog match and an AI answer
 * land in the builder the same way.
 *
 * The dict is the lite-model shape (`depictio/models/models/dashboards/lite.py`),
 * which is also what `to_full` stores, so field names already match what the
 * per-type builders read from `config`.
 */
import { rolesFromConfigBlob } from '../advanced_viz/configBlob';
import { useBuilderStore } from './useBuilderStore';
import type { FigureMode } from './useBuilderStore';

type Dict = Record<string, unknown>;
type BuilderStore = ReturnType<typeof useBuilderStore.getState>;

/** Builder config for an advanced_viz from the stored/server shape: `viz_kind`
 *  plus a grounded `config` blob with `<role>_col` keys. The builder keeps the
 *  bindings as a flat `column_mapping` and the blob as `preset_config`, so
 *  the non-role viz controls ride along untouched (see buildMetadata). Declared
 *  `roles`, when a caller has them, win over what the blob implies. */
export function advancedVizConfig(
  vizKind: string | null | undefined,
  blob: Dict | null | undefined,
  roles?: Record<string, string | string[]> | null,
): Dict {
  return {
    viz_kind: vizKind ?? null,
    column_mapping: {
      ...rolesFromConfigBlob(vizKind ?? undefined, blob),
      ...(roles ?? {}),
    },
    preset_config: blob ?? null,
  };
}

/** Sync the figure's top-level store fields from a lite figure dict. Leaves
 *  `figureMode` alone when `mode` is absent: a partial AI revision must not
 *  flip the user out of the editing mode they are in. */
function syncFigureFields(parsed: Dict, store: BuilderStore): void {
  const mode = parsed.mode as FigureMode | undefined;
  if (mode === 'code' || mode === 'ui') store.setFigureMode(mode);
  if (typeof parsed.visu_type === 'string') store.setVisuType(parsed.visu_type);
  if (parsed.dict_kwargs && typeof parsed.dict_kwargs === 'object') {
    store.patchDictKwargs(parsed.dict_kwargs as Dict);
  }
  if (typeof parsed.code_content === 'string') store.setCodeContent(parsed.code_content);
}

/** Hydrate the builder from a validated lite component dict of the type the
 *  store currently holds. `component_type` in the dict is informational; the
 *  store's `componentType` decides which rules apply, because the Describe
 *  step and the AI-fill modal both ask the model for the type on screen. */
export function applyLiteComponent(
  parsed: Dict,
  store: BuilderStore = useBuilderStore.getState(),
): void {
  if (store.componentType === 'advanced_viz') {
    const { config, viz_kind, ...rest } = parsed;
    store.patchConfig({
      ...rest,
      ...advancedVizConfig(
        typeof viz_kind === 'string' ? viz_kind : null,
        config && typeof config === 'object' ? (config as Dict) : null,
      ),
    });
    return;
  }
  store.patchConfig(parsed);
  if (store.componentType === 'figure') syncFigureFields(parsed, store);
}

/**
 * Translates the in-flight builder state into a persisted stored_metadata
 * dict matching the canonical schemas under depictio/models/components/.
 *
 * Each per-type branch produces exactly the keys that the corresponding
 * `save_*_to_dashboard()` helper in depictio/dash/modules/* writes today,
 * so no Pydantic validation regressions on POST /dashboards/save.
 */
import type { StoredMetadata } from 'depictio-react-core';
import { readMultiqcSelection } from 'depictio-react-core';
import type { BuilderState } from './store/useBuilderStore';
import { autoCardTitle } from './card/cardTitle';

/** Augment an unknown record with type-narrowing safety. */
function as<T extends Record<string, unknown>>(v: unknown): T {
  return (v || {}) as T;
}

export function buildMetadata(state: BuilderState): StoredMetadata {
  const base: StoredMetadata = {
    index: state.componentId!,
    component_type: state.componentType!,
    wf_id: state.wfId || undefined,
    dc_id: state.dcId || undefined,
    project_id: state.projectId || undefined,
    last_updated: new Date().toISOString(),
  };
  // For edit mode, preserve any existing keys we don't explicitly set
  // (e.g. parent_index, panel, dc_config caches).
  const existing = state.existing ? { ...state.existing } : {};

  switch (state.componentType) {
    case 'card':
      return buildCard(state, base, existing);
    case 'figure':
      return buildFigure(state, base, existing);
    case 'interactive':
      return buildInteractive(state, base, existing);
    case 'table':
      return buildTable(state, base, existing);
    case 'multiqc':
      return buildMultiqc(state, base, existing);
    case 'image':
      return buildImage(state, base, existing);
    case 'map':
      return buildMap(state, base, existing);
    default:
      return { ...existing, ...base };
  }
}

// ---- per-type --------------------------------------------------------------

function buildCard(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  const c = as<{
    title?: string;
    column_name?: string;
    column_type?: string;
    aggregation?: string;
    background_color?: string;
    title_color?: string;
    icon_name?: string;
    title_font_size?: string;
  }>(state.config);
  const title =
    (c.title && c.title.trim()) ||
    autoCardTitle(c.aggregation, c.column_name, c.column_type);
  return {
    ...existing,
    ...base,
    title,
    column_name: c.column_name,
    column_type: c.column_type,
    aggregation: c.aggregation,
    background_color: c.background_color || '',
    title_color: c.title_color || '',
    icon_name: c.icon_name || 'mdi:chart-line',
    title_font_size: (c.title_font_size as 'xs' | 'sm' | 'md' | 'lg' | 'xl') || 'md',
  };
}

function buildFigure(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  // Cross-filtering toggle lives on the figure config (not dict_kwargs) since
  // it applies to both UI and code modes — keys match the renderer's reads in
  // packages/depictio-react-core/src/components/ComponentRenderer.tsx
  // (selection_enabled / scatter_selection source).
  const c = as<{
    selection_enabled?: boolean;
    selection_column?: string;
  }>(state.config);
  if (state.figureMode === 'code') {
    return {
      ...existing,
      ...base,
      mode: 'code',
      code_content: state.codeContent,
      visu_type: state.visuType, // hint for renderers
      // dict_kwargs intentionally cleared in code mode
      dict_kwargs: {},
      selection_enabled: Boolean(c.selection_enabled),
      selection_column: c.selection_column,
    };
  }
  return {
    ...existing,
    ...base,
    mode: 'ui',
    visu_type: state.visuType,
    dict_kwargs: state.dictKwargs,
    code_content: null,
    selection_enabled: Boolean(c.selection_enabled),
    selection_column: c.selection_column,
  };
}

function buildInteractive(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  const c = as<{
    interactive_component_type?: string;
    column_name?: string;
    column_type?: string;
    title?: string;
    title_size?: string;
    color?: string;
    icon_name?: string;
  }>(state.config);
  // Mirror Dash design_interactive: the form surfaces only the basics, no
  // default value/range, marks, or scale. Those are derived at render time.
  const title =
    (c.title && c.title.trim()) ||
    (c.interactive_component_type && c.column_name
      ? `${c.interactive_component_type} on ${c.column_name}`
      : '');
  return {
    ...existing,
    ...base,
    interactive_component_type: c.interactive_component_type,
    column_name: c.column_name,
    column_type: c.column_type,
    title,
    title_size: c.title_size ?? 'md',
    color: c.color ?? '',
    icon_name: c.icon_name ?? 'bx:slider-alt',
  };
}

function buildTable(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  const c = as<{
    cols_json?: Record<string, unknown>;
    striped?: boolean;
    compact?: boolean;
    export_csv?: boolean;
    row_selection_enabled?: boolean;
    row_selection_column?: string;
  }>(state.config);
  return {
    ...existing,
    ...base,
    cols_json: c.cols_json ?? {},
    striped: c.striped ?? true,
    compact: c.compact ?? false,
    export_csv: c.export_csv ?? false,
    // Row selection drives `table_selection` filters in
    // packages/depictio-react-core/src/components/ComponentRenderer.tsx —
    // mirrors what map / figure do with `selection_enabled`.
    row_selection_enabled: Boolean(c.row_selection_enabled),
    row_selection_column: c.row_selection_column,
  };
}

function buildMultiqc(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  // Persist with `selected_*` keys — the backend's render_multiqc endpoint
  // and depictio.dash.modules.multiqc_component.models.MultiQCState read
  // `selected_module`/`selected_plot`/`selected_dataset`. Earlier the
  // builder used `multiqc_*` here, which silently produced 400s at render.
  const c = as<{ s3_locations?: string[]; is_general_stats?: boolean }>(state.config);
  const sel = readMultiqcSelection(state.config as Record<string, unknown>);
  return {
    ...existing,
    ...base,
    // `|| null` normalizes `undefined` to an explicit null so the wire
    // shape doesn't depend on JSON's `undefined`-stripping behavior.
    selected_module: sel.module || null,
    selected_plot: sel.plot || null,
    selected_dataset: sel.dataset || null,
    s3_locations: c.s3_locations || [],
    is_general_stats: Boolean(c.is_general_stats),
  };
}

function buildImage(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  const c = as<{
    image_column?: string;
    s3_base_folder?: string;
    title?: string;
  }>(state.config);
  return {
    ...existing,
    ...base,
    image_column: c.image_column,
    s3_base_folder: c.s3_base_folder,
    title: c.title ?? '',
  };
}

function buildMap(
  state: BuilderState,
  base: StoredMetadata,
  existing: Record<string, unknown>,
): StoredMetadata {
  // Schema mirrors MapLiteComponent (depictio/models/components/lite.py) and
  // what depictio/dash/modules/map_component/utils.py reads from trigger_data.
  const c = as<{
    map_type?: string;
    lat_column?: string;
    lon_column?: string;
    color_column?: string;
    size_column?: string;
    hover_columns?: string[];
    map_style?: string;
    opacity?: number;
    selection_enabled?: boolean;
    selection_column?: string;
    title?: string;
  }>(state.config);
  return {
    ...existing,
    ...base,
    map_type: c.map_type ?? 'scatter_map',
    lat_column: c.lat_column,
    lon_column: c.lon_column,
    color_column: c.color_column,
    size_column: c.size_column,
    hover_columns: c.hover_columns ?? [],
    map_style: c.map_style ?? 'carto-positron',
    opacity: typeof c.opacity === 'number' ? c.opacity : 1.0,
    selection_enabled: Boolean(c.selection_enabled),
    selection_column: c.selection_column,
    title: c.title ?? '',
  };
}

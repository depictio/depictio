/**
 * Catalog `RenderSpec` → depictio `StoredMetadata`.
 *
 * The Python mirror of this lives in `depictio/catalog/payload.py`
 * (`_render_meta` + the per-component branches of `build_payload`): both turn a
 * catalog render into the metadata depictio's renderers dispatch on. Keeping
 * the Studio on the same shape is what lets it preview a render with the real
 * `ComponentRenderer` instead of a lookalike.
 *
 * `wf_id` / `dc_id` are constants: the Studio has exactly one data collection,
 * the fixture, and the offline api shim answers every request from it.
 */
import { buildAdvancedVizConfigBlob } from 'depictio-builder/advanced_viz/configBlob';
import type { ComponentMetadata } from '../api/fixtureRegistry';
import { columnKind } from '../api/frame';
import type { ParsedFixture, RenderSpec } from '../types';

export const STUDIO_DASHBOARD_ID = 'tool-studio';
const STUDIO_WF_ID = 'fixture';
const STUDIO_DC_ID = 'fixture';

/** Icon accents depictio gives catalog preview cards, so a row of cards is not
 *  a row of identical grey tiles (`_CARD_ACCENTS` in payload.py). */
const CARD_ACCENTS = ['#45b8ac', '#6e8fdb', '#f0995a', '#b47cd0'];

export function metadataFromRender(
  render: RenderSpec,
  index: string,
  fixture: ParsedFixture,
  position = 0,
): ComponentMetadata {
  const base: ComponentMetadata = {
    index,
    component_type: render.component,
    wf_id: STUDIO_WF_ID,
    dc_id: STUDIO_DC_ID,
  };

  if (render.component === 'figure') {
    return {
      ...base,
      visu_type: render.visu_type ?? 'scatter',
      dict_kwargs: render.dict_kwargs ?? {},
      ...(render.code
        ? { mode: 'code', code_content: render.code, _previewFigure: render._previewFigure }
        : { mode: 'ui' }),
    };
  }

  if (render.component === 'card') {
    return {
      ...base,
      title: render.column,
      column_name: render.column,
      aggregation: render.aggregation,
      icon_name: 'mdi:chart-line',
      icon_color: CARD_ACCENTS[position % CARD_ACCENTS.length],
      // `aggregations: null` — not undefined — is the wire-level "no secondary
      // strip" signal the renderer reads.
      aggregations: render.aggregations?.length ? render.aggregations : null,
      secondary_layout: render.secondary_layout ?? 'vertical',
      breakdown_col: render.breakdown_col ?? null,
      top_n_count: render.top_n_count ?? null,
      coverage_max: render.coverage_max ?? null,
      threshold_value: render.threshold_value ?? null,
      threshold_direction: render.threshold_direction ?? null,
      threshold_warn: render.threshold_warn ?? null,
      attrition_cols: render.attrition_cols ?? [],
      trend_col: render.trend_col ?? null,
    };
  }

  if (render.component === 'table') {
    // The catalog states the visible columns; the renderer wants the bag of
    // per-column overrides, so everything unnamed is hidden.
    const cols_json = render.columns?.length
      ? Object.fromEntries(
          fixture.columns.map((c) => [c.name, { hide: !render.columns!.includes(c.name) }]),
        )
      : {};
    return {
      ...base,
      cols_json,
      page_size: render.page_size ?? 100,
      row_selection_enabled: Boolean(render.row_selection_enabled),
      row_selection_column: render.row_selection_column ?? null,
    };
  }

  if (render.component === 'interactive') {
    const column = fixture.columns.find((c) => c.name === render.column_name);
    return {
      ...base,
      interactive_component_type: render.interactive_type,
      column_name: render.column_name,
      column_type: column ? columnKind(column.dtype) : 'object',
    };
  }

  // advanced_viz — the role → config translation is depictio's own, so the
  // preview and the component depictio builds from this render agree.
  return {
    ...base,
    viz_kind: render.kind,
    config: buildAdvancedVizConfigBlob(render.kind, render.roles ?? {}),
  };
}

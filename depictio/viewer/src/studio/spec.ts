/**
 * The pivot "viz spec" — one neutral object, serialised two ways.
 *
 * - `toRenderSpec`   → a `Render`-native dict for POST /studio/render (preview).
 * - `toLiteComponent`→ a `DashboardDataLite` component dict for the dashboard export.
 *
 * (The catalogue serialisation — the same spec → a catalog `Render` in a
 * `renders_as` — is deferred with the rest of catalogue mode.)
 */

export type VizSpec =
  | { component: 'figure'; visu_type: string; dict_kwargs: Record<string, string> }
  | { component: 'card'; column: string; aggregation: string }
  | { component: 'table' }
  | {
      component: 'advanced_viz';
      kind: string;
      roles: Record<string, string>;
      config?: Record<string, unknown>;
    };

export interface CartItem {
  id: string;
  /** Relative path of the picked file this viz is built on. */
  file: string;
  /** Data-collection tag this viz binds to (one DC per picked file by default). */
  dcTag: string;
  label: string;
  spec: VizSpec;
}

/** Render-native dict for the preview engine (build_payload's `Render`). */
export function toRenderSpec(spec: VizSpec): Record<string, unknown> {
  switch (spec.component) {
    case 'figure':
      return { component: 'figure', visu_type: spec.visu_type, dict_kwargs: spec.dict_kwargs };
    case 'card':
      return { component: 'card', column: spec.column, aggregation: spec.aggregation };
    case 'table':
      return { component: 'table' };
    case 'advanced_viz':
      return { component: 'advanced_viz', kind: spec.kind, roles: spec.roles };
  }
}

/** DashboardDataLite component dict for the export. */
export function toLiteComponent(spec: VizSpec, dcTag: string): Record<string, unknown> {
  const base = { data_collection_tag: dcTag };
  switch (spec.component) {
    case 'figure':
      return {
        ...base,
        component_type: 'figure',
        visu_type: spec.visu_type,
        dict_kwargs: spec.dict_kwargs,
        mode: 'ui',
      };
    case 'card':
      return {
        ...base,
        component_type: 'card',
        aggregation: spec.aggregation,
        column_name: spec.column,
      };
    case 'table':
      return { ...base, component_type: 'table' };
    case 'advanced_viz':
      return {
        ...base,
        component_type: 'advanced_viz',
        viz_kind: spec.kind,
        ...(spec.config ? { config: spec.config } : {}),
      };
  }
}

/** A short human label for the cart / preview header. */
export function specLabel(spec: VizSpec): string {
  switch (spec.component) {
    case 'figure':
      return `${spec.visu_type} figure`;
    case 'card':
      return `${spec.aggregation}(${spec.column})`;
    case 'table':
      return 'table';
    case 'advanced_viz':
      return spec.kind;
  }
}

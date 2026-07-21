/**
 * Per-render display metadata, mirroring depictio's catalog-preview
 * `shared.tsx` COMPONENT_META + `payload.py` _render_variant / _render_binds,
 * so catalog-studio's visualization list looks like the Tools Catalog result
 * (same colors/icons, variant sublabel, and role→column "binds").
 */
import { FIGURE_COLUMN_KWARGS, type KindsMap, type RenderSpec } from '../types';

export interface ComponentMeta {
  name: string;
  color: string;
  icon: string;
}

// Colors/icons copied verbatim from viewer/src/catalog-preview/shared.tsx:24-37.
export const COMPONENT_META: Record<string, ComponentMeta> = {
  figure: { name: 'Figure', color: '#9966cc', icon: 'mdi:graph-box' },
  card: { name: 'Card', color: '#45b8ac', icon: 'formkit:number' },
  interactive: { name: 'Interactive', color: '#8bc34a', icon: 'bx:slider-alt' },
  table: { name: 'Table', color: '#6495ed', icon: 'octicon:table-24' },
  advanced_viz: { name: 'Advanced viz', color: '#f68b33', icon: 'mdi:chart-scatter-plot' },
};

export function metaFor(type: string): ComponentMeta {
  return COMPONENT_META[type] ?? { name: type, color: '#868e96', icon: 'mdi:shape-outline' };
}

/** The dimmed " · {variant}" sublabel shown next to the component name. */
export function variantOf(render: RenderSpec, kinds: KindsMap): string | undefined {
  switch (render.component) {
    case 'figure':
      return render.code ? 'code' : render.visu_type;
    case 'card':
      return render.aggregation;
    case 'advanced_viz':
      return kinds[render.kind]?.label ?? render.kind;
    default:
      return undefined;
  }
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

/** A sensible default render id (slugified) derived from the component + its
 *  key binding — editable afterwards, deduped on add. Mirrors the descriptive
 *  ids in real catalog entries (e.g. `average_coverage`, `volcano`). */
export function defaultRenderId(render: RenderSpec): string {
  switch (render.component) {
    case 'figure':
      return slug(render.code ? 'figure_code' : `figure_${render.visu_type ?? 'plot'}`);
    case 'card':
      return slug(`${render.aggregation}_${render.column}`);
    case 'advanced_viz':
      return slug(render.kind || 'advanced_viz');
    case 'interactive':
      return 'interactive';
    case 'table':
      return 'table';
    default:
      return 'render';
  }
}

/** Flat "label → column" bindings, mirroring payload.py _render_binds. */
export function bindsOf(render: RenderSpec): [string, string][] {
  switch (render.component) {
    case 'figure':
      return FIGURE_COLUMN_KWARGS.map((k) => [k, render.dict_kwargs?.[k]]).filter(
        (pair): pair is [string, string] => Boolean(pair[1]),
      );
    case 'card': {
      const binds: [string, string][] = [['column', render.column]];
      if (render.breakdown_col) binds.push(['breakdown', render.breakdown_col]);
      return binds;
    }
    case 'advanced_viz':
      return Object.entries(render.roles);
    default:
      return [];
  }
}

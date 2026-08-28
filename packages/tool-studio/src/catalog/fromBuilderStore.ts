/**
 * Translate depictio's builder store state into a catalog `RenderSpec` on
 * confirm. Reads the same fields depictio's own `buildMetadata.ts` reads
 * (visuType / dictKwargs / config.*), but emits the compact catalog render
 * instead of dashboard `StoredMetadata`. Every component type comes through
 * here now, advanced_viz included — the Studio no longer has a second authoring
 * path with its own state.
 */
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import {
  FIGURE_COLUMN_KWARGS,
  type Aggregation,
  type RenderSpec,
  type SecondaryLayout,
  type ThresholdDirection,
} from '../types';
import {
  SECONDARY_LAYOUTS,
  THRESHOLD_DIRECTIONS,
} from './generated/cardSpec';
import { nextUid } from '../state/useStudioStore';

/** Depictio card-method key → catalog aggregation enum. */
function normalizeAggregation(agg: string): Aggregation {
  return (agg === 'unique' ? 'nunique' : agg) as Aggregation;
}

/** The builder types these loosely; narrow against the generated enums so a
 *  layout depictio grows but the catalog doesn't accept can't reach the YAML. */
function asLayout(value: string): SecondaryLayout | undefined {
  return (SECONDARY_LAYOUTS as readonly string[]).includes(value)
    ? (value as SecondaryLayout)
    : undefined;
}

function asDirection(value: string): ThresholdDirection | undefined {
  return (THRESHOLD_DIRECTIONS as readonly string[]).includes(value)
    ? (value as ThresholdDirection)
    : undefined;
}

/** Stringify a dict_kwargs value (schema requires Dict[str, str]). */
function asStr(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'boolean' || typeof v === 'number') return String(v);
  return JSON.stringify(v);
}

/**
 * Build a RenderSpec from the current builder store. Returns null if the
 * required binding for the component type isn't set yet.
 */
export function renderSpecFromStore(): RenderSpec | null {
  const s = useBuilderStore.getState();
  const uid = nextUid();

  if (s.componentType === 'figure') {
    // Code mode → emit the inline snippet as the catalog `code` field (depictio
    // code_content); no visu_type/dict_kwargs bindings are needed.
    if (s.figureMode === 'code') {
      const code = (s.codeContent ?? '').trim();
      if (!code) return null;
      // Carry the executed plot (if any) for the list preview — not exported.
      const fig = s.lastCodeFigure;
      return { uid, component: 'figure', code, ...(fig ? { _previewFigure: fig } : {}) };
    }
    const dict_kwargs: Record<string, string> = {};
    for (const [k, v] of Object.entries(s.dictKwargs)) {
      if (v === '' || v == null) continue;
      dict_kwargs[k] = asStr(v);
    }
    // Need at least an x (or names) binding to be meaningful.
    const hasColumn = FIGURE_COLUMN_KWARGS.some((k) => dict_kwargs[k]);
    if (!hasColumn) return null;
    return {
      uid,
      component: 'figure',
      // visu_type is constrained to the catalog enum by the seeded viz list.
      visu_type: s.visuType as never,
      dict_kwargs,
    };
  }

  if (s.componentType === 'card') {
    // Key names match depictio's CardBuilder config bundle 1:1 (see
    // depictio/viewer/src/builder/card/CardBuilder.tsx) — the layout-specific
    // companions are what the catalog model requires per secondary_layout, so
    // dropping any of them here produced a card `dev catalog validate` rejects.
    const cfg = s.config as {
      column_name?: string;
      aggregation?: string;
      aggregations?: string[];
      secondary_layout?: string;
      breakdown_col?: string | null;
      top_n_count?: number;
      coverage_max?: number | null;
      threshold_value?: number | null;
      threshold_direction?: string;
      threshold_warn?: number | null;
      attrition_cols?: string[] | null;
      trend_col?: string | null;
    };
    if (!cfg.column_name || !cfg.aggregation) return null;
    return {
      uid,
      component: 'card',
      column: cfg.column_name,
      aggregation: normalizeAggregation(cfg.aggregation),
      ...(cfg.aggregations?.length
        ? { aggregations: cfg.aggregations.map(normalizeAggregation) }
        : {}),
      ...(cfg.secondary_layout ? { secondary_layout: asLayout(cfg.secondary_layout) } : {}),
      ...(cfg.breakdown_col ? { breakdown_col: cfg.breakdown_col } : {}),
      ...(typeof cfg.top_n_count === 'number' ? { top_n_count: cfg.top_n_count } : {}),
      ...(typeof cfg.coverage_max === 'number' ? { coverage_max: cfg.coverage_max } : {}),
      ...(typeof cfg.threshold_value === 'number'
        ? { threshold_value: cfg.threshold_value }
        : {}),
      ...(cfg.threshold_direction ? { threshold_direction: asDirection(cfg.threshold_direction) } : {}),
      ...(typeof cfg.threshold_warn === 'number' ? { threshold_warn: cfg.threshold_warn } : {}),
      ...(cfg.attrition_cols?.length ? { attrition_cols: [...cfg.attrition_cols] } : {}),
      ...(cfg.trend_col ? { trend_col: cfg.trend_col } : {}),
    };
  }

  if (s.componentType === 'interactive') {
    const cfg = s.config as {
      column_name?: string;
      interactive_component_type?: string;
    };
    // Both are required by `InteractiveLiteComponent`, so a render missing
    // either could not be instantiated on a dashboard.
    if (!cfg.column_name || !cfg.interactive_component_type) return null;
    return {
      uid,
      component: 'interactive',
      interactive_type: cfg.interactive_component_type as never,
      column_name: cfg.column_name,
    };
  }

  if (s.componentType === 'table') {
    const cfg = s.config as {
      cols_json?: Record<string, { hide?: boolean }>;
      page_size?: number;
      striped?: boolean;
      compact?: boolean;
      export_csv?: boolean;
      row_selection_enabled?: boolean;
      row_selection_column?: string | null;
    };
    // `cols_json` is the builder's per-column bag; the catalog states the
    // positive list, which is what a reader of the YAML can check against the
    // fixture. An all-visible table says nothing, which is the default anyway.
    const hidden = Object.entries(cfg.cols_json ?? {})
      .filter(([, v]) => v?.hide)
      .map(([name]) => name);
    const visible = hidden.length
      ? s.cols.map((c) => c.name).filter((name) => !hidden.includes(name))
      : [];
    return {
      uid,
      component: 'table',
      ...(visible.length ? { columns: visible } : {}),
      ...(typeof cfg.page_size === 'number' ? { page_size: cfg.page_size } : {}),
      ...(cfg.striped === false ? { striped: false } : {}),
      ...(cfg.compact ? { compact: true } : {}),
      ...(cfg.export_csv === false ? { export_csv: false } : {}),
      ...(cfg.row_selection_enabled
        ? {
            row_selection_enabled: true,
            ...(cfg.row_selection_column
              ? { row_selection_column: cfg.row_selection_column }
              : {}),
          }
        : {}),
    };
  }

  if (s.componentType === 'advanced_viz') {
    const cfg = s.config as {
      viz_kind?: string;
      column_mapping?: Record<string, string | string[]>;
    };
    if (!cfg.viz_kind) return null;
    // `Render.roles` carries both shapes the builder binds: one column per
    // role, and the ordered column LISTS a few kinds need (sankey steps,
    // sunburst ranks, ComplexHeatmap's value / annotation columns). Dropping
    // the lists — as this did while the model only accepted strings — exported
    // a sankey with no steps, which nothing downstream can infer.
    const roles: Record<string, string | string[]> = {};
    for (const [role, value] of Object.entries(cfg.column_mapping ?? {})) {
      if (typeof value === 'string' && value) roles[role] = value;
      else if (Array.isArray(value) && value.length) roles[role] = value;
    }
    return { uid, component: 'advanced_viz', kind: cfg.viz_kind as never, roles };
  }

  return null;
}

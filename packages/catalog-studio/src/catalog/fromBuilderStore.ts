/**
 * Translate depictio's builder store state into a catalog `RenderSpec` on
 * confirm. Reads the same fields depictio's own `buildMetadata.ts` reads
 * (visuType / dictKwargs / config.*), but emits the compact catalog render
 * instead of dashboard `StoredMetadata`. advanced_viz is authored by the
 * catalog-studio roles panel (its own local state), not this store.
 */
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import { FIGURE_COLUMN_KWARGS, type Aggregation, type RenderSpec } from '../types';
import { nextUid } from '../state/useStudioStore';

/** Depictio card-method key → catalog aggregation enum. */
function normalizeAggregation(agg: string): Aggregation {
  return (agg === 'unique' ? 'nunique' : agg) as Aggregation;
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
    const cfg = s.config as {
      column_name?: string;
      aggregation?: string;
      aggregations?: string[];
      secondary_layout?: string;
      breakdown_col?: string;
      top_n_count?: number;
      coverage_max?: number;
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
      ...(cfg.secondary_layout ? { secondary_layout: cfg.secondary_layout as never } : {}),
      ...(cfg.breakdown_col ? { breakdown_col: cfg.breakdown_col } : {}),
      ...(typeof cfg.top_n_count === 'number' ? { top_n_count: cfg.top_n_count } : {}),
      ...(typeof cfg.coverage_max === 'number' ? { coverage_max: cfg.coverage_max } : {}),
    };
  }

  if (s.componentType === 'interactive') {
    // The catalog carries nothing but `component` for interactive (the model
    // rejects `column`), so the form's column/variant/styling are preview-only.
    return { uid, component: 'interactive' };
  }

  if (s.componentType === 'table') {
    return { uid, component: 'table' };
  }

  return null;
}

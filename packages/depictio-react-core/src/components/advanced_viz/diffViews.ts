import type { StoredMetadata } from '../../api';

/**
 * The views of one differential test a volcano component can switch between.
 *
 * An MA plot and a QQ plot of the same test are other readings of the table
 * the volcano already binds: the effect size against the mean abundance, and
 * the p-values against the uniform null. Authored as components of their own
 * they repeated the volcano's binding, filters and thresholds, and took a tile
 * each. Instead the volcano's config names the extra columns and a View switch
 * in its controls hands the same tile to the MA or QQ renderer.
 */
export type DiffView = 'volcano' | 'ma' | 'qq';

export interface VolcanoViewsConfig {
  feature_id_col?: string;
  effect_size_col?: string;
  significance_col?: string;
  label_col?: string | null;
  category_col?: string | null;
  significance_is_neg_log10?: boolean;
  significance_threshold?: number;
  effect_threshold?: number;
  top_n_labels?: number;
  show_labels?: boolean;
  /** Raw p-values: the QQ view. */
  p_value_col?: string | null;
  /** Mean abundance in the same table: the MA view. */
  avg_log_intensity_col?: string | null;
  /** Or an MA table of its own, in the MA plot's canonical columns. */
  ma_wf_id?: string | null;
  ma_dc_id?: string | null;
  default_view?: DiffView;
}

export interface DiffViewOption {
  value: DiffView;
  label: string;
}

type Meta = StoredMetadata & { viz_kind?: string; config?: unknown };

function hasMaTable(c: VolcanoViewsConfig): boolean {
  return Boolean(c.ma_wf_id && c.ma_dc_id);
}

/** The views the config binds, the volcano first. One means no switch. */
export function volcanoViewOptions(config: VolcanoViewsConfig): DiffViewOption[] {
  const out: DiffViewOption[] = [{ value: 'volcano', label: 'Volcano' }];
  if (config.avg_log_intensity_col || hasMaTable(config)) out.push({ value: 'ma', label: 'MA' });
  if (config.p_value_col) out.push({ value: 'qq', label: 'QQ' });
  return out;
}

/** The view to draw: the pick when the config binds it, else the volcano. */
export function resolveView(pick: unknown, options: readonly DiffViewOption[]): DiffView {
  return options.find((o) => o.value === pick)?.value ?? 'volcano';
}

/**
 * The metadata the view's renderer reads: the same component (index, title,
 * chrome), with the config that renderer expects, built from the volcano's.
 * The thresholds carry over, so a hit is the same feature in every view.
 */
export function viewMetadata(metadata: Meta, view: DiffView): Meta {
  if (view === 'volcano') return metadata;
  const c = (metadata.config ?? {}) as VolcanoViewsConfig;
  const label = c.label_col ?? null;
  if (view === 'qq') {
    return {
      ...metadata,
      viz_kind: 'qq',
      config: {
        viz_kind: 'qq',
        p_value_col: c.p_value_col,
        // The hover names a point by what the volcano labels it with.
        feature_id_col: label ?? c.feature_id_col ?? null,
        category_col: c.category_col ?? null,
      },
    };
  }
  const shared = {
    significance_threshold: c.significance_threshold ?? 0.05,
    fold_change_threshold: c.effect_threshold ?? 1.0,
    top_n_labels: c.top_n_labels ?? 20,
    show_labels: c.show_labels ?? true,
  };
  if (c.avg_log_intensity_col) {
    return {
      ...metadata,
      viz_kind: 'ma',
      config: {
        viz_kind: 'ma',
        feature_id_col: c.feature_id_col,
        avg_log_intensity_col: c.avg_log_intensity_col,
        log2_fold_change_col: c.effect_size_col,
        // The MA plot colours by a raw p; a -log10 column would invert it.
        significance_col: c.significance_is_neg_log10 ? null : (c.significance_col ?? null),
        label_col: label,
        ...shared,
      },
    };
  }
  return {
    ...metadata,
    viz_kind: 'ma',
    wf_id: c.ma_wf_id ?? undefined,
    dc_id: c.ma_dc_id ?? undefined,
    config: {
      viz_kind: 'ma',
      feature_id_col: 'feature_id',
      avg_log_intensity_col: 'avg_log_intensity',
      log2_fold_change_col: 'log2_fold_change',
      significance_col: 'significance',
      label_col: 'label',
      ...shared,
    },
  };
}

/** MA controls that are the volcano's own settings under another name. */
const MA_TO_VOLCANO: Record<string, string> = {
  significance_threshold: 'significance_threshold',
  fold_change_threshold: 'effect_threshold',
  top_n_labels: 'top_n_labels',
  show_labels: 'show_labels',
};

/**
 * A control change in the view, as a change to the volcano's config: a
 * threshold set in the MA view is the volcano's threshold. Anything the
 * volcano has no setting for (a QQ plot's band, its point size) stays with
 * the view and is not saved.
 */
export function volcanoPatch(view: DiffView, patch: Record<string, unknown>): Record<string, unknown> {
  if (view === 'volcano') return patch;
  if (view === 'qq') return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(patch)) {
    const key = MA_TO_VOLCANO[k];
    if (key) out[key] = v;
  }
  return out;
}

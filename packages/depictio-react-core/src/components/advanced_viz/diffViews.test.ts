import { describe, expect, it } from 'vitest';

import { resolveView, viewMetadata, volcanoPatch, volcanoViewOptions } from './diffViews';

const base = {
  index: 'v1',
  component_type: 'advanced_viz',
  wf_id: 'wf',
  dc_id: 'dc',
  title: 'DA',
};
const volcano = {
  viz_kind: 'volcano',
  feature_id_col: 'id',
  effect_size_col: 'lfc',
  significance_col: 'q_val',
  label_col: 'Phylum',
  category_col: 'contrast',
  significance_threshold: 0.01,
  effect_threshold: 0.5,
};

describe('volcanoViewOptions', () => {
  it('offers only the volcano when nothing else is bound', () => {
    expect(volcanoViewOptions(volcano).map((o) => o.value)).toEqual(['volcano']);
  });
  it('adds MA for a mean-abundance column or an MA table, QQ for raw p-values', () => {
    expect(
      volcanoViewOptions({ ...volcano, avg_log_intensity_col: 'mean', p_value_col: 'p_val' }).map(
        (o) => o.value,
      ),
    ).toEqual(['volcano', 'ma', 'qq']);
    expect(
      volcanoViewOptions({ ...volcano, ma_wf_id: 'w2', ma_dc_id: 'd2' }).map((o) => o.value),
    ).toEqual(['volcano', 'ma']);
    // Half an MA binding (an unresolved tag) is not one.
    expect(volcanoViewOptions({ ...volcano, ma_dc_id: 'd2' }).map((o) => o.value)).toEqual([
      'volcano',
    ]);
  });
});

describe('resolveView', () => {
  it('falls back to the volcano for a view the config does not bind', () => {
    const opts = volcanoViewOptions({ ...volcano, p_value_col: 'p_val' });
    expect(resolveView('qq', opts)).toBe('qq');
    expect(resolveView('ma', opts)).toBe('volcano');
    expect(resolveView(undefined, opts)).toBe('volcano');
  });
});

describe('viewMetadata', () => {
  it('builds the QQ config from the p-values, labelled and split like the volcano', () => {
    const m = viewMetadata({ ...base, config: { ...volcano, p_value_col: 'p_val' } }, 'qq');
    expect(m.viz_kind).toBe('qq');
    expect(m.dc_id).toBe('dc');
    expect(m.index).toBe('v1');
    expect(m.config).toEqual({
      viz_kind: 'qq',
      p_value_col: 'p_val',
      feature_id_col: 'Phylum',
      category_col: 'contrast',
    });
  });

  it('builds an MA on the same table, the effect size on y, thresholds carried over', () => {
    const m = viewMetadata({ ...base, config: { ...volcano, avg_log_intensity_col: 'mean' } }, 'ma');
    expect(m.dc_id).toBe('dc');
    expect(m.config).toMatchObject({
      viz_kind: 'ma',
      avg_log_intensity_col: 'mean',
      log2_fold_change_col: 'lfc',
      significance_col: 'q_val',
      significance_threshold: 0.01,
      fold_change_threshold: 0.5,
    });
  });

  it('drops a -log10 significance, which the MA plot would read inverted', () => {
    const m = viewMetadata(
      {
        ...base,
        config: { ...volcano, avg_log_intensity_col: 'mean', significance_is_neg_log10: true },
      },
      'ma',
    );
    expect((m.config as Record<string, unknown>).significance_col).toBeNull();
  });

  it('points an MA table view at that table, in its canonical columns', () => {
    const m = viewMetadata({ ...base, config: { ...volcano, ma_wf_id: 'w2', ma_dc_id: 'd2' } }, 'ma');
    expect(m.wf_id).toBe('w2');
    expect(m.dc_id).toBe('d2');
    expect(m.config).toMatchObject({
      feature_id_col: 'feature_id',
      avg_log_intensity_col: 'avg_log_intensity',
      log2_fold_change_col: 'log2_fold_change',
    });
  });

  it('leaves the volcano as it is', () => {
    const meta = { ...base, config: volcano };
    expect(viewMetadata(meta, 'volcano')).toBe(meta);
  });
});

describe('volcanoPatch', () => {
  it('saves an MA threshold as the volcano setting it stands for', () => {
    expect(volcanoPatch('ma', { fold_change_threshold: 2 })).toEqual({ effect_threshold: 2 });
    expect(volcanoPatch('ma', { significance_threshold: 0.1 })).toEqual({
      significance_threshold: 0.1,
    });
  });
  it('keeps what the volcano has no setting for out of its config', () => {
    expect(volcanoPatch('qq', { show_ci: false, top_n_labels: 3 })).toEqual({});
    expect(volcanoPatch('ma', { unknown: 1 })).toEqual({});
  });
});

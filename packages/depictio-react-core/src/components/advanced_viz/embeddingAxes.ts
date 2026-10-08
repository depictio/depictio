/** Axis titles for the embedding scatter.
 *
 * A precomputed DC usually stores its coordinates under generic names
 * (`dim_1`, `dim_2`), which read as raw column names on the axes. The
 * `axis_prefix` config names the dimensions instead (`PCo` gives PCo1 / PCo2);
 * in live-compute mode the method supplies it. Without either, the column
 * names stay, as before.
 */
export type EmbeddingMethod = 'pca' | 'umap' | 'tsne' | 'pcoa';

const METHOD_PREFIX: Record<EmbeddingMethod, string> = {
  pca: 'PC',
  pcoa: 'PCo',
  umap: 'UMAP',
  tsne: 't-SNE ',
};

export function embeddingAxisTitles(
  config: {
    dim_1_col?: string | null;
    dim_2_col?: string | null;
    dim_3_col?: string | null;
    axis_prefix?: string | null;
  },
  liveMethod?: EmbeddingMethod | null,
): [string, string, string] {
  const prefix = config.axis_prefix || (liveMethod ? METHOD_PREFIX[liveMethod] : null);
  if (prefix) return [`${prefix}1`, `${prefix}2`, `${prefix}3`];
  return [config.dim_1_col || 'dim_1', config.dim_2_col || 'dim_2', config.dim_3_col || 'dim_3'];
}

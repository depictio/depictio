/**
 * One y position per bar of a horizontal per-feature bar chart.
 *
 * Plotly puts bars that share a category on the same row, on top of each
 * other. A chart positioned on a display label (a GSEA phenotype, a gene
 * shared by two samples' copies of a cluster) drew fifteen gene sets as two
 * bars. Each row keeps its feature id; a repeat gets an invisible suffix, so the
 * rows stay apart while the label on the bar reads the same.
 */
export function barRowKeys(features: readonly string[]): string[] {
  const seen = new Map<string, number>();
  return features.map((f) => {
    const n = seen.get(f) ?? 0;
    seen.set(f, n + 1);
    return n === 0 ? f : `${f}​${'​'.repeat(n - 1)}`;
  });
}

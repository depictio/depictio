/**
 * Reads the MultiQC cascade pick (`selected_module` / `selected_plot` /
 * `selected_dataset`) from a stored_metadata-like dict, falling back to the
 * pre-rename `multiqc_*` keys for components saved before
 * `buildMetadata.ts → buildMultiqc` started writing the canonical names.
 *
 * Also derives `isGeneralStats` so callers don't have to repeat the four-way
 * check — GS components may be tagged via the cascade pick OR via the
 * standalone `is_general_stats: true` flag the builder also writes.
 */
export interface MultiqcSelection {
  module: string | undefined;
  plot: string | undefined;
  dataset: string | undefined;
  isGeneralStats: boolean;
}

export function readMultiqcSelection(
  md: Record<string, unknown> | null | undefined,
): MultiqcSelection {
  const m = md ?? {};
  const module =
    (m.selected_module as string | undefined) ??
    (m.multiqc_module as string | undefined);
  const plot =
    (m.selected_plot as string | undefined) ??
    (m.multiqc_plot as string | undefined);
  const dataset =
    (m.selected_dataset as string | undefined) ??
    (m.multiqc_dataset as string | undefined);
  return {
    module,
    plot,
    dataset,
    isGeneralStats:
      module === 'general_stats' ||
      plot === 'general_stats' ||
      Boolean(m.is_general_stats),
  };
}

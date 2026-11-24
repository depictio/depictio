/**
 * The rows of a coverage track that sit on the chromosomes it shows.
 *
 * A track's x axis is one coordinate system. The server narrows its rows to
 * the chosen chromosomes, but a result computed ahead of time (the static
 * catalog, an offline report) holds every chromosome whatever the choice, and
 * drawn together their bins overlap position for position. Pure, so tested
 * without the renderer.
 */

export interface TrackRows {
  rows: Record<string, unknown[]>;
  columns: { chromosome: string };
}

export function restrictToChromosomes<T extends TrackRows>(data: T, shown: readonly string[]): T {
  const chroms = (data.rows[data.columns.chromosome] as unknown[] | undefined) ?? [];
  if (!shown.length || !chroms.length) return data;
  const keep = new Set(shown.map(String));
  const idx: number[] = [];
  for (let i = 0; i < chroms.length; i++) if (keep.has(String(chroms[i]))) idx.push(i);
  if (idx.length === chroms.length) return data;
  const rows: Record<string, unknown[]> = {};
  for (const [col, values] of Object.entries(data.rows)) {
    rows[col] = Array.isArray(values) ? idx.map((i) => values[i]) : values;
  }
  return { ...data, rows };
}

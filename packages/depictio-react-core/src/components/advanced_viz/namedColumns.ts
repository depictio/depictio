/**
 * The columns a viz config names: its explicit list, else the schema columns
 * its pattern matches, in schema order.
 *
 * A template whose columns are one per sample of the run names them by
 * pattern, and only the worker resolves that against the loaded frame. The
 * schema is the nearest thing in the browser: close enough to keep those
 * columns out of pickers and to seed a data preview. A pattern the browser
 * cannot compile names nothing.
 */
export function namedColumns(
  listed: string[] | null | undefined,
  pattern: string | null | undefined,
  schema: Record<string, string> | null,
): string[] {
  if (listed) return listed;
  if (!pattern || !schema) return [];
  try {
    const matcher = new RegExp(pattern);
    return Object.keys(schema).filter((c) => matcher.test(c));
  } catch {
    return [];
  }
}

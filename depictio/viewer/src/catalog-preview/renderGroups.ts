/**
 * The render switcher of a catalog output, grouped by what a render is.
 *
 * `renders_as` lists renders in the order a module author wrote them, which
 * put a KPI or a filter first as often as a plot. A reader comes to see the
 * figures, so the switcher shows them first and the rest under their kind:
 * plots, then cards, filters, tables. A kind no group names goes last, as is.
 * Pure, so the order is tested without rendering the page.
 */

export interface RenderGroup {
  key: string;
  label: string;
  /** The component type whose depictio visual (icon, colour) stands for the
   *  kind: the same as in the "new component" grid, once per kind. */
  type: string;
  /** Indices into the output's `renders`, in their authored order. */
  indices: number[];
}

const GROUPS: ReadonlyArray<{ key: string; label: string; types: readonly string[] }> = [
  {
    key: 'plots',
    label: 'Plots',
    types: ['figure', 'advanced_viz', 'multiqc', 'image', 'jbrowse', 'map', 'geojson', 'phylogeny'],
  },
  { key: 'cards', label: 'Cards', types: ['card'] },
  { key: 'filters', label: 'Filters', types: ['interactive'] },
  { key: 'tables', label: 'Tables', types: ['table'] },
];

export function groupRenders(types: readonly string[]): RenderGroup[] {
  const out: RenderGroup[] = GROUPS.map((g) => ({ key: g.key, label: g.label, type: '', indices: [] }));
  const other: RenderGroup = { key: 'other', label: 'Other', type: '', indices: [] };
  types.forEach((type, i) => {
    const at = GROUPS.findIndex((g) => g.types.includes(type));
    const group = at >= 0 ? out[at] : other;
    group.indices.push(i);
    // A kind wears its first render's type: a plots tab of advanced viz only
    // shows the advanced-viz visual, a mixed one the first of them.
    if (!group.type) group.type = type;
  });
  return [...out, other].filter((g) => g.indices.length > 0);
}

/** The render the page opens on: the first plot, else the first render. */
export function firstRender(types: readonly string[]): number {
  const groups = groupRenders(types);
  return groups.length ? groups[0].indices[0] : 0;
}

/** A render's name on its button: its title, cut with an ellipsis past `max`. */
export function renderButtonLabel(title: unknown, fallback: string, max = 36): string {
  const text = typeof title === 'string' && title.trim() ? title.trim() : fallback;
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}\u2026` : text;
}

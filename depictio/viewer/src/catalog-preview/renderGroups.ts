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
  /** One light icon for the whole kind, instead of one per render. */
  icon: string;
  /** Indices into the output's `renders`, in their authored order. */
  indices: number[];
}

const GROUPS: ReadonlyArray<{ key: string; label: string; icon: string; types: readonly string[] }> = [
  {
    key: 'plots',
    label: 'Plots',
    icon: 'tabler:chart-bar',
    types: ['figure', 'advanced_viz', 'multiqc', 'image', 'jbrowse', 'map', 'geojson', 'phylogeny'],
  },
  { key: 'cards', label: 'Cards', icon: 'tabler:number', types: ['card'] },
  { key: 'filters', label: 'Filters', icon: 'tabler:adjustments-horizontal', types: ['interactive'] },
  { key: 'tables', label: 'Tables', icon: 'tabler:table', types: ['table'] },
];
const OTHER = { key: 'other', label: 'Other', icon: 'tabler:puzzle' };

export function groupRenders(types: readonly string[]): RenderGroup[] {
  const out: RenderGroup[] = GROUPS.map((g) => ({ key: g.key, label: g.label, icon: g.icon, indices: [] }));
  const other: RenderGroup = { ...OTHER, indices: [] };
  types.forEach((type, i) => {
    const at = GROUPS.findIndex((g) => g.types.includes(type));
    (at >= 0 ? out[at] : other).indices.push(i);
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

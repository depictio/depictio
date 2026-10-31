/**
 * The region navigator of a genome browser tile: spatial previous / next over
 * the merged regions of `locus_from`, and the region picker's grid. The calls
 * come from the backend (`fetchJBrowseCalls`); this file holds the pure part:
 * the `near` query a step sends, the sources a reader switched off, the shape
 * of the picker's columns, sort and requests, and the labels.
 */
import type {
  JBrowseCall,
  JBrowseCallsBody,
  JBrowseColumnFilter,
  JBrowseLocusFrom,
  JBrowseNearQuery,
} from '../../api';
import type { NamedLocusSource } from './locusSources';
import { paletteVar } from '../../paletteColor';

/** A stretch of one contig as JBrowse reports the visible span (0-based, end-exclusive). */
export interface VisibleRegion {
  refName: string;
  start: number;
  end: number;
}

/** Rows per request of the picker (the endpoint allows up to 200). */
export const PICKER_PAGE_SIZE = 50;

/**
 * The `near` query of a step. The anchor is the edge of the visible span the
 * reader is heading to (right edge for next, left edge for previous), so the
 * region in view is skipped rather than landing on it again. Positions are
 * 1-based like the data: the left edge is the first visible base. Null when
 * the view shows nothing yet.
 */
export function nearQuery(
  direction: 1 | -1,
  visible: readonly VisibleRegion[],
  chromOrder: readonly string[],
): JBrowseNearQuery | null {
  const usable = visible.filter(
    (r) => r && r.refName && Number.isFinite(r.start) && Number.isFinite(r.end),
  );
  if (usable.length === 0) return null;
  const edge = direction > 0 ? usable[usable.length - 1] : usable[0];
  const pos = direction > 0 ? Math.floor(edge.end) : Math.floor(edge.start) + 1;
  return { chrom: edge.refName, pos, direction, chrom_order: [...chromOrder] };
}

/** "224,312" */
export function formatCount(n: number): string {
  return Math.max(0, Math.round(n)).toLocaleString('en-US');
}

/**
 * What one region of a source is called, from the source's name: "Peaks"
 * gives "peak", "Consensus" stays "consensus" (a name ending in -us or -ss is
 * not a plural); no name, a collection tag, or several sources at once,
 * gives "region".
 */
export function regionNoun(sourceNames: readonly string[]): string {
  if (sourceNames.length !== 1) return 'region';
  const name = sourceNames[0].trim().toLowerCase();
  if (!name) return 'region';
  // A source without a name goes by its collection tag (`vcf_variants`),
  // which is no word to count with.
  if (name.includes('_')) return 'region';
  return /[^us]s$/.test(name) ? name.slice(0, -1) : name;
}

/** The badge text: "224,312 regions" ("1 region"), or with the source's noun. */
export function regionCountLabel(n: number, noun = 'region'): string {
  const plural = /s$/.test(noun) ? noun : `${noun}s`;
  return `${formatCount(n)} ${n === 1 ? noun : plural}`;
}

/** What the header shows beside the keys: the region's label, else its locus,
 *  plus the sample count when overlapping regions of several samples were
 *  merged into it. */
export function navigatorCaption(call: JBrowseCall | null): string | null {
  if (!call) return null;
  const base = call.label?.trim() || call.locus || null;
  if (!base) return null;
  const n = call.n_samples ?? 0;
  return n > 1 ? `${base} · ${n} samples` : base;
}

/** Fields of the data-version request body that the calls endpoint reads. */
export function versionFields(
  versionBody: Record<string, unknown>,
): Pick<JBrowseCallsBody, 'as_of_version' | 'data_versions'> {
  return {
    ...(versionBody.as_of_version !== undefined
      ? { as_of_version: versionBody.as_of_version as string | null }
      : {}),
    ...(versionBody.data_versions !== undefined
      ? { data_versions: versionBody.data_versions as Record<string, unknown> | null }
      : {}),
  };
}

/** Where the enabled sources of a tile are remembered. */
export function sourcesStorageKey(index: string): string {
  return `depictio.jbrowse.${index}.sources`;
}

/**
 * The source the reader steps through: one at a time, the first stored name
 * the tile still has. Nothing stored, unreadable, or none left means the
 * tile's first source (the reader can never end up reading nothing).
 */
export function normalizeEnabledSources(
  stored: readonly string[] | null | undefined,
  names: readonly string[],
): string[] {
  const kept = Array.isArray(stored) ? names.filter((n) => stored.includes(n)) : [];
  const first = kept[0] ?? names[0];
  return first === undefined ? [] : [first];
}

/** Parse the stored JSON; null when absent or malformed. */
export function parseStoredSources(raw: string | null): string[] | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((s): s is string => typeof s === 'string') : null;
  } catch {
    return null;
  }
}

/** The `sources` of a request: null (read them all) when every one is on. */
export function sourcesBody(
  enabled: readonly string[],
  names: readonly string[],
): string[] | null {
  return names.every((n) => enabled.includes(n)) ? null : [...enabled];
}

/** The Mantine CSS variable of a source's palette colour, null without one. */
export function sourceColorVar(color: string | null | undefined): string | null {
  return paletteVar(color) ?? null;
}

/** Extra columns a source shows in the picker (`locus_from.columns`). */
export function extraColumns(source: JBrowseLocusFrom): string[] {
  const cols = (source as { columns?: unknown }).columns;
  return Array.isArray(cols) ? cols.filter((c): c is string => typeof c === 'string') : [];
}

// ----- the picker's grid -----------------------------------------------------

export type PickerColumnId =
  | 'label'
  | 'locus'
  | 'score'
  | 'sample'
  | 'run'
  | 'source'
  | 'n_samples'
  | 'samples'
  | 'sources'
  | `extra:${string}`;

export interface PickerColumn {
  id: PickerColumnId;
  header: string;
  /** Column the backend sorts by, null when the header is not sortable. */
  sortColumn: string | null;
  /** Column the backend filters on, and how; absent when not filterable. */
  filter?: { column: string; kind: 'text' | 'number' };
  width: number;
}

/**
 * The picker's columns for a mode. In merged mode the backend sorts by
 * chrom / start / score / n_samples only, so the other headers are not
 * sortable; in rows mode a header sorts by the column it shows.
 */
export function pickerColumns(args: {
  sources: readonly NamedLocusSource[];
  merged: boolean;
  scoreLabel?: string | null;
}): PickerColumn[] {
  const { sources, merged } = args;
  const primary = sources[0];
  if (!primary) return [];
  const multi = sources.length > 1;
  const scoreName = args.scoreLabel || primary.sort_by || null;
  const hasScore = sources.some((s) => !!s.sort_by);
  const anyOf = (pick: (s: NamedLocusSource) => string | null | undefined) =>
    sources.some((s) => !!pick(s));

  const cols: PickerColumn[] = [
    {
      id: 'label',
      header: multi ? 'Name' : 'Region',
      sortColumn: merged ? null : (primary.label_column ?? null),
      filter: { column: 'label', kind: 'text' },
      width: 150,
    },
    {
      id: 'locus',
      header: 'Locus',
      sortColumn: 'chrom',
      filter: { column: 'chrom', kind: 'text' },
      width: 170,
    },
  ];
  if (hasScore) {
    cols.push({
      id: 'score',
      header: scoreName ?? 'Score',
      sortColumn: merged ? 'score' : (primary.sort_by ?? null),
      filter: { column: 'score', kind: 'number' },
      width: 90,
    });
  }
  if (merged) {
    cols.push({
      id: 'n_samples',
      header: 'Samples',
      sortColumn: 'n_samples',
      filter: { column: 'n_samples', kind: 'number' },
      width: 90,
    });
    cols.push({ id: 'samples', header: 'Sample names', sortColumn: null, width: 170 });
    if (multi) cols.push({ id: 'sources', header: 'Sources', sortColumn: null, width: 140 });
    return cols;
  }
  if (anyOf((s) => s.sample_column)) {
    cols.push({
      id: 'sample',
      header: 'Sample',
      sortColumn: primary.sample_column ?? null,
      filter: { column: 'sample', kind: 'text' },
      width: 120,
    });
  }
  if (anyOf((s) => s.run_column)) {
    cols.push({
      id: 'run',
      header: 'Run',
      sortColumn: primary.run_column ?? null,
      filter: { column: 'run', kind: 'text' },
      width: 110,
    });
  }
  if (multi) {
    cols.push({
      id: 'source',
      header: 'Source',
      sortColumn: null,
      filter: { column: 'source', kind: 'text' },
      width: 120,
    });
  }
  const seen = new Set<string>();
  for (const s of sources) {
    for (const name of extraColumns(s)) {
      if (seen.has(name)) continue;
      seen.add(name);
      // Text until the rows say the column holds numbers (`withNumericExtras`).
      cols.push({
        id: `extra:${name}`,
        header: name,
        sortColumn: name,
        filter: { column: name, kind: 'text' },
        width: 110,
      });
    }
  }
  return cols;
}

/** The extra columns whose loaded cells are all numbers filter as numbers. */
export function withNumericExtras(
  columns: readonly PickerColumn[],
  rows: readonly JBrowseCall[],
): PickerColumn[] {
  return columns.map((c) => {
    if (!c.id.startsWith('extra:') || !c.filter || !rows.length) return c;
    const name = c.id.slice('extra:'.length);
    const values = rows.map((r) => r.extra?.[name]).filter((v) => v !== null && v !== undefined && v !== '');
    const numeric = values.length > 0 && values.every((v) => typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))));
    return numeric ? { ...c, filter: { ...c.filter, kind: 'number' as const } } : c;
  });
}

/** One entry of AG Grid's filter model (a single condition per column). */
export interface GridFilter {
  filterType?: string;
  type?: string;
  filter?: string | number | null;
  filterTo?: number | null;
}

/** The backend's column filters for AG Grid's filter model; a condition with
 *  no value (an emptied box) or on a column the backend cannot filter is left out. */
export function gridFiltersToBody(
  filterModel: Record<string, GridFilter> | null | undefined,
  columns: readonly PickerColumn[],
): JBrowseColumnFilter[] {
  const out: JBrowseColumnFilter[] = [];
  for (const [colId, f] of Object.entries(filterModel ?? {})) {
    const col = columns.find((c) => c.id === colId);
    if (!col?.filter || !f?.type) continue;
    if (f.filter === null || f.filter === undefined || f.filter === '') continue;
    const number = col.filter.kind === 'number';
    const value = number ? Number(f.filter) : String(f.filter);
    if (number && !Number.isFinite(value)) continue;
    const entry: JBrowseColumnFilter = { column: col.filter.column, kind: col.filter.kind, op: f.type, value };
    if (f.type === 'inRange') {
      if (f.filterTo === null || f.filterTo === undefined) continue;
      entry.value_to = Number(f.filterTo);
    }
    out.push(entry);
  }
  return out;
}

/** AG Grid's sort model entry. */
export interface GridSort {
  colId: string;
  sort: 'asc' | 'desc' | null | undefined;
}

/** The backend sort for AG Grid's sort model: the first sorted column that is
 *  sortable. Null leaves the order to `locus_from.sort_by`. */
export function gridSortToBody(
  sortModel: readonly GridSort[],
  columns: readonly PickerColumn[],
): JBrowseCallsBody['sort'] {
  for (const s of sortModel) {
    if (!s.sort) continue;
    const col = columns.find((c) => c.id === s.colId);
    if (col?.sortColumn) return { column: col.sortColumn, descending: s.sort === 'desc' };
  }
  return null;
}

/** The request for one block of the picker's infinite row model. */
export function pickerRequest(args: {
  filters: JBrowseCallsBody['filters'];
  versionBody: Record<string, unknown>;
  startRow: number;
  endRow: number;
  sortModel: readonly GridSort[];
  columns: readonly PickerColumn[];
  search: string;
  sources: string[] | null;
  merged: boolean;
  filterModel?: Record<string, GridFilter> | null;
}): JBrowseCallsBody {
  const columnFilters = gridFiltersToBody(args.filterModel, args.columns);
  const search = args.search.trim();
  return {
    filters: args.filters,
    start: args.startRow,
    limit: Math.max(1, Math.min(200, args.endRow - args.startRow)),
    sort: gridSortToBody(args.sortModel, args.columns),
    search: search || null,
    ...(columnFilters.length ? { column_filters: columnFilters } : {}),
    sources: args.sources,
    merge: args.merged,
    ...versionFields(args.versionBody),
  };
}

const text = (v: unknown): string => (v === null || v === undefined ? '' : String(v));

/** One cell of the picker. */
export function cellValue(call: JBrowseCall | undefined, id: PickerColumnId): string | number {
  if (!call) return '';
  switch (id) {
    case 'label':
      return call.label?.trim() || call.source || '';
    case 'locus':
      return call.locus ?? '';
    case 'score':
      return call.score === null || call.score === undefined ? '' : call.score;
    case 'sample':
      return text(call.sample);
    case 'run':
      return text(call.run);
    case 'source':
      return text(call.source);
    case 'n_samples':
      return call.n_samples ?? '';
    case 'samples': {
      const names = call.samples ?? [];
      const more = (call.n_samples ?? names.length) - names.length;
      return names.join(', ') + (more > 0 ? ` +${more}` : '');
    }
    case 'sources':
      return (call.sources ?? []).join(', ');
    default:
      return text(call.extra?.[id.slice('extra:'.length)]);
  }
}

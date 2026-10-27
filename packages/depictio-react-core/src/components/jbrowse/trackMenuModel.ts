import type { JBrowseTrackRow } from '../../api';

/** "Show all" opens at most this many tracks: every open track fetches its
 *  own data, so opening hundreds at once would stall the browser. */
export const SHOW_ALL_CAP = 60;

export type TrackSource = NonNullable<JBrowseTrackRow['source']>;

/** The two top-level sections of the track menu. */
export type TrackSection = 'project' | 'external';

export const SECTION_LABELS: Record<TrackSection, string> = {
  project: 'Project tracks',
  external: 'External tracks',
};

export interface TrackGroup {
  /** Stable React key (a manifest category may itself be called "UCSC"). */
  key: string;
  label: string;
  /** The top-level section the group sits in. */
  section: TrackSection;
  rows: JBrowseTrackRow[];
}

/** A row's origin; rows from a backend that predates ``source`` are manifest rows. */
export function rowSource(row: JBrowseTrackRow): TrackSource {
  return row.source ?? 'manifest';
}

export function isManifestRow(row: JBrowseTrackRow): boolean {
  return rowSource(row) === 'manifest';
}

/** Track ids of the manifest rows: the ones the dashboard filters drive. */
export function manifestTrackIds(rows: JBrowseTrackRow[]): string[] {
  return rows.filter(isManifestRow).map((r) => r.track_id);
}

/**
 * Case-insensitive search over the fields a user would type: every
 * whitespace-separated term must appear in the name, id, category, sample or
 * selection value (so "h3k27 liver" narrows on both).
 */
export function rowMatchesQuery(row: JBrowseTrackRow, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const hay = [row.name, row.track_id, row.category, row.sample, row.selection_value, row.format]
    .filter((v): v is string => typeof v === 'string' && v.length > 0)
    .join('\u0000')
    .toLowerCase();
  return terms.every((t) => hay.includes(t));
}

/** Readable names of the UCSC track groups (the `group` of a catalogue entry). */
const UCSC_GROUP_LABELS: Record<string, string> = {
  genes: 'Genes',
  regulation: 'Regulation',
  rep: 'Repeats',
  phenDis: 'Phenotype & disease',
  map: 'Mapping & recombination',
  varRep: 'Variation',
  expression: 'Expression',
  compGeno: 'Comparative genomics',
  mrna: 'mRNA & EST',
  rna: 'RNA',
  cons: 'Conservation',
  x: 'Experimental',
};

/**
 * JBrowse's own track selector (the toolbar burger) groups tracks by their
 * ``category`` path. Put the two top-level sections in front of it: manifest
 * tracks under "Project tracks", everything else (UCSC, annotation, extra)
 * under "External tracks", with UCSC groups given their readable labels.
 */
export function withSectionCategory<T extends { trackId: string; category?: string[] }>(
  confs: T[],
  rows: JBrowseTrackRow[],
  /** Value a manifest track is grouped under instead of its own category path
   *  (the tile's `color_by` column); null keeps the path. */
  groupOf?: (conf: T) => string | null,
): T[] {
  const sources = new Map(rows.map((r) => [r.track_id, rowSource(r)]));
  return confs.map((conf) => {
    const path = conf.category ?? [];
    if (sources.get(conf.trackId) === 'manifest') {
      const group = groupOf?.(conf) ?? null;
      return { ...conf, category: [SECTION_LABELS.project, ...(group ? [group] : path)] };
    }
    const rest =
      path[0] === 'UCSC' && path.length > 1
        ? [ucscGroupLabel(path[1])]
        : path;
    return { ...conf, category: [SECTION_LABELS.external, ...rest] };
  });
}

/** The sections that have at least one group, in menu order. */
export function sectionsOf(groups: TrackGroup[]): TrackSection[] {
  const out: TrackSection[] = [];
  for (const g of groups) if (!out.includes(g.section)) out.push(g.section);
  return out;
}

/** The label of a UCSC track group; unknown codes are shown as they are. */
export function ucscGroupLabel(code: string | null | undefined): string {
  if (!code) return 'UCSC · Other';
  return `UCSC · ${UCSC_GROUP_LABELS[code] ?? code}`;
}

/**
 * The track menu's sections, for the rows matching ``query``: the reference
 * tracks first (assembly annotation and ``extra_tracks``, what orients the
 * view), then the manifest rows grouped by ``category`` (first-appearance
 * order, uncategorised ones last), then the UCSC tracks, one section per
 * UCSC group. Empty groups are dropped.
 */
export function groupTrackRows(
  rows: JBrowseTrackRow[],
  query = '',
  /** Group of a manifest row, replacing its category (the tile's `color_by`
   *  value); null keeps the category. */
  groupOf?: (row: JBrowseTrackRow) => string | null,
): TrackGroup[] {
  const categories = new Map<string, JBrowseTrackRow[]>();
  const uncategorised: JBrowseTrackRow[] = [];
  const ucsc = new Map<string, JBrowseTrackRow[]>();
  const reference: JBrowseTrackRow[] = [];
  for (const row of rows) {
    if (!rowMatchesQuery(row, query)) continue;
    const source = rowSource(row);
    if (source === 'ucsc') {
      const code = row.category ?? '';
      const list = ucsc.get(code);
      if (list) list.push(row);
      else ucsc.set(code, [row]);
    } else if (source === 'annotation' || source === 'extra') {
      reference.push(row);
    } else if (groupOf?.(row) ?? row.category) {
      const key = (groupOf?.(row) ?? row.category) as string;
      const list = categories.get(key);
      if (list) list.push(row);
      else categories.set(key, [row]);
    } else {
      uncategorised.push(row);
    }
  }
  // Project tracks: the manifest's categories. External tracks: the reference
  // annotation, then the UCSC groups.
  const groups: TrackGroup[] = [];
  if (reference.length) {
    groups.push({ key: 'reference', label: 'Reference', section: 'external', rows: reference });
  }
  for (const [label, list] of categories) {
    groups.push({ key: `category:${label}`, label, section: 'project', rows: list });
  }
  if (uncategorised.length) {
    groups.push({
      key: 'uncategorised',
      label: categories.size ? 'Other tracks' : 'Tracks',
      section: 'project',
      rows: uncategorised,
    });
  }
  for (const [code, list] of ucsc) {
    groups.push({ key: `ucsc:${code}`, label: ucscGroupLabel(code), section: 'external', rows: list });
  }
  return groups;
}

/**
 * What "Show all" opens: the first ``cap`` matching rows in menu order.
 * ``total`` is every matching row (the button's count), ``capped`` whether
 * some were left out (the menu then says so).
 */
export function showAllPlan(
  groups: TrackGroup[],
  cap: number = SHOW_ALL_CAP,
): { ids: string[]; total: number; capped: boolean } {
  const all = groups.flatMap((g) => g.rows.map((r) => r.track_id));
  return { ids: all.slice(0, Math.max(0, cap)), total: all.length, capped: all.length > cap };
}

/** The open tracks "Hide all" closes: manifest rows only, so the reference
 *  annotation and UCSC tracks stay as orientation. */
export function hideAllIds(open: string[], rows: JBrowseTrackRow[]): string[] {
  const manifest = new Set(manifestTrackIds(rows));
  return open.filter((id) => manifest.has(id));
}

/** How many of ``rows`` are open, for the "k / N open" header. */
export function countOpen(rows: JBrowseTrackRow[], open: Iterable<string>): number {
  const isOpen = new Set(open);
  return rows.reduce((n, r) => n + (isOpen.has(r.track_id) ? 1 : 0), 0);
}

/**
 * The "Genome tracks" section of the metadata panel, as plain data.
 *
 * Built from the tile's static config (what the YAML says, always known) and,
 * once the tile has rendered, its payload and visible locus (what is actually
 * on screen). Pure, so it is testable without React or a browser. Every URI it
 * carries is a display field the backend already sanitized (see `display_uri`).
 */
import type { JBrowseLocusFrom, JBrowseSessionResponse, JBrowseTrackRow } from '../../api';
import { primaryLocusSource } from './locusSources';

/** Tracks listed per category before the rest is summarised as "+N more". */
export const MAX_LISTED_TRACKS = 60;

export interface SummaryItem {
  label: string;
  value: string;
  /** Monospace, truncated, with the full text on hover and a copy button. */
  uri?: boolean;
}

export interface TrackEntry {
  name: string;
  /** Format, sample and storage, joined for one muted line. */
  detail: string;
  origin?: string;
  index?: string;
}

export interface TrackGroup {
  category: string;
  tracks: TrackEntry[];
}

export interface GenomeSection {
  id: 'assembly' | 'location' | 'tracks' | 'ucsc' | 'data';
  title: string;
  rows: SummaryItem[];
  groups?: TrackGroup[];
  /** Tracks of the section left out of the list (cap). */
  more?: number;
}

export interface GenomeTracksSummary {
  /** True once the tile has rendered and the live sections are filled. */
  loaded: boolean;
  sections: GenomeSection[];
}

const STORAGE_LABEL: Record<string, string> = {
  remote: 'read in place',
  direct: 'read by the browser',
  depictio: 'ingested',
};

const text = (v: unknown): string =>
  v === null || v === undefined || v === '' ? '' : String(v);

const list = (v: unknown): string[] =>
  Array.isArray(v) ? v.map(text).filter(Boolean) : [];

const item = (label: string, value: unknown, uri?: boolean): SummaryItem[] => {
  const val = text(value);
  return val ? [{ label, value: val, ...(uri ? { uri } : {}) }] : [];
};

function sourceLabel(kind: string | undefined): string {
  if (kind === 'custom') return 'Custom assembly';
  if (kind === 'preset') return 'Built-in preset';
  return '';
}

function assemblySection(
  config: Record<string, unknown>,
  payload: JBrowseSessionResponse | null,
): GenomeSection {
  const assembly = payload?.assembly as
    | { name?: unknown; displayName?: unknown; aliases?: unknown }
    | undefined;
  const name = text(assembly?.displayName) || text(assembly?.name) || text(config.assembly);
  // The component's `assembly` is a preset id; without a payload that is the
  // only thing known, and it always means a preset.
  const kind = payload?.assembly_kind ?? (config.assembly ? 'preset' : undefined);
  const rows = [
    ...item('Name', name),
    ...item('Aliases', list(assembly?.aliases).join(', ')),
    ...item('Source', sourceLabel(kind)),
  ];
  return { id: 'assembly', title: 'Assembly', rows };
}

function locationSection(
  config: Record<string, unknown>,
  payload: JBrowseSessionResponse | null,
  locus: string | null,
): GenomeSection {
  // A list of sources frames the view from its first (primary) one.
  const from = (primaryLocusSource(
    config.locus_from as JBrowseLocusFrom | JBrowseLocusFrom[] | undefined,
  ) ?? undefined) as Record<string, unknown> | undefined;
  const rows = [
    ...item('Now', locus),
    ...item('Initial', payload?.location ?? config.location),
  ];
  if (from?.data_collection_tag) {
    const cols = [from.chrom_column, from.start_column, from.end_column]
      .map(text)
      .filter(Boolean)
      .join(', ');
    rows.push({
      label: 'Framed from',
      value: `${text(from.data_collection_tag)} (${cols})`,
    });
    const limits = [
      from.padding !== undefined ? `${text(from.padding)} bp padding` : '',
      from.max_rows !== undefined ? `up to ${text(from.max_rows)} rows` : '',
    ].filter(Boolean);
    if (limits.length) rows.push({ label: 'Framing', value: limits.join(', ') });
  }
  return { id: 'location', title: 'Location', rows };
}

function trackEntry(row: JBrowseTrackRow): TrackEntry {
  const detail = [row.format, row.sample, row.storage ? STORAGE_LABEL[row.storage] : null]
    .filter(Boolean)
    .join(' · ');
  return {
    name: row.name,
    detail,
    ...(row.uri ? { origin: row.uri } : {}),
    ...(row.index_uri ? { index: row.index_uri } : {}),
  };
}

function tracksSection(payload: JBrowseSessionResponse): GenomeSection {
  const rowById = new Map(payload.track_rows.map((r) => [r.track_id, r]));
  const shown = payload.shown_track_ids
    .map((id) => rowById.get(id))
    .filter((r): r is JBrowseTrackRow => !!r && r.source !== 'ucsc');
  const groups = new Map<string, TrackEntry[]>();
  let listed = 0;
  for (const row of shown) {
    if (listed >= MAX_LISTED_TRACKS) break;
    const category = row.category || (row.source === 'annotation' ? 'Annotation' : 'Tracks');
    const entries = groups.get(category) ?? [];
    entries.push(trackEntry(row));
    groups.set(category, entries);
    listed += 1;
  }
  return {
    id: 'tracks',
    title: 'Tracks',
    rows: shown.length ? [] : [{ label: 'Open', value: 'No track matches the filters' }],
    groups: [...groups].map(([category, tracks]) => ({ category, tracks })),
    more: shown.length - listed,
  };
}

function ucscSection(
  config: Record<string, unknown>,
  payload: JBrowseSessionResponse | null,
): GenomeSection | null {
  const missing = payload?.ucsc_missing ?? [];
  const names = payload
    ? payload.track_rows.filter((r) => r.source === 'ucsc').map((r) => r.name)
    : list(config.ucsc_tracks);
  if (!names.length && !missing.length) return null;
  return {
    id: 'ucsc',
    title: 'UCSC tracks',
    rows: [
      ...names.map((n) => ({ label: 'Track', value: n })),
      ...missing.map((n) => ({ label: 'Unavailable', value: n })),
    ],
  };
}

function dataSection(payload: JBrowseSessionResponse): GenomeSection {
  const shown = payload.shown_track_ids.filter(
    (id) => payload.track_rows.find((r) => r.track_id === id)?.source === 'manifest',
  ).length;
  const rows: SummaryItem[] = [
    {
      label: 'Version',
      value:
        payload.data_version == null
          ? 'Live (latest ingest)'
          : `Pinned to data version ${payload.data_version}`,
    },
    {
      label: 'Shown',
      value:
        `${shown} of ${payload.total_tracks} tracks` +
        (payload.filter_applied ? `, ${payload.matched_tracks} match the filters` : ''),
    },
  ];
  if (payload.truncated) {
    rows.push({
      label: 'Capped',
      value: `Only the first ${payload.max_tracks ?? shown} matching tracks open`,
    });
  }
  rows.push(...item('Remote folder', payload.remote_base, true));
  return { id: 'data', title: 'Data', rows };
}

/**
 * Sections of the metadata panel for one genome browser tile.
 *
 * `config` is the tile's stored metadata; `payload` / `locus` are what it last
 * rendered (null when it has not mounted yet: the static sections still show).
 */
export function buildGenomeTracksSummary(
  config: Record<string, unknown>,
  payload: JBrowseSessionResponse | null,
  locus: string | null,
): GenomeTracksSummary {
  const sections: GenomeSection[] = [
    assemblySection(config, payload),
    locationSection(config, payload, locus),
  ];
  if (payload) sections.push(tracksSection(payload));
  const ucsc = ucscSection(config, payload);
  if (ucsc) sections.push(ucsc);
  if (payload) sections.push(dataSection(payload));
  return { loaded: !!payload, sections: sections.filter((s) => s.rows.length || s.groups?.length) };
}

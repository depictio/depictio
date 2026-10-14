/**
 * The data model of the `domain_architecture` tile, pure and unit-tested in
 * `architecture.test.ts`: domain hits read off a column-oriented frame, the
 * E-value and source filters, the Pfam-graphics partial-match flags, the
 * packing of overlapping domains into lanes, architecture strings and their
 * grouping (top N, a representative protein per group), and the virtualised
 * row layout the panel draws.
 *
 * Coordinates are 1-based inclusive residue numbers, as a hmmsearch domain
 * table writes its envelope (`start`, `end`) and its HMM span (`hmm_from`,
 * `hmm_to`).
 */

import { frameLength, numberOrNull, stringOrNull } from '../protein/rendererData';

export type Frame = Record<string, unknown[]>;

/** Separator of an architecture string (`PF00001~PF00002`), as InterPro and
 *  MGnifams write a domain architecture. */
export const ARCHITECTURE_SEPARATOR = '~';

/** Label of a hit whose label and accession are both empty. */
export const UNLABELLED = 'unlabelled';

/** Where each field of a hit lives in the frame; `null` or absent = unbound. */
export interface DomainColumns {
  entity: string;
  start: string;
  end: string;
  label: string;
  proteinLength?: string | null;
  hmmFrom?: string | null;
  hmmTo?: string | null;
  hmmLength?: string | null;
  hmmCoverage?: string | null;
  evalue?: string | null;
  source?: string | null;
  description?: string | null;
  accession?: string | null;
  score?: string | null;
}

/** One domain hit on one protein. */
export interface DomainHit {
  /** Row index in the frame the hit was read from. */
  row: number;
  entity: string;
  /** Envelope on the protein, 1-based inclusive, `start <= end`. */
  start: number;
  end: number;
  label: string;
  source: string | null;
  accession: string | null;
  description: string | null;
  evalue: number | null;
  score: number | null;
  hmmFrom: number | null;
  hmmTo: number | null;
  hmmLength: number | null;
  /** Fraction of the HMM the hit covers, 0 to 1, from the coverage column. */
  coverage: number | null;
  proteinLength: number | null;
}

/**
 * A coverage value as a 0 to 1 fraction. The column is a fraction by contract;
 * a value above 1 and up to 100 reads as a percentage, anything else as unknown.
 */
export function normaliseCoverage(v: unknown): number | null {
  const n = numberOrNull(v);
  if (n == null || n < 0) return null;
  if (n <= 1) return n;
  if (n <= 100) return n / 100;
  return null;
}

/**
 * Every row of `frame` that names a protein and a span, as a hit. Rows missing
 * the entity, the start or the end are skipped and counted; a reversed span is
 * put back in order; a hit with no label takes its accession.
 */
export function parseDomainHits(
  frame: Frame | null | undefined,
  cols: DomainColumns,
): { hits: DomainHit[]; skipped: number } {
  if (!frame) return { hits: [], skipped: 0 };
  const n = frameLength(frame);
  const col = (name: string | null | undefined): unknown[] | undefined =>
    name ? frame[name] : undefined;
  const entity = col(cols.entity);
  const start = col(cols.start);
  const end = col(cols.end);
  const label = col(cols.label);
  const proteinLength = col(cols.proteinLength);
  const hmmFrom = col(cols.hmmFrom);
  const hmmTo = col(cols.hmmTo);
  const hmmLength = col(cols.hmmLength);
  const coverage = col(cols.hmmCoverage);
  const evalue = col(cols.evalue);
  const source = col(cols.source);
  const description = col(cols.description);
  const accession = col(cols.accession);
  const score = col(cols.score);
  const hits: DomainHit[] = [];
  let skipped = 0;
  if (!entity || !start || !end) return { hits, skipped: n };
  for (let i = 0; i < n; i++) {
    const e = stringOrNull(entity[i]);
    const s = numberOrNull(start[i]);
    const t = numberOrNull(end[i]);
    if (e == null || s == null || t == null) {
      skipped++;
      continue;
    }
    const acc = accession ? stringOrNull(accession[i]) : null;
    hits.push({
      row: i,
      entity: e,
      start: Math.min(s, t),
      end: Math.max(s, t),
      label: (label ? stringOrNull(label[i]) : null) ?? acc ?? UNLABELLED,
      source: source ? stringOrNull(source[i]) : null,
      accession: acc,
      description: description ? stringOrNull(description[i]) : null,
      evalue: evalue ? numberOrNull(evalue[i]) : null,
      score: score ? numberOrNull(score[i]) : null,
      hmmFrom: hmmFrom ? numberOrNull(hmmFrom[i]) : null,
      hmmTo: hmmTo ? numberOrNull(hmmTo[i]) : null,
      hmmLength: hmmLength ? numberOrNull(hmmLength[i]) : null,
      coverage: coverage ? normaliseCoverage(coverage[i]) : null,
      proteinLength: proteinLength ? numberOrNull(proteinLength[i]) : null,
    });
  }
  return { hits, skipped };
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

export interface HitFilter {
  /** Keep hits at or below this E-value; null or non-positive keeps all. */
  evalueThreshold?: number | null;
  /** Keep hits whose source is listed (case-insensitive); empty keeps all. */
  sources?: readonly string[] | null;
}

/** Whether the source filter can apply: some hit names a source. */
export function hasSources(hits: readonly DomainHit[]): boolean {
  return hits.some((h) => h.source != null);
}

/**
 * The hits the tile draws. A hit with no E-value passes the threshold (there
 * is nothing to compare). The source filter is ignored when no hit carries a
 * source (the column is not bound), rather than hiding every domain.
 */
export function filterHits(hits: readonly DomainHit[], filter: HitFilter): DomainHit[] {
  const threshold =
    filter.evalueThreshold != null &&
    Number.isFinite(filter.evalueThreshold) &&
    filter.evalueThreshold > 0
      ? filter.evalueThreshold
      : null;
  const wanted =
    filter.sources && filter.sources.length && hasSources(hits)
      ? new Set(filter.sources.map((s) => s.toLowerCase()))
      : null;
  if (threshold == null && !wanted) return hits.slice();
  return hits.filter((h) => {
    if (threshold != null && h.evalue != null && h.evalue > threshold) return false;
    if (wanted && (h.source == null || !wanted.has(h.source.toLowerCase()))) return false;
    return true;
  });
}

// ---------------------------------------------------------------------------
// Partial HMM matches (Pfam graphics)
// ---------------------------------------------------------------------------

export interface PartialEdges {
  /** The match starts after the first HMM state: the N-terminal edge is jagged. */
  left: boolean;
  /** The match ends before the last HMM state: the C-terminal edge is jagged. */
  right: boolean;
  /** Partial by coverage alone: no HMM states say which end is missing. */
  unknown: boolean;
}

export const FULL_MATCH: PartialEdges = Object.freeze({
  left: false,
  right: false,
  unknown: false,
});

/**
 * Which edges of a domain are drawn jagged.
 *
 * From the HMM states first, as Pfam graphics does: `hmm_from > 1` cuts the
 * left edge, `hmm_to < hmm_length` the right one. When the states cannot
 * decide (unbound, or no HMM length for the right end and the left end is
 * whole), a coverage under `partialCoverage` marks the domain partial on an
 * unknown side.
 */
export function partialEdges(hit: DomainHit, partialCoverage = 0.9): PartialEdges {
  const left = hit.hmmFrom != null && hit.hmmFrom > 1;
  const right = hit.hmmTo != null && hit.hmmLength != null && hit.hmmTo < hit.hmmLength;
  if (left || right) return { left, right, unknown: false };
  const decided = hit.hmmFrom != null && hit.hmmTo != null && hit.hmmLength != null;
  if (decided) return FULL_MATCH;
  if (hit.coverage != null && hit.coverage < partialCoverage) {
    return { left: false, right: false, unknown: true };
  }
  return FULL_MATCH;
}

export function isPartial(edges: PartialEdges): boolean {
  return edges.left || edges.right || edges.unknown;
}

/** The fraction of the HMM a hit covers: the coverage column, else its states. */
export function hmmCoverage(hit: DomainHit): number | null {
  if (hit.coverage != null) return hit.coverage;
  if (hit.hmmFrom == null || hit.hmmTo == null || hit.hmmLength == null || hit.hmmLength <= 0) {
    return null;
  }
  const span = Math.abs(hit.hmmTo - hit.hmmFrom) + 1;
  return Math.max(0, Math.min(1, span / hit.hmmLength));
}

// ---------------------------------------------------------------------------
// Proteins, lanes, architectures
// ---------------------------------------------------------------------------

export interface ProteinLength {
  length: number;
  /** The length came from the protein length column, not from the last domain end. */
  known: boolean;
}

/**
 * Each protein's length: the largest protein length the table states, and in
 * any case at least the end of its last domain (a length shorter than a hit
 * is a data error, and the backbone must hold every domain). Read from every
 * hit, before filtering, so a filter never shortens a backbone.
 */
export function proteinLengths(hits: readonly DomainHit[]): Map<string, ProteinLength> {
  const out = new Map<string, ProteinLength>();
  for (const h of hits) {
    const prev = out.get(h.entity) ?? { length: 0, known: false };
    const stated = h.proteinLength != null && h.proteinLength > 0 ? h.proteinLength : null;
    out.set(h.entity, {
      length: Math.max(prev.length, h.end, stated ?? 0),
      known: prev.known || stated != null,
    });
  }
  return out;
}

/** Domain order on a protein: by start, then end, then label. */
export function compareDomains(a: DomainHit, b: DomainHit): number {
  return a.start - b.start || a.end - b.end || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0);
}

/**
 * Greedy interval partitioning of spans sorted by start: each span takes the
 * first lane whose last span ends before it starts (inclusive coordinates, so
 * `[1, 10]` and `[10, 20]` overlap). Returns each span's lane and the lane
 * count, at least 1 (the backbone's own lane).
 */
export function packLanes(spans: ReadonlyArray<{ start: number; end: number }>): {
  lanes: number[];
  count: number;
} {
  const laneEnds: number[] = [];
  const lanes: number[] = [];
  for (const s of spans) {
    let lane = laneEnds.findIndex((end) => end < s.start);
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(s.end);
    } else {
      laneEnds[lane] = s.end;
    }
    lanes.push(lane);
  }
  return { lanes, count: Math.max(1, laneEnds.length) };
}

/** The architecture of a protein: its domains' labels in start order. */
export function architectureString(
  domains: readonly DomainHit[],
  key: (hit: DomainHit) => string = (h) => h.label,
): string {
  return [...domains].sort(compareDomains).map(key).join(ARCHITECTURE_SEPARATOR);
}

export interface ProteinArch {
  entity: string;
  length: number;
  lengthKnown: boolean;
  /** Its hits in `compareDomains` order. */
  domains: DomainHit[];
  /** Lane of each domain, parallel to `domains`. */
  lanes: number[];
  laneCount: number;
  architecture: string;
}

/**
 * One protein per entity among `hits` (in first-appearance order), its
 * domains sorted, packed into lanes and named by architecture. `lengths`
 * comes from `proteinLengths` over the unfiltered hits.
 */
export function buildProteins(
  hits: readonly DomainHit[],
  lengths?: ReadonlyMap<string, ProteinLength>,
): ProteinArch[] {
  const byEntity = new Map<string, DomainHit[]>();
  for (const h of hits) {
    const list = byEntity.get(h.entity);
    if (list) list.push(h);
    else byEntity.set(h.entity, [h]);
  }
  const out: ProteinArch[] = [];
  for (const [entity, list] of byEntity) {
    const domains = list.slice().sort(compareDomains);
    const { lanes, count } = packLanes(domains);
    const lastEnd = domains.reduce((m, d) => Math.max(m, d.end), 0);
    const len = lengths?.get(entity);
    out.push({
      entity,
      length: Math.max(len?.length ?? 0, lastEnd),
      lengthKnown: len?.known ?? false,
      domains,
      lanes,
      laneCount: count,
      architecture: architectureString(domains),
    });
  }
  return out;
}

const ENTITY_COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/** Code-point order: deterministic whatever the locale. */
function compareCodePoints(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Proteins by architecture string, then entity (natural order); stable. */
export function sortProteins(proteins: readonly ProteinArch[]): ProteinArch[] {
  return proteins
    .map((p, i) => ({ p, i }))
    .sort(
      (a, b) =>
        compareCodePoints(a.p.architecture, b.p.architecture) ||
        ENTITY_COLLATOR.compare(a.p.entity, b.p.entity) ||
        a.i - b.i,
    )
    .map(({ p }) => p);
}

/**
 * The first `max` proteins, plus any of `mustInclude` the cap left out (a
 * protein picked elsewhere must stay on screen to be ringed), appended.
 */
export function capProteins(
  proteins: readonly ProteinArch[],
  max: number,
  mustInclude?: Iterable<string> | null,
): { shown: ProteinArch[]; total: number; capped: boolean } {
  const total = proteins.length;
  const limit = Math.max(1, Math.floor(max));
  if (total <= limit) return { shown: proteins.slice(), total, capped: false };
  const shown = proteins.slice(0, limit);
  const want = new Set(mustInclude ?? []);
  if (want.size) {
    for (const p of shown) want.delete(p.entity);
    if (want.size) {
      for (const p of proteins.slice(limit)) if (want.has(p.entity)) shown.push(p);
    }
  }
  return { shown, total, capped: true };
}

/** The median-length member (the lower median for an even count; ties by entity). */
export function representative(members: readonly ProteinArch[]): ProteinArch | null {
  if (!members.length) return null;
  const sorted = members
    .slice()
    .sort((a, b) => a.length - b.length || ENTITY_COLLATOR.compare(a.entity, b.entity));
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

export interface ArchitectureGroup {
  architecture: string;
  /** Members in natural entity order. */
  members: ProteinArch[];
  representative: ProteinArch;
}

export interface ArchitectureGrouping {
  /** The `max` most frequent architectures, by count then architecture string. */
  groups: ArchitectureGroup[];
  /** What the cap left out. */
  others: { architectures: number; proteins: number };
  /** Distinct architectures in all. */
  architectures: number;
  /** Proteins in all. */
  proteins: number;
}

/** Proteins grouped by architecture string, the `max` most frequent first. */
export function groupArchitectures(
  proteins: readonly ProteinArch[],
  max: number,
): ArchitectureGrouping {
  const byArch = new Map<string, ProteinArch[]>();
  for (const p of proteins) {
    const list = byArch.get(p.architecture);
    if (list) list.push(p);
    else byArch.set(p.architecture, [p]);
  }
  const all = Array.from(byArch.entries())
    .map(([architecture, members]) => ({ architecture, members }))
    .sort(
      (a, b) =>
        b.members.length - a.members.length || compareCodePoints(a.architecture, b.architecture),
    );
  const limit = Math.max(1, Math.floor(max));
  const top = all.slice(0, limit);
  const rest = all.slice(limit);
  return {
    groups: top.map(({ architecture, members }) => {
      const sorted = members.slice().sort((a, b) => ENTITY_COLLATOR.compare(a.entity, b.entity));
      return { architecture, members: sorted, representative: representative(sorted)! };
    }),
    others: {
      architectures: rest.length,
      proteins: rest.reduce((n, g) => n + g.members.length, 0),
    },
    architectures: all.length,
    proteins: proteins.length,
  };
}

/** How often each value of a hit field occurs, most frequent first (ties by
 *  value), the first `top` of them and how many distinct values are left. */
export function valueCounts(
  hits: readonly DomainHit[],
  key: (hit: DomainHit) => string,
  top: number,
): { items: { value: string; count: number }[]; more: number } {
  const counts = new Map<string, number>();
  for (const h of hits) {
    const k = key(h);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const sorted = Array.from(counts.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || compareCodePoints(a.value, b.value));
  const n = Math.max(0, Math.floor(top));
  return { items: sorted.slice(0, n), more: Math.max(0, sorted.length - n) };
}

/** The domain of `protein` in `lane` covering residue coordinate `pos` (a
 *  fractional residue, 0 at the start of residue 1), within `slack` residues;
 *  the narrowest wins. Index into `protein.domains`, or -1. */
export function domainAt(protein: ProteinArch, lane: number, pos: number, slack = 0): number {
  let best = -1;
  let bestWidth = Infinity;
  protein.domains.forEach((d, i) => {
    if (protein.lanes[i] !== lane) return;
    if (pos < d.start - 1 - slack || pos > d.end + slack) return;
    const w = d.end - d.start;
    if (w < bestWidth) {
      best = i;
      bestWidth = w;
    }
  });
  return best;
}

// ---------------------------------------------------------------------------
// Rows the panel draws
// ---------------------------------------------------------------------------

export type PanelRow =
  | { kind: 'protein'; key: string; protein: ProteinArch; indent: boolean }
  | { kind: 'group'; key: string; group: ArchitectureGroup; expanded: boolean }
  | { kind: 'note'; key: string; text: string };

/** Key of an architecture group's row. */
export function groupKey(architecture: string): string {
  return `arch:${architecture}`;
}

/** The proteins view: one row per protein. */
export function proteinRows(proteins: readonly ProteinArch[]): PanelRow[] {
  return proteins.map((p) => ({
    kind: 'protein',
    key: `p:${p.entity}`,
    protein: p,
    indent: false,
  }));
}

/**
 * The architectures view: one row per group drawn with its representative,
 * the members of an expanded group under it (at most `maxMembers`, then a
 * note), and a closing note for the architectures past the cap.
 */
export function architectureRows(
  grouping: ArchitectureGrouping,
  expanded: ReadonlySet<string>,
  maxMembers = 500,
): PanelRow[] {
  const rows: PanelRow[] = [];
  for (const group of grouping.groups) {
    const key = groupKey(group.architecture);
    const open = expanded.has(key);
    rows.push({ kind: 'group', key, group, expanded: open });
    if (!open) continue;
    for (const p of group.members.slice(0, maxMembers)) {
      rows.push({ kind: 'protein', key: `${key}|${p.entity}`, protein: p, indent: true });
    }
    const left = group.members.length - maxMembers;
    if (left > 0) {
      rows.push({
        kind: 'note',
        key: `${key}|more`,
        text: `${left.toLocaleString()} more protein${left === 1 ? '' : 's'} with this architecture`,
      });
    }
  }
  if (grouping.others.architectures > 0) {
    const a = grouping.others.architectures;
    const p = grouping.others.proteins;
    rows.push({
      kind: 'note',
      key: 'others',
      text: `${a.toLocaleString()} other architecture${a === 1 ? '' : 's'} (${p.toLocaleString()} protein${p === 1 ? '' : 's'})`,
    });
  }
  return rows;
}

export interface RowGeometry {
  /** Vertical padding above and below the lanes of a row. */
  padPx: number;
  /** Height of one domain lane. */
  lanePx: number;
  /** Height of a note row. */
  notePx: number;
}

/** Lane count a row draws. */
export function rowLanes(row: PanelRow): number {
  if (row.kind === 'protein') return row.protein.laneCount;
  if (row.kind === 'group') return row.group.representative.laneCount;
  return 0;
}

export function rowHeight(row: PanelRow, g: RowGeometry): number {
  if (row.kind === 'note') return g.notePx;
  return 2 * g.padPx + rowLanes(row) * g.lanePx;
}

/** Top offset of every row and the total height (`offsets[n]`). */
export function rowOffsets(heights: readonly number[]): Float64Array {
  const out = new Float64Array(heights.length + 1);
  for (let i = 0; i < heights.length; i++) out[i + 1] = out[i] + heights[i];
  return out;
}

/** Row at vertical offset `y` (binary search on `rowOffsets`), or -1. */
export function rowAt(offsets: Float64Array, y: number): number {
  const n = offsets.length - 1;
  if (n <= 0 || y < 0 || y >= offsets[n]) return -1;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (offsets[mid] <= y) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Rows intersecting `[scroll, scroll + viewport]`, plus `overscan` each side:
 *  `[first, last]` inclusive, or `[0, -1]` when there are none. */
export function rowWindow(
  offsets: Float64Array,
  scroll: number,
  viewport: number,
  overscan = 2,
): [number, number] {
  const n = offsets.length - 1;
  if (n <= 0 || viewport <= 0) return [0, -1];
  const total = offsets[n];
  const first = rowAt(offsets, Math.max(0, Math.min(scroll, total - 1)));
  const last = rowAt(offsets, Math.max(0, Math.min(scroll + viewport, total - 1)));
  if (first < 0 || last < 0) return [0, -1];
  return [Math.max(0, first - overscan), Math.min(n - 1, last + overscan)];
}

// ---------------------------------------------------------------------------
// Tooltip text
// ---------------------------------------------------------------------------

/** An E-value as people read them: `3.2e-15`, `0.012`, `0`. */
export function formatEvalue(v: number): string {
  if (v === 0) return '0';
  const a = Math.abs(v);
  if (a < 1e-3 || a >= 1e4) return v.toExponential(1).replace('e+', 'e');
  return String(Number(v.toPrecision(2)));
}

/** The tooltip's name for an E-value column (hmmsearch's two per-domain ones). */
export function evalueLabel(column: string | null | undefined): string {
  if (column === 'i_evalue') return 'i-Evalue';
  if (column === 'c_evalue') return 'c-Evalue';
  return 'E-value';
}

/** What a partial match's edges mean, in words; null for a full match. */
export function partialText(edges: PartialEdges): string | null {
  if (edges.left && edges.right) return 'Partial HMM match: both ends of the model missing';
  if (edges.left) return 'Partial HMM match: start of the model missing';
  if (edges.right) return 'Partial HMM match: end of the model missing';
  if (edges.unknown) return 'Partial HMM match (by coverage, side unknown)';
  return null;
}

/** The tooltip lines of one domain hit. */
export function domainTooltip(
  hit: DomainHit,
  edges: PartialEdges,
  opts: { evalueColumn?: string | null } = {},
): string[] {
  const lines: string[] = [];
  lines.push(
    hit.accession && hit.accession !== hit.label ? `${hit.label} (${hit.accession})` : hit.label,
  );
  if (hit.description) lines.push(hit.description);
  if (hit.source) lines.push(`Source ${hit.source}`);
  lines.push(`Envelope ${hit.start}-${hit.end} (${hit.end - hit.start + 1} aa)`);
  const cov = hmmCoverage(hit);
  const covText = cov != null ? ` (${Math.round(cov * 100)}% coverage)` : '';
  if (hit.hmmFrom != null && hit.hmmTo != null) {
    const of = hit.hmmLength != null ? ` of ${hit.hmmLength}` : '';
    lines.push(`HMM ${hit.hmmFrom}-${hit.hmmTo}${of}${covText}`);
  } else if (cov != null) {
    lines.push(`HMM coverage ${Math.round(cov * 100)}%`);
  }
  const partial = partialText(edges);
  if (partial) lines.push(partial);
  if (hit.evalue != null)
    lines.push(`${evalueLabel(opts.evalueColumn)} ${formatEvalue(hit.evalue)}`);
  if (hit.score != null) lines.push(`Score ${Number(hit.score.toFixed(1))} bits`);
  return lines;
}

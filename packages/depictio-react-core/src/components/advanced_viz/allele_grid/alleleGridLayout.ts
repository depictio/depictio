/**
 * Pure layout for the `allele_grid` kind: everything between the fetched rows
 * and the SVG, with no DOM and no theme, so every rule is unit-tested.
 *
 * - HLA nomenclature parsing (`HLA-A*02:01:01:01`, `A*02:01`, `A02:01`, the
 *   pre-2010 `A*0201`, expression suffixes such as `N`), truncated to the
 *   display resolution.
 * - Pairing a sample's calls at one locus into two haplotype slots, by the
 *   haplotype column when bound, else by row order; homozygosity is decided at
 *   the display resolution, so two calls that differ only past it merge.
 * - Locus order (the author's, then the conventional HLA order, grouped by
 *   class), sample order (name, value, or the alleles at one locus), and the
 *   `max_samples` / `max_loci` guards, which count what they leave out.
 * - Colours as indices: the allele group (first field) picks a hue family, the
 *   full allele a shade inside it. The renderer resolves both against the
 *   Mantine theme, so nothing here names a colour.
 */

/** The display resolution: how many nomenclature fields are kept. */
export type AlleleResolution = 1 | 2 | 3 | 4;

export interface ParsedAllele {
  /** The value as it came from the table. */
  raw: string;
  /** Gene without the `HLA-` prefix (`A`, `DRB1`), or null when the call
   *  carries none (`02:01`): the locus column then names it. */
  gene: string | null;
  /** The colon-separated fields, digits only (`['02', '01', '01']`). Empty
   *  when the value is not nomenclature at all; it is then shown as written. */
  fields: string[];
  /** Expression suffix (`N` null, `L` low, `Q` questionable...) or the `G` /
   *  `P` group designation, `''` when there is none. */
  suffix: string;
}

/** Values a typing tool writes for "no call". */
const NO_CALL = new Set(['', '-', '--', 'NA', 'N/A', 'NAN', 'NONE', 'NULL', 'NOCALL', 'NO_CALL', '.']);

/** HLA (and neighbouring MHC) genes, longest first so `DRB1` wins over `D`. */
const KNOWN_GENES: readonly string[] = [
  'DRB1', 'DRB2', 'DRB3', 'DRB4', 'DRB5', 'DRB6', 'DRB7', 'DRB8', 'DRB9',
  'DQA1', 'DQA2', 'DQB1', 'DQB2', 'DPA1', 'DPA2', 'DPB1', 'DPB2',
  'MICA', 'MICB', 'TAP1', 'TAP2',
  'DRA', 'DMA', 'DMB', 'DOA', 'DOB',
  'A', 'B', 'C', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'V',
];

/** Column order a reader expects: class I classical, class I non-classical,
 *  then class II by the DR, DQ, DP convention. */
export const CANONICAL_LOCUS_ORDER: readonly string[] = [
  'A', 'B', 'C', 'E', 'F', 'G',
  'DRA', 'DRB1', 'DRB3', 'DRB4', 'DRB5',
  'DQA1', 'DQB1', 'DPA1', 'DPB1',
  'DMA', 'DMB', 'DOA', 'DOB', 'MICA', 'MICB',
];

const SUFFIX_RE = /^(.*?\d)([NLSCAQGP])$/;

/** A locus name as the grid keys it: trimmed, upper case, `HLA-` dropped. */
export function normaliseLocus(raw: unknown): string {
  if (raw === null || raw === undefined) return '';
  return String(raw).trim().toUpperCase().replace(/^HLA[-_\s]?/, '');
}

/** Old four-, six- or eight-digit names (`0201`, `020101`) as 2-digit fields. */
function splitCompactDigits(digits: string): string[] {
  if (digits.length % 2 !== 0 || digits.length < 4) return [digits];
  const out: string[] = [];
  for (let i = 0; i < digits.length; i += 2) out.push(digits.slice(i, i + 2));
  return out;
}

/**
 * Read one allele call. Null for an empty cell or a tool's "no call" marker;
 * otherwise always a value, with empty `fields` for text that is not
 * nomenclature, which the grid shows as written rather than dropping a call.
 */
export function parseAllele(value: unknown): ParsedAllele | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  const raw = String(value).trim();
  if (NO_CALL.has(raw.toUpperCase())) return null;

  let text = raw.toUpperCase().replace(/\s+/g, '').replace(/^HLA[-_]?/, '');
  let gene: string | null = null;
  let rest: string;
  const star = text.indexOf('*');
  if (star >= 0) {
    gene = text.slice(0, star) || null;
    rest = text.slice(star + 1);
  } else {
    const known = KNOWN_GENES.find((g) => text.startsWith(g) && /^\d/.test(text.slice(g.length)));
    if (known) {
      gene = known;
      rest = text.slice(known.length);
    } else {
      const m = /^([A-Z][A-Z0-9]*?)(\d{2,}(?::.*)?)$/.exec(text);
      if (m && /[A-Z]/.test(m[1])) {
        gene = m[1];
        rest = m[2];
      } else {
        rest = text;
      }
    }
  }
  text = rest;

  let suffix = '';
  const sm = SUFFIX_RE.exec(text);
  if (sm) {
    text = sm[1];
    suffix = sm[2];
  }
  const parts = text.includes(':') ? text.split(':') : splitCompactDigits(text);
  const fields = parts.every((p) => /^\d{1,4}$/.test(p)) && parts.length > 0 ? parts : [];
  if (fields.length === 0) return { raw, gene: null, fields: [], suffix: '' };
  return { raw, gene, fields, suffix };
}

/**
 * The allele as the grid writes it at `resolution` fields: `A*02:01`. The
 * expression suffix survives only when no field is cut, since it qualifies
 * the full name (`A*24:09N` stays null at 2 fields, not at 1).
 */
export function formatAllele(
  allele: ParsedAllele,
  resolution: AlleleResolution,
  withGene = true,
): string {
  if (allele.fields.length === 0) return allele.raw;
  const kept = allele.fields.slice(0, Math.max(1, resolution));
  const suffix = allele.fields.length <= kept.length ? allele.suffix : '';
  const body = `${kept.join(':')}${suffix}`;
  return withGene && allele.gene ? `${allele.gene}*${body}` : body;
}

/** The allele group (first field), the key of a hue family: `A*02`. */
export function alleleGroup(allele: ParsedAllele, locus?: string): string {
  if (allele.fields.length === 0) return allele.raw;
  const gene = allele.gene ?? (locus ? normaliseLocus(locus) : '');
  return gene ? `${gene}*${allele.fields[0]}` : allele.fields[0];
}

/**
 * Which half a call fills, from the haplotype column: 1 or 2 as a number, or a
 * string ending in one (`A1`, `hap2`, `2`). Null for anything else, which
 * falls back to row order.
 */
export function parseHaplotype(value: unknown): 1 | 2 | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return value === 1 ? 1 : value === 2 ? 2 : null;
  const m = /([12])\s*$/.exec(String(value));
  return m ? (m[1] === '1' ? 1 : 2) : null;
}

/** Natural order: `S2` before `S10`, `A*02:01` before `A*11:01`. */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

// ---------------------------------------------------------------------------
// Rows to cells
// ---------------------------------------------------------------------------

export interface AlleleRow {
  /** Index into the fetched frame. */
  row: number;
  sample: string;
  locus: string;
  allele: ParsedAllele | null;
  haplotype: 1 | 2 | null;
  category: string | null;
  value: number | null;
  reads: number | null;
}

export interface AlleleColumns {
  sample: string;
  locus: string;
  allele: string;
  haplotype?: string | null;
  category?: string | null;
  value?: string | null;
  reads?: string | null;
}

const finiteOrNull = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

const textOrNull = (v: unknown): string | null => {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s ? s : null;
};

/**
 * The fetched columns as rows. A row with no sample is dropped; a row with no
 * locus takes the gene its allele names, and is dropped when it names none.
 */
export function parseAlleleRows(
  columns: Record<string, unknown[]>,
  cols: AlleleColumns,
): AlleleRow[] {
  const samples = columns[cols.sample] ?? [];
  const loci = columns[cols.locus] ?? [];
  const alleles = columns[cols.allele] ?? [];
  const pick = (name: string | null | undefined) => (name ? (columns[name] ?? null) : null);
  const haps = pick(cols.haplotype);
  const cats = pick(cols.category);
  const values = pick(cols.value);
  const reads = pick(cols.reads);
  const n = Math.max(samples.length, loci.length, alleles.length);
  const out: AlleleRow[] = [];
  for (let i = 0; i < n; i++) {
    const sample = textOrNull(samples[i]);
    if (!sample) continue;
    const allele = parseAllele(alleles[i]);
    const locus = normaliseLocus(loci[i]) || allele?.gene || '';
    if (!locus) continue;
    out.push({
      row: i,
      sample,
      locus,
      allele,
      haplotype: haps ? parseHaplotype(haps[i]) : null,
      category: cats ? textOrNull(cats[i]) : null,
      value: values ? finiteOrNull(values[i]) : null,
      reads: reads ? finiteOrNull(reads[i]) : null,
    });
  }
  return out;
}

export interface AlleleCall {
  allele: ParsedAllele;
  /** The allele at the display resolution, with its gene: the legend key. */
  label: string;
  /** Allele group at the display resolution's first field. */
  group: string;
  row: number;
}

export interface GenotypeCell {
  sample: string;
  locus: string;
  /** Haplotype 1 and 2; null where the table holds no call for that half. */
  haplotypes: [AlleleCall | null, AlleleCall | null];
  /** Both halves called and equal at the display resolution. */
  homozygous: boolean;
  /** Calls past the second for this sample and locus, left out. */
  extra: number;
}

export interface SampleInfo {
  sample: string;
  value: number | null;
  reads: number | null;
}

export interface LocusInfo {
  locus: string;
  category: string | null;
}

export interface LocusGroup {
  category: string | null;
  /** Index of the first and one past the last column of the run. */
  start: number;
  end: number;
}

export interface LegendEntry {
  locus: string;
  label: string;
  group: string;
  /** Haplotype copies of this allele among the typed samples. */
  copies: number;
  /** Samples carrying at least one copy. */
  carriers: number;
  /** Copies over twice the samples typed at the locus. */
  frequency: number;
}

export interface AlleleGridOptions {
  resolution: AlleleResolution;
  locusOrder?: readonly string[] | null;
  sampleOrder?: 'alphabetical' | 'value' | 'allele';
  /** Locus whose alleles order the rows under `sampleOrder: 'allele'`. */
  orderLocus?: string | null;
  maxSamples?: number;
  maxLoci?: number;
}

export interface AlleleGrid {
  samples: SampleInfo[];
  loci: LocusInfo[];
  /** Runs of adjacent columns sharing a category, for the header band. */
  groups: LocusGroup[];
  /** `cellKey(sample, locus)` to its genotype. */
  cells: Map<string, GenotypeCell>;
  /** Per locus, alleles by frequency (highest first), over every sample. */
  legend: LegendEntry[];
  /** Samples and loci the guards left out. */
  droppedSamples: number;
  droppedLoci: number;
  /** Cells with more than two calls (a third row for one sample and locus). */
  overfull: number;
}

export const cellKey = (sample: string, locus: string): string => `${sample}\u0000${locus}`;

function toCall(row: AlleleRow, resolution: AlleleResolution): AlleleCall | null {
  if (!row.allele) return null;
  const allele = row.allele.gene ? row.allele : { ...row.allele, gene: row.allele.fields.length ? row.locus : null };
  return {
    allele,
    label: formatAllele(allele, resolution),
    group: alleleGroup(allele, row.locus),
    row: row.row,
  };
}

/**
 * Pair one sample's rows at one locus into two halves. Calls that name their
 * haplotype take that half; the rest fill the free halves in table order. A
 * row with no call still takes its half (an explicit `-` for haplotype 2
 * leaves haplotype 2 empty rather than letting a later call slide in).
 */
export function pairHaplotypes(
  rows: readonly AlleleRow[],
  resolution: AlleleResolution,
): { haplotypes: [AlleleCall | null, AlleleCall | null]; extra: number } {
  const slots: [AlleleCall | null, AlleleCall | null] = [null, null];
  const taken: [boolean, boolean] = [false, false];
  const pending: AlleleRow[] = [];
  for (const row of rows) {
    const slot: 0 | 1 | null = row.haplotype === 1 ? 0 : row.haplotype === 2 ? 1 : null;
    if (slot !== null && !taken[slot]) {
      slots[slot] = toCall(row, resolution);
      taken[slot] = true;
    } else {
      pending.push(row);
    }
  }
  let extra = 0;
  for (const row of pending) {
    const free: 0 | 1 | null = taken[0] ? (taken[1] ? null : 1) : 0;
    if (free === null) {
      if (row.allele) extra += 1;
      continue;
    }
    slots[free] = toCall(row, resolution);
    taken[free] = true;
  }
  return { haplotypes: slots, extra };
}

function canonicalRank(locus: string): number {
  const i = CANONICAL_LOCUS_ORDER.indexOf(locus);
  return i < 0 ? CANONICAL_LOCUS_ORDER.length : i;
}

/** Column order: the author's list first, then category, the conventional HLA
 *  order, and the name. */
export function orderLoci(
  loci: readonly LocusInfo[],
  locusOrder?: readonly string[] | null,
): LocusInfo[] {
  const authored = (locusOrder ?? []).map(normaliseLocus).filter(Boolean);
  const rankOf = (l: string) => {
    const i = authored.indexOf(l);
    return i < 0 ? authored.length : i;
  };
  return [...loci].sort((a, b) => {
    const ra = rankOf(a.locus);
    const rb = rankOf(b.locus);
    if (ra !== rb) return ra - rb;
    if (ra < authored.length) return 0;
    const ca = a.category ?? '￿';
    const cb = b.category ?? '￿';
    if (ca !== cb) return naturalCompare(ca, cb);
    const ka = canonicalRank(a.locus);
    const kb = canonicalRank(b.locus);
    if (ka !== kb) return ka - kb;
    return naturalCompare(a.locus, b.locus);
  });
}

/** Runs of adjacent columns sharing a category. Empty when no locus has one. */
export function locusGroups(loci: readonly LocusInfo[]): LocusGroup[] {
  if (!loci.some((l) => l.category)) return [];
  const out: LocusGroup[] = [];
  loci.forEach((l, i) => {
    const last = out[out.length - 1];
    if (last && last.category === l.category) last.end = i + 1;
    else out.push({ category: l.category, start: i, end: i + 1 });
  });
  return out;
}

/** Per locus, every allele with its copies, carriers and frequency. */
export function alleleFrequencies(
  cells: Iterable<GenotypeCell>,
  loci: readonly string[],
): LegendEntry[] {
  const typed = new Map<string, number>();
  const byKey = new Map<string, LegendEntry>();
  for (const cell of cells) {
    const calls = cell.haplotypes.filter((c): c is AlleleCall => c !== null);
    if (calls.length === 0) continue;
    typed.set(cell.locus, (typed.get(cell.locus) ?? 0) + 1);
    const seen = new Set<string>();
    for (const call of calls) {
      const key = cellKey(cell.locus, call.label);
      let entry = byKey.get(key);
      if (!entry) {
        entry = { locus: cell.locus, label: call.label, group: call.group, copies: 0, carriers: 0, frequency: 0 };
        byKey.set(key, entry);
      }
      entry.copies += 1;
      if (!seen.has(call.label)) {
        entry.carriers += 1;
        seen.add(call.label);
      }
    }
  }
  const order = new Map(loci.map((l, i) => [l, i]));
  const entries = [...byKey.values()];
  for (const e of entries) e.frequency = e.copies / (2 * (typed.get(e.locus) ?? 1));
  return entries.sort((a, b) => {
    const la = order.get(a.locus) ?? loci.length;
    const lb = order.get(b.locus) ?? loci.length;
    if (la !== lb) return la - lb;
    if (a.copies !== b.copies) return b.copies - a.copies;
    return naturalCompare(a.label, b.label);
  });
}

/** Row order. Ties and missing values always fall back to the sample name. */
export function orderSamples(
  samples: readonly SampleInfo[],
  cells: Map<string, GenotypeCell>,
  legend: readonly LegendEntry[],
  mode: 'alphabetical' | 'value' | 'allele',
  orderLocus: string | null,
): SampleInfo[] {
  const byName = (a: SampleInfo, b: SampleInfo) => naturalCompare(a.sample, b.sample);
  if (mode === 'value') {
    return [...samples].sort((a, b) => {
      if (a.value === null && b.value === null) return byName(a, b);
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      return b.value - a.value || byName(a, b);
    });
  }
  if (mode === 'allele' && orderLocus) {
    // Carriers of the commonest allele first, then the next, so a block of
    // rows shares a colour down the ordering column.
    const rank = new Map<string, number>();
    legend
      .filter((e) => e.locus === orderLocus)
      .forEach((e, i) => rank.set(e.label, i));
    const keyOf = (s: SampleInfo): number[] => {
      const cell = cells.get(cellKey(s.sample, orderLocus));
      const calls: (AlleleCall | null)[] = cell ? [...cell.haplotypes] : [];
      const ranks = calls
        .filter((c): c is AlleleCall => c !== null)
        .map((c) => rank.get(c.label) ?? Number.MAX_SAFE_INTEGER)
        .sort((a, b) => a - b);
      if (ranks.length === 0) return [Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER];
      return [ranks[0], ranks[1] ?? ranks[0]];
    };
    const keys = new Map(samples.map((s) => [s.sample, keyOf(s)]));
    return [...samples].sort((a, b) => {
      const ka = keys.get(a.sample)!;
      const kb = keys.get(b.sample)!;
      return ka[0] - kb[0] || ka[1] - kb[1] || byName(a, b);
    });
  }
  return [...samples].sort(byName);
}

/** Largest finite value of a sample's rows: the per-sample columns of a long
 *  table repeat the same number on every row. */
const maxOf = (current: number | null, next: number | null): number | null =>
  next === null ? current : current === null ? next : Math.max(current, next);

/** The whole grid: cells, ordered and guarded axes, legend. */
export function buildAlleleGrid(rows: readonly AlleleRow[], options: AlleleGridOptions): AlleleGrid {
  const resolution = options.resolution;
  const groups = new Map<string, AlleleRow[]>();
  const sampleInfo = new Map<string, SampleInfo>();
  const locusInfo = new Map<string, LocusInfo>();
  for (const row of rows) {
    const key = cellKey(row.sample, row.locus);
    const list = groups.get(key);
    if (list) list.push(row);
    else groups.set(key, [row]);
    const s = sampleInfo.get(row.sample) ?? { sample: row.sample, value: null, reads: null };
    s.value = maxOf(s.value, row.value);
    s.reads = maxOf(s.reads, row.reads);
    sampleInfo.set(row.sample, s);
    const l = locusInfo.get(row.locus);
    if (!l) locusInfo.set(row.locus, { locus: row.locus, category: row.category });
    else if (!l.category && row.category) l.category = row.category;
  }

  const cells = new Map<string, GenotypeCell>();
  let overfull = 0;
  for (const [key, list] of groups) {
    const { haplotypes, extra } = pairHaplotypes(list, resolution);
    if (extra > 0) overfull += 1;
    const [h1, h2] = haplotypes;
    cells.set(key, {
      sample: list[0].sample,
      locus: list[0].locus,
      haplotypes,
      homozygous: h1 !== null && h2 !== null && h1.label === h2.label,
      extra,
    });
  }

  const allLoci = orderLoci([...locusInfo.values()], options.locusOrder);
  const legend = alleleFrequencies(
    cells.values(),
    allLoci.map((l) => l.locus),
  );
  const maxLoci = Math.max(1, options.maxLoci ?? allLoci.length);
  const loci = allLoci.slice(0, maxLoci);

  const orderLocus =
    (options.orderLocus && normaliseLocus(options.orderLocus)) || loci[0]?.locus || null;
  const allSamples = orderSamples(
    [...sampleInfo.values()],
    cells,
    legend,
    options.sampleOrder ?? 'alphabetical',
    orderLocus,
  );
  const maxSamples = Math.max(1, options.maxSamples ?? allSamples.length);
  const samples = allSamples.slice(0, maxSamples);

  return {
    samples,
    loci,
    groups: locusGroups(loci),
    cells,
    legend,
    droppedSamples: allSamples.length - samples.length,
    droppedLoci: allLoci.length - loci.length,
    overfull,
  };
}

// ---------------------------------------------------------------------------
// Colours, as indices into the theme
// ---------------------------------------------------------------------------

export interface AlleleShade {
  /** Index into the renderer's hue list. */
  hue: number;
  /** Mantine shade, 0 (lightest) to 9. */
  shade: number;
}

/** Shades per rank inside a group, spread so neighbours differ: the first
 *  allele of a group sits on the scheme's base shade (6 on light, 4 on dark,
 *  the same base `mantineCategoricalPalette` uses). */
const LIGHT_LADDER = [6, 4, 8, 3, 7, 5, 9, 2] as const;
const DARK_LADDER = [4, 2, 6, 3, 5, 1, 7, 8] as const;

export function shadeForRank(rank: number, isDark: boolean): number {
  const ladder = isDark ? DARK_LADDER : LIGHT_LADDER;
  return ladder[((rank % ladder.length) + ladder.length) % ladder.length];
}

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

export interface ColourUniverseEntry {
  /** Gene (or locus) the allele belongs to. */
  gene: string;
  group: string;
  label: string;
}

/**
 * The universe of alleles the colours are assigned over: every value of the
 * allele column the collection holds (`uniqueValues`, so a filter that drops
 * an allele does not repaint the others) plus whatever the rows on screen
 * carry, at the display resolution.
 */
export function colourUniverse(
  uniqueValues: readonly unknown[] | null,
  calls: Iterable<AlleleCall>,
  resolution: AlleleResolution,
): ColourUniverseEntry[] {
  const out = new Map<string, ColourUniverseEntry>();
  const add = (allele: ParsedAllele, gene: string) => {
    const withGene = allele.gene ? allele : { ...allele, gene };
    const label = formatAllele(withGene, resolution);
    if (!out.has(label)) out.set(label, { gene, group: alleleGroup(withGene, gene), label });
  };
  for (const v of uniqueValues ?? []) {
    const parsed = parseAllele(v);
    // A gene-less value cannot be placed in a family until a row names its
    // locus; the rows below add it.
    if (parsed && parsed.fields.length > 0 && parsed.gene) add(parsed, parsed.gene);
  }
  for (const call of calls) add(call.allele, call.allele.gene ?? '');
  return [...out.values()];
}

/**
 * Hue family per allele group and shade per allele.
 *
 * Within one gene the groups are taken in natural order and given consecutive
 * hues from an offset hashed from the gene's name, so two groups of the same
 * locus never share a hue (until a locus has more groups than there are
 * hues) and the assignment does not depend on which other loci are drawn.
 * Inside a group the alleles, in natural order, walk the shade ladder.
 */
export function assignAlleleShades(
  universe: readonly ColourUniverseEntry[],
  hueCount: number,
  isDark: boolean,
): Map<string, AlleleShade> {
  const hues = Math.max(1, Math.floor(hueCount));
  const byGene = new Map<string, Map<string, string[]>>();
  for (const e of universe) {
    const groups = byGene.get(e.gene) ?? new Map<string, string[]>();
    const labels = groups.get(e.group) ?? [];
    if (!labels.includes(e.label)) labels.push(e.label);
    groups.set(e.group, labels);
    byGene.set(e.gene, groups);
  }
  const out = new Map<string, AlleleShade>();
  for (const [gene, groups] of byGene) {
    const offset = hashString(gene) % hues;
    [...groups.keys()].sort(naturalCompare).forEach((group, gi) => {
      const hue = (offset + gi) % hues;
      [...(groups.get(group) ?? [])].sort(naturalCompare).forEach((label, ai) => {
        out.set(label, { hue, shade: shadeForRank(ai, isDark) });
      });
    });
  }
  return out;
}

/**
 * Whether text on `colour` should be light or dark, by its relative
 * luminance. Takes `#rgb`, `#rrggbb` and `rgb(...)`; anything else reads as a
 * light background, which is what dark text is safe on.
 */
export function inkFor(colour: string): 'light' | 'dark' {
  let r: number;
  let g: number;
  let b: number;
  const c = colour.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c);
  const rgb = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(c);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, (x) => x + x) : hex[1];
    r = parseInt(h.slice(0, 2), 16);
    g = parseInt(h.slice(2, 4), 16);
    b = parseInt(h.slice(4, 6), 16);
  } else if (rgb) {
    [r, g, b] = [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  } else {
    return 'dark';
  }
  const lin = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  // The crossover where white and black text have equal contrast.
  return luminance > 0.179 ? 'dark' : 'light';
}

// ---------------------------------------------------------------------------
// Geometry and labels
// ---------------------------------------------------------------------------

/** Width of one character at `fontPx`: digits and capitals in the UI font. */
export const CHAR_WIDTH_EM = 0.6;

/**
 * The text a half of `widthPx` can hold: the allele with its gene, without
 * it (the column header names the locus), or nothing.
 */
export function fitAlleleLabel(
  call: AlleleCall,
  widthPx: number,
  fontPx: number,
  resolution: AlleleResolution,
  paddingPx = 4,
): string | null {
  const room = widthPx - 2 * paddingPx;
  const fits = (s: string) => s.length * fontPx * CHAR_WIDTH_EM <= room;
  const full = call.label;
  if (fits(full)) return full;
  const bare = formatAllele(call.allele, resolution, false);
  if (bare !== full && fits(bare)) return bare;
  return null;
}

export interface GridGeometryInput {
  width: number;
  nLoci: number;
  /** Longest sample name, in characters. */
  sampleLabelChars: number;
  sideBars: number;
  fontPx?: number;
}

export interface GridGeometry {
  labelWidth: number;
  cellWidth: number;
  barWidth: number;
  /** Total drawn width: may exceed `width` when the cells hit their minimum. */
  totalWidth: number;
}

export const MIN_CELL_PX = 28;
export const MAX_CELL_PX = 150;
export const BAR_PX = 56;
const LABEL_MIN_PX = 48;
const LABEL_MAX_PX = 180;

/** Column widths for a container `width` px wide. */
export function gridGeometry(input: GridGeometryInput): GridGeometry {
  const font = input.fontPx ?? 11;
  const labelWidth = Math.min(
    LABEL_MAX_PX,
    Math.max(LABEL_MIN_PX, Math.ceil(input.sampleLabelChars * font * CHAR_WIDTH_EM) + 10),
  );
  const barWidth = BAR_PX;
  const bars = Math.max(0, input.sideBars) * (barWidth + 6);
  const nLoci = Math.max(1, input.nLoci);
  const free = Math.max(0, input.width - labelWidth - bars);
  const cellWidth = Math.min(MAX_CELL_PX, Math.max(MIN_CELL_PX, Math.floor(free / nLoci)));
  return {
    labelWidth,
    cellWidth,
    barWidth,
    totalWidth: labelWidth + nLoci * cellWidth + bars,
  };
}

/** The sentence a hover states about one cell. */
export function cellSummary(cell: GenotypeCell): string {
  const [h1, h2] = cell.haplotypes;
  const name = (c: AlleleCall | null) => (c ? c.label : 'no call');
  if (cell.homozygous) return `${cell.sample} · ${cell.locus} · ${name(h1)} (homozygous)`;
  return `${cell.sample} · ${cell.locus} · ${name(h1)} / ${name(h2)}`;
}

/** Raw values of the allele column whose display label is `label`: what an
 *  allele pick filters on, so a pick at 2 fields keeps every 3-field call
 *  that truncates to it. */
export function rawValuesForLabel(cells: Iterable<GenotypeCell>, label: string): string[] {
  const out = new Set<string>();
  for (const cell of cells) {
    for (const call of cell.haplotypes) {
      if (call && call.label === label) out.add(call.allele.raw);
    }
  }
  return [...out].sort(naturalCompare);
}

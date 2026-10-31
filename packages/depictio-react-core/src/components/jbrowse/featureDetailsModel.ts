/**
 * Pure helpers behind the genome browser's feature panel (`FeatureDetails`).
 *
 * JBrowse hands a clicked feature to a widget as plain JSON (`featureData`);
 * `buildFeatureView` turns that JSON into a small view model (header, facts,
 * chips, tables, "all fields") that the panel draws with Mantine. Nothing here
 * touches React or JBrowse, so every format rule is covered by unit tests.
 *
 * The JSON shapes come from JBrowse 4.3: a VCF feature is `@gmod/vcf`'s
 * `Variant.toJSON()` plus `samples`; a BAM/CRAM read is `BamSlightlyLazyFeature`
 * (`CIGAR`, `flags`, `tags`...); GFF/BED/UCSC features are a `SimpleFeature`
 * with lower-cased attributes and `subfeatures`.
 */

/** Widget types JBrowse opens for a clicked feature; every other widget (track
 *  config, about-track...) keeps JBrowse's own dialog. */
export const FEATURE_WIDGET_TYPES = [
  'BaseFeatureWidget',
  'VariantFeatureWidget',
  'AlignmentsFeatureWidget',
] as const;

export function isFeatureWidgetType(type: unknown): boolean {
  return typeof type === 'string' && (FEATURE_WIDGET_TYPES as readonly string[]).includes(type);
}

export type Tone = 'red' | 'orange' | 'yellow' | 'green' | 'blue' | 'violet' | 'teal' | 'gray';

export interface Fact {
  label: string;
  value: string;
  /** Drawn as a badge of this colour instead of plain text. */
  tone?: Tone;
  mono?: boolean;
  hint?: string;
}

export interface Chip {
  text: string;
  tone?: Tone;
  hint?: string;
}

export interface ChipGroup {
  label: string;
  chips: Chip[];
}

export interface AnnotationRow {
  gene: string;
  consequence: string;
  impact: string;
  impactTone: Tone;
  hgvsc: string;
  hgvsp: string;
  /** Untrimmed HGVS strings (transcript prefix kept), for the tooltip. */
  hgvscFull: string;
  hgvspFull: string;
}

export type Zygosity = 'homref' | 'het' | 'homalt' | 'nocall';

export interface GenotypeRow {
  sample: string;
  gt: string;
  zygosity: Zygosity;
  zygosityLabel: string;
  tone: Tone;
  dp: string;
  gq: string;
  ad: string;
  vaf: string;
}

export interface FieldRow {
  key: string;
  value: string;
}

export interface FeatureView {
  kind: 'variant' | 'alignment' | 'feature';
  title: string;
  subtitle?: string;
  typeLabel: string;
  /** `chr:1,234-5,678`, 1-based. */
  locus: string;
  facts: Fact[];
  /** Free text under the facts (a gene's description). */
  description?: string;
  chips: ChipGroup[];
  annotations: AnnotationRow[];
  annotationSource?: 'CSQ' | 'ANN';
  genotypes: GenotypeRow[];
  /** Every key the panel did not draw above, as key / value rows. */
  fields: FieldRow[];
}

export interface BuildContext {
  /** `CoreGetMetadata` of the track's adapter: the VCF header (`INFO.CSQ.Description`). */
  descriptions?: unknown;
  widgetType?: string;
}

type Rec = Record<string, unknown>;

const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);

/** `[]` for nothing, the array itself, else a one-element array. */
function asArray(v: unknown): unknown[] {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

const present = (v: unknown): boolean =>
  v !== undefined && v !== null && v !== '' && v !== '.' && !(Array.isArray(v) && v.length === 0);

export function toNum(v: unknown): number | undefined {
  if (typeof v === 'number') return Number.isFinite(v) ? v : undefined;
  if (typeof v === 'string' && v.trim() !== '' && v.trim() !== '.') {
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  }
  return undefined;
}

const NF = new Intl.NumberFormat('en-US', { maximumFractionDigits: 20 });

/** Integers with thousands separators. */
export function formatInt(n: number): string {
  return NF.format(Math.round(n));
}

/** `1.2e-4` style for tiny values: JS' own `toExponential`, minus a trailing `.0`. */
function sci(n: number): string {
  return n.toExponential(1).replace('.0e', 'e');
}

/** A general number: integers grouped, decimals trimmed to what is readable,
 *  tiny values in scientific notation. */
export function formatNumber(n: number): string {
  if (Number.isInteger(n)) return formatInt(n);
  const a = Math.abs(n);
  if (a < 0.001) return sci(n);
  const digits = a >= 100 ? 1 : a >= 1 ? 2 : 4;
  return n.toLocaleString('en-US', { maximumFractionDigits: digits });
}

/** An allele frequency: scientific below 0.001, three significant digits above. */
export function formatFrequency(n: number): string {
  if (n === 0) return '0';
  if (Math.abs(n) < 0.001) return sci(n);
  return n.toLocaleString('en-US', { maximumSignificantDigits: 3 });
}

/** `chr:start-end` from a 0-based half-open JBrowse interval; a 1 bp feature
 *  is a single position. */
export function formatLocus(refName: string, start0: number, end: number): string {
  const start = start0 + 1;
  return end <= start ? `${refName}:${formatInt(start)}` : `${refName}:${formatInt(start)}-${formatInt(end)}`;
}

/** `chr:1234` (an adapter's mate position) with the position grouped. */
function formatMate(raw: string): string {
  const m = /^(.*):(\d+)$/.exec(raw);
  return m ? `${m[1]}:${formatInt(Number(m[2]))}` : raw;
}

const clean = (s: string): string => s.replace(/_/g, ' ');

/** `missense_variant&splice_region_variant` -> `missense variant, splice region variant`. */
export function formatConsequence(raw: string): string {
  return raw
    .split(/[&,]/)
    .map((p) => clean(p).trim())
    .filter(Boolean)
    .join(', ');
}

const upperFirst = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);

function scalarText(v: unknown): string {
  if (typeof v === 'number') return formatNumber(v);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  return String(v);
}

/** One cell of the "All fields" list: arrays joined with ", ", objects as JSON. */
export function stringifyValue(v: unknown): string {
  if (Array.isArray(v)) return v.filter((x) => x != null).map(stringifyValue).join(', ');
  if (isRec(v)) return JSON.stringify(v);
  return scalarText(v);
}

/** Reads a record by case-insensitive key and remembers which keys were read. */
class Reader {
  readonly used = new Set<string>();
  private readonly byLower = new Map<string, string>();

  constructor(readonly data: Rec) {
    for (const k of Object.keys(data)) {
      const l = k.toLowerCase();
      if (!this.byLower.has(l)) this.byLower.set(l, k);
    }
  }

  /** First of `names` that holds a value; only that key is marked consumed,
   *  so an alias carrying a different value still reaches "All fields". */
  take(...names: string[]): unknown {
    for (const n of names) {
      const key = this.byLower.get(n.toLowerCase());
      if (key === undefined || !present(this.data[key])) continue;
      this.used.add(key);
      return this.data[key];
    }
    return undefined;
  }

  text(...names: string[]): string | undefined {
    const v = this.take(...names);
    return v === undefined ? undefined : stringifyValue(v);
  }

  /** Marks keys consumed without reading them. */
  skip(...names: string[]): void {
    for (const n of names) {
      const key = this.byLower.get(n.toLowerCase());
      if (key !== undefined) this.used.add(key);
    }
  }
}

/** Key / value rows for everything not in `used`. Nested records in
 *  `inlineKeys` (INFO, tags...) are flattened without a prefix, other ones with a dotted one. */
export function collectFields(data: Rec, used: ReadonlySet<string>, inlineKeys: string[] = []): FieldRow[] {
  const rows: FieldRow[] = [];
  const inline = new Set(inlineKeys.map((k) => k.toLowerCase()));
  const add = (key: string, v: unknown) => {
    if (!present(v)) return;
    if (isRec(v)) {
      for (const [k, x] of Object.entries(v)) add(inline.has(key.toLowerCase()) ? k : `${key}.${k}`, x);
      return;
    }
    if (Array.isArray(v) && v.every((x) => x == null)) return;
    rows.push({ key, value: stringifyValue(v) });
  };
  for (const [k, v] of Object.entries(data)) {
    if (used.has(k) || k.startsWith('__')) continue;
    add(k, v);
  }
  return rows;
}

// ---- VCF annotations --------------------------------------------------------

export const VEP_DEFAULT_FIELDS = [
  'Allele', 'Consequence', 'IMPACT', 'SYMBOL', 'Gene', 'Feature_type', 'Feature', 'BIOTYPE',
  'EXON', 'INTRON', 'HGVSc', 'HGVSp',
];

export const SNPEFF_DEFAULT_FIELDS = [
  'Allele', 'Annotation', 'Annotation_Impact', 'Gene_Name', 'Gene_ID', 'Feature_Type',
  'Feature_ID', 'Transcript_BioType', 'Rank', 'HGVS.c', 'HGVS.p',
];

/** The pipe-separated field names a VCF header declares for an INFO annotation
 *  (`##INFO=<ID=CSQ,...,Description="... Format: Allele|Consequence|...">` for
 *  VEP, `Functional annotations: 'Allele | Annotation | ...'` for snpEff). */
export function parseAnnotationFormat(descriptions: unknown, key: 'CSQ' | 'ANN'): string[] | undefined {
  if (!isRec(descriptions) || !isRec(descriptions.INFO)) return undefined;
  const entry = descriptions.INFO[key];
  const desc = isRec(entry) ? entry.Description : undefined;
  if (typeof desc !== 'string') return undefined;
  const m = /(?:format|annotations)\s*:\s*['"]?(.+?)['"]?\s*$/i.exec(desc);
  if (!m || !m[1].includes('|')) return undefined;
  return m[1].split('|').map((s) => s.trim());
}

const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]/g, '');

const IMPACT_ORDER: Record<string, number> = { HIGH: 0, MODERATE: 1, LOW: 2, MODIFIER: 3 };
const IMPACT_TONE: Record<string, Tone> = {
  HIGH: 'red',
  MODERATE: 'orange',
  LOW: 'yellow',
  MODIFIER: 'gray',
};

/** `ENST00000.1:c.123A>G` -> `c.123A>G`. */
function shortHgvs(s: string): string {
  return s.replace(/^[A-Za-z_]+\d+(\.\d+)?(\([^)]*\))?:/, '');
}

/** Turns the raw `CSQ` / `ANN` entries (one pipe string per transcript) into
 *  rows: de-duplicated, most severe first. */
export function parseAnnotations(
  values: unknown,
  source: 'CSQ' | 'ANN',
  headerFields?: string[],
): AnnotationRow[] {
  const entries = asArray(values).flatMap((v) => (typeof v === 'string' ? v.split(',') : []));
  const defaults = source === 'CSQ' ? VEP_DEFAULT_FIELDS : SNPEFF_DEFAULT_FIELDS;
  const rows: AnnotationRow[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    if (!entry.trim()) continue;
    const parts = entry.split('|');
    const fields = headerFields && headerFields.length === parts.length ? headerFields : defaults;
    const index = new Map<string, number>();
    fields.forEach((f, i) => {
      if (!index.has(norm(f))) index.set(norm(f), i);
    });
    const get = (...names: string[]): string => {
      for (const n of names) {
        const i = index.get(n);
        if (i !== undefined && parts[i]?.trim()) return parts[i].trim();
      }
      return '';
    };
    const hgvscFull = get('hgvsc');
    const hgvspFull = get('hgvsp');
    const impact = get('impact', 'annotationimpact').toUpperCase();
    const row: AnnotationRow = {
      gene: get('symbol', 'genename', 'gene'),
      consequence: formatConsequence(get('consequence', 'annotation')),
      impact,
      impactTone: IMPACT_TONE[impact] ?? 'gray',
      hgvsc: shortHgvs(hgvscFull),
      hgvsp: shortHgvs(hgvspFull),
      hgvscFull,
      hgvspFull,
    };
    const key = [row.gene, row.consequence, row.impact, row.hgvsc, row.hgvsp].join('\u0001');
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(row);
  }
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => (IMPACT_ORDER[a.r.impact] ?? 4) - (IMPACT_ORDER[b.r.impact] ?? 4) || a.i - b.i)
    .map(({ r }) => r);
}

// ---- Inheritance and scores -------------------------------------------------

const MODEL_LABEL: Record<string, [string, Tone]> = {
  AR_HOM: ['Recessive', 'orange'],
  AR_COMP: ['Compound heterozygous', 'violet'],
  AD: ['Dominant', 'blue'],
  XR: ['X-linked recessive', 'teal'],
  XD: ['X-linked dominant', 'teal'],
};

/** genmod's `GeneticModels` (`family:AR_comp|AD_dn`) as readable chips. */
export function parseGeneticModels(raw: unknown): Chip[] {
  const chips: Chip[] = [];
  const seen = new Map<string, Chip>();
  for (const item of asArray(raw)) {
    if (typeof item !== 'string') continue;
    for (const entry of item.split(',')) {
      const at = entry.indexOf(':');
      const family = at >= 0 ? entry.slice(0, at).trim() : '';
      const models = (at >= 0 ? entry.slice(at + 1) : entry).split('|');
      for (const m of models) {
        const code = m.trim();
        if (!code || code.toUpperCase() === 'NA') continue;
        const deNovo = /_dn$/i.test(code);
        const base = code.replace(/_dn$/i, '').toUpperCase();
        const [label, tone] = MODEL_LABEL[base] ?? [clean(code.replace(/_dn$/i, '')), 'gray' as Tone];
        const text = deNovo ? `${label}, de novo` : label;
        const existing = seen.get(text);
        if (existing) {
          if (family && existing.hint && !existing.hint.split(', ').includes(family)) {
            existing.hint += `, ${family}`;
          }
          continue;
        }
        const chip: Chip = { text, tone: deNovo ? 'red' : tone, hint: family || undefined };
        seen.set(text, chip);
        chips.push(chip);
      }
    }
  }
  return chips;
}

/** `RankScore` (`fam:14.0`, one per family) as `14`, or `fam 14, fam2 12`. */
export function formatRankScore(raw: unknown): string | undefined {
  const parts: string[] = [];
  const items = asArray(raw).flatMap((v) => (typeof v === 'string' ? v.split(',') : [v]));
  for (const item of items) {
    if (typeof item === 'number') {
      parts.push(formatNumber(item));
      continue;
    }
    if (typeof item !== 'string') continue;
    const at = item.lastIndexOf(':');
    const n = toNum(at >= 0 ? item.slice(at + 1) : item);
    if (n === undefined) continue;
    const family = at >= 0 ? item.slice(0, at).trim() : '';
    parts.push(family && items.length > 1 ? `${family} ${formatNumber(n)}` : formatNumber(n));
  }
  return parts.length ? parts.join(', ') : undefined;
}

function formatEach(raw: unknown, f: (n: number) => string): string | undefined {
  const parts = asArray(raw)
    .filter((v) => present(v))
    .map((v) => {
      const n = toNum(v);
      return n === undefined ? String(v) : f(n);
    });
  return parts.length ? parts.join(', ') : undefined;
}

// ---- Genotypes --------------------------------------------------------------

const ZYG_LABEL: Record<Zygosity, [string, Tone]> = {
  homref: ['Hom ref', 'gray'],
  het: ['Het', 'yellow'],
  homalt: ['Hom alt', 'orange'],
  nocall: ['No call', 'gray'],
};

/** Zygosity of a GT string: `0/0` `0|1` `1/1` `./.` `1/2`. */
export function zygosityOf(gt: string): Zygosity {
  const alleles = gt.split(/[/|]/).map((a) => a.trim());
  if (alleles.length === 0 || alleles.some((a) => a === '' || a === '.')) return 'nocall';
  if (alleles.every((a) => a === '0')) return 'homref';
  if (alleles.every((a) => a === alleles[0])) return 'homalt';
  return 'het';
}

function firstOf(v: unknown): unknown {
  return Array.isArray(v) ? v[0] : v;
}

/** One row per sample of a VCF feature's `samples`. */
export function buildGenotypes(samples: unknown): GenotypeRow[] {
  if (!isRec(samples)) return [];
  return Object.entries(samples).map(([sample, raw]) => {
    const s = isRec(raw) ? raw : {};
    const gtRaw = firstOf(s.GT);
    const gt = gtRaw == null ? '' : String(gtRaw);
    const zygosity = gt ? zygosityOf(gt) : 'nocall';
    const [zygosityLabel, tone] = ZYG_LABEL[zygosity];
    const num = (v: unknown): string => {
      const n = toNum(firstOf(v));
      return n === undefined ? '' : formatNumber(n);
    };
    const ad = asArray(s.AD).map(toNum);
    let adText = '';
    let vaf = '';
    if (ad.length > 0 && ad.every((n) => n !== undefined)) {
      const counts = ad as number[];
      adText = counts.map(formatInt).join(',');
      const ref = counts[0];
      const alt = counts.slice(1).reduce((a, b) => a + b, 0);
      if (counts.length > 1 && ref + alt > 0) {
        const pct = (alt / (ref + alt)) * 100;
        vaf = `${pct.toLocaleString('en-US', { maximumFractionDigits: pct < 10 ? 1 : 0 })}%`;
      }
    }
    return {
      sample,
      gt: gt || '.',
      zygosity,
      zygosityLabel,
      tone,
      dp: num(s.DP),
      gq: num(s.GQ),
      ad: adText,
      vaf,
    };
  });
}

// ---- Alignment flags --------------------------------------------------------

const FLAG_WORDS: Array<[number, string]> = [
  [0x1, 'paired'],
  [0x2, 'proper pair'],
  [0x4, 'unmapped'],
  [0x8, 'mate unmapped'],
  [0x10, 'reverse strand'],
  [0x20, 'mate reverse strand'],
  [0x40, 'first in pair'],
  [0x80, 'second in pair'],
  [0x100, 'secondary'],
  [0x200, 'QC fail'],
  [0x400, 'duplicate'],
  [0x800, 'supplementary'],
];

/** SAM FLAG bits as words. */
export function decodeFlags(flags: number): string[] {
  return FLAG_WORDS.filter(([bit]) => (flags & bit) !== 0).map(([, w]) => w);
}

// ---- Builders ---------------------------------------------------------------

function variantTypeLabel(type: string | undefined, ref: string, alts: string[]): string {
  const t = (type ?? '').toLowerCase();
  const known: Record<string, string> = {
    snv: 'SNV',
    mnv: 'MNV',
    insertion: 'Insertion',
    deletion: 'Deletion',
    delins: 'Indel',
    indel: 'Indel',
    sv: 'SV',
    cnv: 'CNV',
  };
  if (known[t]) return known[t];
  if (t) return upperFirst(clean(t));
  const alt = alts[0] ?? '';
  if (!ref || !alt || alt.startsWith('<')) return 'Variant';
  if (ref.length === 1 && alt.length === 1) return 'SNV';
  if (alt.length > ref.length) return 'Insertion';
  if (alt.length < ref.length) return 'Deletion';
  return 'MNV';
}

const filterFact = (filter: unknown): Fact => {
  if (filter === 'PASS') return { label: 'Filter', value: 'PASS', tone: 'green' };
  const codes = asArray(filter).map(String).filter(Boolean);
  return codes.length
    ? { label: 'Filter', value: codes.join(', '), tone: 'red' }
    : { label: 'Filter', value: 'Not filtered', tone: 'gray' };
};

function buildVariant(data: Rec, ctx: BuildContext): FeatureView {
  const r = new Reader(data);
  const info = isRec(data.INFO) ? data.INFO : {};
  const ir = new Reader(info);

  const refName = r.text('refName', 'CHROM') ?? '';
  const ref = r.text('REF') ?? '';
  const alts = asArray(r.take('ALT')).map(String);
  const pos = toNum(r.take('POS'));
  const start = toNum(r.take('start')) ?? (pos !== undefined ? pos - 1 : 0);
  const end = toNum(r.take('end')) ?? start + Math.max(ref.length, 1);
  const ids = asArray(r.take('ID')).map(String);
  const name = r.text('name');
  const type = r.text('type');
  r.skip('uniqueId', 'description', 'FORMAT', 'samples', 'INFO', 'CHROM', 'POS');

  // Annotations: VEP first, snpEff when VEP is absent or empty.
  let annotations: AnnotationRow[] = [];
  let annotationSource: 'CSQ' | 'ANN' | undefined;
  const rawAnnotations: FieldRow[] = [];
  for (const key of ['CSQ', 'ANN'] as const) {
    const raw = ir.take(key);
    if (raw === undefined) continue;
    rawAnnotations.push({ key, value: stringifyValue(raw) });
    if (annotationSource) continue;
    const rows = parseAnnotations(raw, key, parseAnnotationFormat(ctx.descriptions, key));
    if (rows.length) {
      annotations = rows;
      annotationSource = key;
    }
  }
  const gene = annotations.find((a) => a.gene)?.gene;
  const idText = ids.length ? ids.join(', ') : name;
  const title = gene || idText || formatLocus(refName, start, end);
  const subtitle = gene && idText ? idText : undefined;

  const facts: Fact[] = [];
  if (ref || alts.length) {
    facts.push({ label: 'Alleles', value: `${ref || '.'} → ${alts.length ? alts.join(', ') : '.'}`, mono: true });
  }
  const qual = toNum(r.take('QUAL'));
  if (qual !== undefined) facts.push({ label: 'Quality', value: formatNumber(qual) });
  facts.push(filterFact(r.take('FILTER')));

  // Known INFO keys, in a fixed reading order.
  const metric = (label: string, value: string | undefined, hint?: string) => {
    if (value !== undefined) facts.push({ label, value, hint });
  };
  metric('Rank score', formatRankScore(ir.take('RankScore')));
  metric('Rank score (normalized)', formatRankScore(ir.take('RankScoreNormalized')));
  for (const key of Object.keys(info)) {
    if (!/^gnomad_?af/i.test(key)) continue;
    metric(clean(key.replace(/^gnomad_?/i, 'gnomAD ')), formatEach(ir.take(key), formatFrequency), key);
  }
  for (const key of Object.keys(info)) {
    if (!/^cadd/i.test(key)) continue;
    metric(clean(key), formatEach(ir.take(key), formatNumber), key);
  }
  metric('AF', formatEach(ir.take('AF'), formatFrequency));
  metric('DP', formatEach(ir.take('DP'), formatNumber));
  metric('AQ', formatEach(ir.take('AQ'), formatNumber));

  const chips: ChipGroup[] = [];
  const models = parseGeneticModels(ir.take('GeneticModels'));
  if (models.length) chips.push({ label: 'Inheritance', chips: models });

  const fields = [...collectFields(info, ir.used), ...rawAnnotations.map((f) => ({ ...f, key: `${f.key} (raw)` }))];
  fields.push(...collectFields(data, r.used, ['INFO']));

  return {
    kind: 'variant',
    title,
    subtitle,
    typeLabel: variantTypeLabel(type, ref, alts),
    locus: formatLocus(refName, start, end),
    facts,
    chips,
    annotations,
    annotationSource,
    genotypes: buildGenotypes(data.samples),
    fields,
  };
}

function buildAlignment(data: Rec): FeatureView {
  const r = new Reader(data);
  const refName = r.text('refName') ?? '';
  const start = toNum(r.take('start')) ?? 0;
  const end = toNum(r.take('end')) ?? start + 1;
  const name = r.text('name') ?? 'Read';
  const strand = toNum(r.take('strand'));
  const mapq = toNum(r.take('score', 'mapq'));
  const cigar = r.text('CIGAR');
  const tlen = toNum(r.take('template_length'));
  const mate = r.text('next_segment_position');
  const orientation = r.text('pair_orientation');
  const flagsNum = toNum(data.flags);
  const seq = typeof data.seq === 'string' ? data.seq : undefined;
  r.skip('uniqueId', 'type', 'next_ref', 'next_pos');

  const facts: Fact[] = [];
  if (strand !== undefined) facts.push({ label: 'Strand', value: strand < 0 ? '−' : '+' });
  if (mapq !== undefined) facts.push({ label: 'MAPQ', value: formatNumber(mapq) });
  if (cigar) facts.push({ label: 'CIGAR', value: cigar, mono: true });
  if (tlen) facts.push({ label: 'Insert size', value: `${formatInt(Math.abs(tlen))} bp` });
  facts.push({ label: 'Aligned length', value: `${formatInt(end - start)} bp` });
  if (seq) facts.push({ label: 'Read length', value: `${formatInt(seq.length)} bp` });
  if (mate) facts.push({ label: 'Mate', value: formatMate(mate), mono: true });
  if (orientation) facts.push({ label: 'Pair orientation', value: orientation, mono: true });

  const chips: ChipGroup[] = [];
  if (flagsNum !== undefined) {
    const words = decodeFlags(flagsNum);
    if (words.length) {
      chips.push({
        label: 'Flags',
        chips: words.map((text) => ({
          text,
          tone: /duplicate|QC fail|unmapped/.test(text) ? 'red' : text === 'secondary' || text === 'supplementary' ? 'orange' : 'gray',
        })),
      });
    }
  }

  return {
    kind: 'alignment',
    title: name,
    typeLabel: 'Read',
    locus: formatLocus(refName, start, end),
    facts,
    chips,
    annotations: [],
    genotypes: [],
    fields: collectFields(data, r.used, ['tags']),
  };
}

/** Subfeature counts by type (recursive), in first-seen order. */
export function countSubfeatures(subfeatures: unknown): Array<[string, number]> {
  const counts = new Map<string, number>();
  const walk = (list: unknown) => {
    for (const sub of asArray(list)) {
      if (!isRec(sub)) continue;
      const type = typeof sub.type === 'string' && sub.type ? sub.type : 'feature';
      counts.set(type, (counts.get(type) ?? 0) + 1);
      walk(sub.subfeatures);
    }
  };
  walk(subfeatures);
  return [...counts];
}

function plural(label: string, n: number): string {
  if (n === 1) return label;
  if (/^(CDS|UTR)$/i.test(label) || label.endsWith('s')) return label;
  return `${label}s`;
}

function subfeatureLabel(type: string): string {
  if (/^five_prime_utr$/i.test(type)) return "5' UTR";
  if (/^three_prime_utr$/i.test(type)) return "3' UTR";
  return /^[A-Z]+$/.test(type) ? type : clean(type);
}

/** An Ensembl / RefSeq / UCSC transcript id (`ENST…`, `NM_…`, `uc002yis.1`). */
const TRANSCRIPT_ID = /^(ENS[A-Z]*T\d|[NX][MR]_\d|uc\d{3}[a-z]{3}\.\d)/;
/** An Ensembl gene id. */
const GENE_ID = /^ENS[A-Z]*G\d/;
/** A UCSC knownGene id (`uc002yis.1`). */
const UCSC_ID = /^uc\d{3}[a-z]{3}\.\d/;

/** ncbiRefSeq's `name2` is the gene symbol; knownGene's is a UCSC id. */
function refSeqSymbol(r: Reader): string | undefined {
  const v = r.data.name2;
  return typeof v === 'string' && v && !UCSC_ID.test(v) ? r.text('name2') : undefined;
}

function buildGeneric(data: Rec): FeatureView {
  const r = new Reader(data);
  const refName = r.text('refName') ?? '';
  const start = toNum(r.take('start')) ?? 0;
  const end = toNum(r.take('end')) ?? start + 1;
  const strand = toNum(r.take('strand'));
  const type = r.text('type');
  const source = r.text('source');
  const score = toNum(r.take('score'));
  // A gene model names a transcript by its id and its gene apart: UCSC's
  // knownGene (`geneName` = symbol, `geneName2` = UniProt, `name2` = UCSC id),
  // its ncbiRefSeq (`name2` = symbol), a GFF (`gene_name`, `gene_id`). The
  // symbol is what a reader looks for, so it heads the panel and the ids
  // follow it, without opening "All fields".
  const id = r.text('name', 'transcript_id', 'id');
  // A name that is not an accession (a GFF `Name=TP53`) is the symbol itself;
  // an alias holding something else then stays for "All fields".
  const isAccession = !!id && (TRANSCRIPT_ID.test(id) || GENE_ID.test(id));
  const symbol =
    id && !isAccession
      ? id
      : (r.text('gene_name', 'geneName', 'gene_symbol', 'geneSymbol', 'symbol', 'gene') ??
        refSeqSymbol(r));
  const geneIdRaw = r.text('gene_id');
  const geneId = geneIdRaw && geneIdRaw !== symbol ? geneIdRaw : undefined;
  const ucscId = r.text('name2');
  const uniprot = r.text('geneName2');
  const transcriptType = r.text('transcriptType', 'transcript_type', 'transcript_biotype');
  const biotype = r.text('geneType', 'biotype', 'gene_biotype', 'gene_type');
  const transcriptClass = r.text('transcriptClass');
  const tags = (r.text('tag') ?? '').split(',').map((t) => t.trim()).filter(Boolean);
  const description = r.text('description', 'note', 'product');
  r.skip('uniqueId', 'parentId', 'subfeatures');
  const isTranscript = !!id && TRANSCRIPT_ID.test(id);

  const facts: Fact[] = [];
  if (symbol && id && id !== symbol) {
    facts.push({ label: isTranscript ? 'Transcript' : 'ID', value: id, mono: true });
  }
  if (geneId) facts.push({ label: 'Gene ID', value: geneId, mono: GENE_ID.test(geneId) });
  if (uniprot && uniprot !== 'none') facts.push({ label: 'UniProt', value: uniprot, mono: true });
  if (ucscId && ucscId !== symbol && UCSC_ID.test(ucscId)) {
    facts.push({ label: 'UCSC ID', value: ucscId, mono: true });
  }
  if (strand !== undefined && strand !== 0) facts.push({ label: 'Strand', value: strand < 0 ? '−' : '+' });
  if (biotype) facts.push({ label: 'Biotype', value: clean(biotype) });
  if (transcriptType && transcriptType !== biotype) {
    facts.push({ label: 'Transcript type', value: clean(transcriptType) });
  }
  if (transcriptClass) facts.push({ label: 'Class', value: clean(transcriptClass) });
  facts.push({ label: 'Length', value: `${formatInt(end - start)} bp` });
  if (source) facts.push({ label: 'Source', value: source });
  if (score !== undefined) facts.push({ label: 'Score', value: formatNumber(score) });

  const chips: ChipGroup[] = [];
  if (tags.length) {
    chips.push({
      label: 'Tags',
      chips: tags.map((t) => ({
        text: clean(t),
        tone: (/mane|canonical/i.test(t) ? 'blue' : 'gray') as Tone,
      })),
    });
  }
  // bigBed `block` children are drawing detail, not structure.
  const counts = countSubfeatures(data.subfeatures).filter(([t]) => t !== 'block');
  if (counts.length) {
    chips.push({
      label: 'Structure',
      chips: counts.map(([t, n]) => ({ text: `${formatInt(n)} ${plural(subfeatureLabel(t), n)}`, tone: 'gray' as Tone })),
    });
  }

  return {
    kind: 'feature',
    title: symbol ?? id ?? formatLocus(refName, start, end),
    typeLabel: type
      ? upperFirst(clean(type))
      : isTranscript
        ? 'Transcript'
        : id && GENE_ID.test(id)
          ? 'Gene'
          : 'Feature',
    locus: formatLocus(refName, start, end),
    facts,
    description,
    chips,
    annotations: [],
    genotypes: [],
    fields: collectFields(data, r.used, ['attributes']),
  };
}

/** The view model of a clicked feature. */
export function buildFeatureView(data: Rec, ctx: BuildContext = {}): FeatureView {
  const isVariant =
    ctx.widgetType === 'VariantFeatureWidget' ||
    ('REF' in data && ('ALT' in data || 'INFO' in data));
  if (isVariant) return buildVariant(data, ctx);
  const isAlignment =
    ctx.widgetType === 'AlignmentsFeatureWidget' ||
    ('CIGAR' in data && 'flags' in data);
  if (isAlignment) return buildAlignment(data);
  return buildGeneric(data);
}

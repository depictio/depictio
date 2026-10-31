/**
 * The features a genome browser points at, painted in the selection colour.
 *
 * The backend names the picked `locus_from` rows (`payload.picked`): their
 * loci, and the names a feature carries (a transcript id, else the row's
 * label). Each track's renderer colours are rewritten as a jexl test in front
 * of the colour the track had, so the picked features take the selection
 * colour and an outline, and every other feature keeps its own. A variant (or
 * a call of the rank track) is picked by position, a feature of an annotation
 * track by name: a gene under a picked variant is not the pick.
 */
import type { JBrowsePicked } from '../../api';

/** Id of the rank track the backend adds for `locus_from.rank_track`. */
export const RANK_TRACK_ID = 'depictio-ranked-calls';

/** How a track's features are matched against the pick. */
export type PickMatch = 'loci' | 'names';

/** The renderer slots a pick rewrites: the fill, the UTR fill, the outline,
 *  the name label's colour and size, and the name itself (a star in front). */
export const PICK_SLOTS = [
  'color1',
  'color3',
  'outline',
  'labels.nameColor',
  'labels.fontSize',
  'labels.name',
] as const;

/** Label size of a picked feature, pixels (JBrowse's default is 12). */
export const PICK_FONT_PX = 15;

/** The mark in front of a picked feature's name (the rank track's top calls
 *  wear it too). */
export const PICK_STAR = '\u2605';
export type PickSlot = (typeof PICK_SLOTS)[number];

interface PickedLocus {
  chrom: string;
  start: number;
  end: number;
}

/** `chrom:start-end` (1-based, inclusive, separators allowed), or null. */
export function parseLocus(locus: string): PickedLocus | null {
  const m = /^([^:\s]+):([\d,]+)[-.]+([\d,]+)$/.exec(locus.trim());
  if (!m) return null;
  const start = Number(m[2].replace(/,/g, ''));
  const end = Number(m[3].replace(/,/g, ''));
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 1 || end < start) return null;
  return { chrom: m[1], start, end };
}

function quote(value: string): string {
  return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;
}

/** A contig name without its `chr` prefix, so `21` and `chr21` compare equal. */
function bareChrom(chrom: string): string {
  return chrom.replace(/^chr/i, '');
}

/** Jexl true for a feature starting inside one of `loci` (a variant at the position). */
export function lociCondition(loci: string[]): string | null {
  const parsed = loci.map(parseLocus).filter((l): l is PickedLocus => l !== null);
  if (!parsed.length) return null;
  const ref = "replace(get(feature,'refName'),'chr','')";
  // A feature's start is 0-based: a call at 1-based `start` starts at start - 1.
  return parsed
    .map(
      (l) =>
        `(${ref} == ${quote(bareChrom(l.chrom))} && get(feature,'start') >= ${l.start - 1}` +
        ` && get(feature,'start') <= ${l.end})`,
    )
    .join(' || ');
}

/** A field of the feature, else of its parent (an exon or CDS part carries
 *  neither name nor gene: it takes its transcript's), else ''. */
function ownOrParent(field: string): string {
  return (
    `(get(feature,'${field}') || ` +
    `(parent(feature) ? get(parent(feature),'${field}') : '') || '')`
  );
}

/**
 * Jexl true for a feature (or an exon of one) named one of `names`: its id,
 * version suffix ignored (`ENST…` matches `ENST….5`), or its gene symbol
 * (`geneName` of UCSC's knownGene, `name2` of its ncbiRefSeq; knownGene's
 * `name2` is a UCSC id and `geneName2` a UniProt one), so a row that names
 * only its gene (a riboseq ORF) lights the gene's transcripts.
 */
export function namesCondition(names: string[]): string | null {
  const kept = names.filter((n) => n.trim() !== '');
  if (!kept.length) return null;
  const name = ownOrParent('name');
  const symbols = [ownOrParent('geneName'), ownOrParent('name2')];
  return kept
    .map((n) =>
      [
        `${name} == ${quote(n)}`,
        `startsWith(${name}, ${quote(`${n}.`)})`,
        ...symbols.map((s) => `${s} == ${quote(n)}`),
      ].join(' || '),
    )
    .join(' || ');
}

/** The test a track's features are matched by, or null when the pick says nothing to it. */
export function pickCondition(picked: JBrowsePicked | null | undefined, match: PickMatch): string | null {
  if (!picked) return null;
  return match === 'loci' ? lociCondition(picked.loci ?? []) : namesCondition(picked.names ?? []);
}

/** A slot's value as a jexl operand: its expression, a number, or the literal. */
function operand(value: unknown): string {
  if (typeof value === 'string' && value.startsWith('jexl:')) return `(${value.slice(5)})`;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return quote(typeof value === 'string' ? value : '');
}

/** The colours a pick paints with: the theme's primary, and a medal per rank
 *  for the best three calls (gold, silver, bronze). */
export interface PickPalette {
  fill: string;
  light: string;
  outline: string;
  /** Label colour of ranks 1, 2 and 3: their star and name. */
  medals: string[];
}

/** The slots a rule sets: the fills, the outline, the name label's colour. */
export type PickKey = 'fill' | 'light' | 'outline' | 'label';

/** One test and the colours the features passing it take. A slot a rule
 *  leaves out keeps the track's own value (a medal keeps the feature's colour). */
export type PickRule = { condition: string } & Partial<Record<PickKey, string>>;

/**
 * The tests a track's picked features are coloured by, first match wins, and
 * `any` (true for a feature any rule picks: its label grows and gets a star).
 *
 * - The rank track wears its medals always: the star and name of `#1` in
 *   gold, `#2` silver, `#3` bronze, the box in its own colour (the category
 *   colour the navigator shows); a picked call below them takes the primary.
 * - A variant track picked at the opening (`picked.medals`) gives each of the
 *   best three calls its medal, in the order the backend lists them.
 * - Otherwise every picked feature takes the primary colour.
 */
export function pickRules(
  picked: JBrowsePicked | null | undefined,
  match: PickMatch,
  trackId: string,
  palette: PickPalette,
): { rules: PickRule[]; any: string | null } {
  const primary = (condition: string): PickRule => ({
    condition,
    fill: palette.fill,
    light: palette.light,
    outline: palette.outline,
    label: palette.outline,
  });
  const medal = (condition: string, i: number): PickRule => ({
    condition,
    label: palette.medals[i],
  });
  const rules: PickRule[] = [];
  if (trackId === RANK_TRACK_ID) {
    palette.medals.forEach((_, i) => rules.push(medal(`get(feature,'rank') == ${i + 1}`, i)));
    const cond = pickCondition(picked, 'loci');
    if (cond) rules.push(primary(cond));
  } else if (match === 'loci' && picked?.medals) {
    (picked.loci ?? []).forEach((locus, i) => {
      const cond = lociCondition([locus]);
      if (cond) rules.push(i < palette.medals.length ? medal(cond, i) : primary(cond));
    });
  } else {
    const cond = pickCondition(picked, match);
    if (cond) rules.push(primary(cond));
  }
  // The gene a picked transcript sits under wears the star (so the reader,
  // and the scroll to the pick, find it) but keeps its colours.
  const starred = rules.map((r) => r.condition);
  if (match === 'names' && picked?.genes?.length) {
    starred.push(
      picked.genes
        .filter((g) => g.trim() !== '')
        .map((g) => `get(feature,'name') == ${quote(g)}`)
        .join(' || '),
    );
  }
  const kept = starred.filter((c) => c !== '');
  return { rules, any: kept.length ? kept.map((c) => `(${c})`).join(' || ') : null };
}

/** `original` behind the rules: `jexl:c1 ? v1 : c2 ? v2 : original`; a
 *  rule without `key` keeps `original` for its features. */
export function rulesSlotValue(rules: PickRule[], key: PickKey, original: unknown): string {
  const base = operand(original);
  const body = rules.reduceRight((rest, r) => {
    const value = r[key];
    return `(${r.condition}) ? ${value === undefined ? base : quote(value)} : ${rest}`;
  }, base);
  return `jexl:${body}`;
}

/** `original` with `value` for the features `condition` picks (a label size). */
export function pickedNumberValue(condition: string, value: number, original: unknown): string {
  return `jexl:(${condition}) ? ${value} : ${operand(original)}`;
}

/** `original` with the picked features in `colour`: `jexl:cond ? colour : original`. */
export function pickedSlotValue(condition: string, colour: string, original: unknown): string {
  return `jexl:(${condition}) ? ${quote(colour)} : ${operand(original)}`;
}

/** `original` (a name expression) with a star in front of the picked features'
 *  names; a nameless one (a VCF record with ID `.`) gets the star alone, not
 *  "★ undefined". */
export function pickedLabelValue(condition: string, original: unknown): string {
  const name = operand(original);
  return `jexl:(${condition}) ? ${quote(`${PICK_STAR} `)} + (${name} || '') : ${name}`;
}

/** How a track is matched, or null for a track whose features are never picked. */
export function pickMatchOf(trackId: string, trackType: string): PickMatch | null {
  if (trackId === RANK_TRACK_ID || trackType === 'VariantTrack') return 'loci';
  if (trackType === 'FeatureTrack') return 'names';
  return null;
}

/**
 * A row test for the picked keys: a row is picked when it carries every column
 * of one key with the same values. A table lacking a key column (only `chrom`
 * of a `chrom` + `pos` key) never matches, or it would light a whole contig.
 * Null without keys.
 */
export function pickedRowMatcher(
  keys: Array<Record<string, unknown>>,
): ((row: Record<string, unknown>) => boolean) | null {
  const usable = keys.filter((k) => Object.keys(k).length > 0);
  if (!usable.length) return null;
  return (row) =>
    usable.some((key) =>
      Object.entries(key).every(([column, value]) => {
        const cell = row[column];
        return cell !== undefined && cell !== null && String(cell) === String(value);
      }),
    );
}

/**
 * Whether a layout record's feature is picked: its name label wears the star
 * (`pickedLabelValue`). The renderer sends the client the layout and its
 * labels, not the features, so the label is what the client can read.
 */
export function layoutRecordIsPicked(record: unknown): boolean {
  if (!Array.isArray(record)) return false;
  const labels = (record[4] as { floatingLabels?: Array<{ text?: unknown }> } | undefined)
    ?.floatingLabels;
  return (labels ?? []).some(
    (l) => typeof l.text === 'string' && l.text.startsWith(`${PICK_STAR} `),
  );
}

/** Room under a feature's box for its name label, pixels. */
export const PICK_LABEL_PX = 16;
/** The tallest a track grows to bring a picked feature into view, pixels;
 *  a pick laid out lower is scrolled to inside the track. */
export const PICK_TRACK_MAX_PX = 320;
/** Room kept above a picked feature scrolled to the top of its track, pixels. */
export const PICK_SCROLL_MARGIN_PX = 24;

/**
 * The height a track needs so the picked features' boxes (bottom edges, in
 * pixels from the track's top) and their labels show, or null when they
 * already do (or nothing is picked). Never more than `maxPx`.
 */
export function heightToShowPicked(
  bottoms: number[],
  height: number,
  maxPx: number = PICK_TRACK_MAX_PX,
): number | null {
  if (!bottoms.length) return null;
  const need = Math.min(Math.max(...bottoms) + PICK_LABEL_PX, maxPx);
  return need > height ? need : null;
}

/**
 * The scroll offset that shows a picked feature spanning `top`..`bottom`
 * (pixels from the track's top, label included) in a track `height` tall
 * scrolled to `scrollTop`, or null when it already shows.
 */
export function scrollToShowPicked(
  top: number,
  bottom: number,
  scrollTop: number,
  height: number,
): number | null {
  if (top >= scrollTop && bottom + PICK_LABEL_PX <= scrollTop + height) return null;
  return Math.max(0, top - PICK_SCROLL_MARGIN_PX);
}

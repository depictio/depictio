/**
 * What the ranked table's pinned popover needs to draw a variant's family:
 * the genotype of each family member read off a row or off a long table, the
 * fill that genotype earns on a pedigree symbol, and who the proband is.
 *
 * The tree itself (parsing, generations, coordinates) is `pedigree/pedigreeLayout.ts`.
 * Nothing here names a colour: the drawing resolves the theme.
 */
import { parseDeceased, type Person } from '../pedigree/pedigreeLayout';
import { parseProbandFlag, probandKeyOf } from '../pedigree/probands';

/** A genotype, reduced to what a carrier map shows. */
export type GenotypeClass = 'hom_alt' | 'het' | 'ref' | 'missing';

/** How a symbol is filled for a genotype. */
export type SymbolFill = 'full' | 'half' | 'empty' | 'grey';

/** Least to most alternate: the order a person with several calls keeps the largest of. */
const SEVERITY: Record<GenotypeClass, number> = { missing: 0, ref: 1, het: 2, hom_alt: 3 };

// Labels are compared case-, space-, dash- and underscore-insensitively: they
// are written `hom_alt`, `Hom alt`, `hom-alt` and `HOM ALT` alike, so each set
// holds the underscore spelling of a normalised label.
const HOM_ALT_WORDS = new Set([
  'hom_alt',
  'homalt',
  'hom',
  'homozygous',
  'homozygous_alt',
  'homozygous_alternate',
  'hom_alternate',
  'hom_var',
  'homvar',
  'homozygous_variant',
]);
const HET_WORDS = new Set([
  'het',
  'hetero',
  'heterozygous',
  'het_alt',
  'heterozygous_alt',
  'heterozygous_alternate',
  'het_var',
  'hetvar',
  'heterozygous_variant',
]);
const REF_WORDS = new Set([
  'ref',
  'hom_ref',
  'homref',
  'homozygous_ref',
  'homozygous_reference',
  'hom_reference',
  'wt',
  'wild_type',
  'wildtype',
  'reference',
]);
const MISSING_WORDS = new Set(['', 'missing', 'unknown', 'no_call', 'nocall', 'na', 'n/a', 'nan', 'none', 'null', '.', '-', '_']);

/** A label as the word sets spell it: lower case, runs of spaces, dashes and
 *  underscores one underscore, none at the ends. */
function normaliseLabel(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

/**
 * A genotype cell as a class.
 *
 * Words first (`hom_alt`, `Hom alt`, `Homozygous alt`, `Het`, `heterozygous`,
 * `Hom ref`, `missing`: any case, with spaces, dashes or underscores), then
 * allele calls: `0/0` and `0|0` are reference, `1/1` and `2/2` (one allele
 * repeated) homozygous alternate, `0/1`, `1|0` and `1/2` heterozygous, a call
 * with a `.` allele missing, and a single allele (a haploid call) read as a
 * homozygote. A bare number is a dosage of alternate alleles (0, 1, 2).
 */
export function genotypeClass(value: unknown): GenotypeClass {
  if (value === null || value === undefined) return 'missing';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 'missing';
    if (value <= 0) return 'ref';
    return value >= 2 ? 'hom_alt' : 'het';
  }
  const raw = String(value).trim().toLowerCase();
  if (MISSING_WORDS.has(raw)) return 'missing';
  const word = normaliseLabel(raw);
  if (MISSING_WORDS.has(word)) return 'missing';
  if (HOM_ALT_WORDS.has(word)) return 'hom_alt';
  if (HET_WORDS.has(word)) return 'het';
  if (REF_WORDS.has(word)) return 'ref';
  const alleles = raw.split(/[/|]/).map((a) => a.trim());
  if (alleles.some((a) => a === '' || a === '.')) return 'missing';
  if (!alleles.every((a) => /^\d+$/.test(a))) return 'missing';
  if (alleles.every((a) => Number(a) === 0)) return 'ref';
  if (alleles.every((a) => a === alleles[0])) return 'hom_alt';
  return 'het';
}

/** The fill a genotype earns: hom-alt solid, het half, ref open, missing grey. */
export function symbolFill(cls: GenotypeClass | null | undefined): SymbolFill {
  switch (cls) {
    case 'hom_alt':
      return 'full';
    case 'het':
      return 'half';
    case 'ref':
      return 'empty';
    default:
      return 'grey';
  }
}

/** The word a tooltip gives a genotype class. */
export const GENOTYPE_WORD: Record<GenotypeClass, string> = {
  hom_alt: 'homozygous alternate',
  het: 'heterozygous',
  ref: 'reference',
  missing: 'no call',
};

/** The larger of two genotype classes: the call a repeated individual keeps. */
export function moreAlternate(a: GenotypeClass, b: GenotypeClass): GenotypeClass {
  return SEVERITY[b] > SEVERITY[a] ? b : a;
}

// One rule for who the proband is, shared with the pedigree tile
// (`pedigree/probands.ts`): the popover's genotype roles (`proband`, `father`,
// `mother`) must resolve against the person the arrow points at.
export { parseProbandFlag };

/** The family's proband (see `probandKeyOf`). */
export const findProband = probandKeyOf;

/**
 * Which person each genotype column describes. A key of `genotype_columns` is
 * an individual's identifier, or one of the roles `proband`, `father` and
 * `mother` (the proband's parents), resolved against the tree so a template can
 * name the columns of any family the same way. An identifier wins over a role
 * word. A key matching nobody is dropped.
 */
export function assignGenotypeColumns(
  people: readonly Person[],
  probandKey: string | null,
  mapping: Record<string, string>,
): Map<string, string> {
  const byKey = new Map(people.map((p) => [p.key, p]));
  const proband = probandKey ? byKey.get(probandKey) : undefined;
  const out = new Map<string, string>();
  for (const [name, column] of Object.entries(mapping)) {
    const byId = people.find((p) => !p.placeholder && p.id === name);
    let target = byId?.key ?? null;
    if (!target && proband) {
      if (name === 'proband') target = proband.key;
      else if (name === 'father') target = proband.fatherKey;
      else if (name === 'mother') target = proband.motherKey;
    }
    if (target && byKey.get(target) && !byKey.get(target)!.placeholder) out.set(target, column);
  }
  return out;
}

/** What a person with no genotype row (or an empty cell) is drawn as: a real
 *  `missing` (no call, grey), the default, or `ref` for a table that lists
 *  carriers only, where no row means the variant is not there. */
export type MissingAs = 'ref' | 'missing';

const isEmptyCell = (v: unknown): boolean =>
  v === null || v === undefined || (typeof v === 'string' && v.trim() === '');

/** Each person's class read from columns of one ranked row. An empty cell
 *  reads as `missingAs`; a call that says "missing" (`./.`) stays missing. */
export function carriersFromRow(
  people: readonly Person[],
  probandKey: string | null,
  mapping: Record<string, string>,
  cell: (column: string) => unknown,
  missingAs: MissingAs = 'missing',
): Map<string, GenotypeClass> {
  const out = new Map<string, GenotypeClass>();
  for (const [key, column] of assignGenotypeColumns(people, probandKey, mapping)) {
    const value = cell(column);
    out.set(key, isEmptyCell(value) && missingAs === 'ref' ? 'ref' : genotypeClass(value));
  }
  return out;
}

/**
 * Each person's class read from a long table (one row per variant and
 * individual). Rows name the individual by identifier; one with several rows
 * keeps its most alternate call. People the table does not mention are absent
 * from the map, which the drawing reads as "no call" (`missingAs: 'ref'`
 * reads them as reference instead).
 */
export function carriersFromLong(
  people: readonly Person[],
  rows: Record<string, unknown[]>,
  columns: { individual: string; genotype: string },
  missingAs: MissingAs = 'missing',
): Map<string, GenotypeClass> {
  const byId = new Map(people.filter((p) => !p.placeholder).map((p) => [p.id, p.key]));
  const ids = rows[columns.individual] ?? [];
  const calls = rows[columns.genotype] ?? [];
  const out = new Map<string, GenotypeClass>();
  for (let i = 0; i < ids.length; i += 1) {
    const raw = ids[i];
    const key = byId.get(String(raw ?? '').trim());
    if (!key) continue;
    const cls = genotypeClass(calls[i]);
    const previous = out.get(key);
    out.set(key, previous ? moreAlternate(previous, cls) : cls);
  }
  // A table of carriers only has no row for a person without the variant:
  // with `missingAs: 'ref'` they are reference, not "no call".
  if (missingAs === 'ref') {
    for (const key of byId.values()) if (!out.has(key)) out.set(key, 'ref');
  }
  return out;
}

/** Whether a person is drawn as dead; kept here so the drawing needs one import. */
export function isDeceased(person: Person, column?: string | null): boolean {
  return column ? parseDeceased(person.row[column]) : person.deceased;
}

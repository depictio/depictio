/**
 * Pure layout for the `pedigree` kind: everything between the fetched rows and
 * the SVG, with no DOM and no theme, so every rule is unit-tested.
 *
 * - Reading the encodings a PED-like table comes in: sex as 1 / 2 / 0 or words,
 *   affected status as 2 / 1 / 0 / -9 or words, a parent of 0, empty or null
 *   as a founder, a deceased flag as 1 / true / a word.
 * - One person per (family, identifier): a repeated row is dropped and counted.
 *   A parent named in a row but absent from the table becomes a placeholder
 *   person, so the child still hangs under a couple.
 * - Generations: founders on row 0, a child one row under its later parent,
 *   and the two members of a couple on the same row (a founder who marries
 *   into the family is lowered to the row of the partner).
 * - A tree per family, laid out recursively: a couple is centred over its
 *   children, a person with several partners sits between them, and the
 *   children of each couple are drawn left to right in table order. Lines are
 *   returned as segments: the couple line, the drop from its midpoint, the
 *   sibship bar and one tick per child.
 *
 * Nothing here names a colour or a font; the renderer resolves both.
 */

export type Sex = 'male' | 'female' | 'unknown';
export type AffectedStatus = 'affected' | 'unaffected' | 'unknown';

/** A cell value as a fetched row carries it. */
type Cell = unknown;

const EMPTY_CELLS = new Set(['', '0', '.', '-', 'NA', 'N/A', 'NAN', 'NONE', 'NULL', '-9']);

function cellText(value: Cell): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : '';
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value).trim();
}

/** A parent reference as a key, or null for "no parent in this table".
 *  `0`, an empty cell, a dot, `NA` and null all mean a founder on that side. */
export function parseParentId(value: Cell): string | null {
  const text = cellText(value);
  if (EMPTY_CELLS.has(text.toUpperCase())) return null;
  // A float column writes 12 as "12.0"
  const asNumber = Number(text);
  if (text !== '' && Number.isFinite(asNumber) && Number.isInteger(asNumber)) {
    return asNumber === 0 ? null : String(asNumber);
  }
  return text;
}

/** An individual identifier as a key ("" when the cell is empty). */
export function parseIndividualId(value: Cell): string {
  const text = cellText(value);
  const asNumber = Number(text);
  if (text !== '' && Number.isFinite(asNumber) && Number.isInteger(asNumber)) {
    return String(asNumber);
  }
  return text;
}

/** PED sex: 1 male, 2 female, anything else unknown. Words are accepted too. */
export function parseSex(value: Cell): Sex {
  const text = cellText(value).toLowerCase();
  if (['1', '1.0', 'm', 'male', 'man', 'boy'].includes(text)) return 'male';
  if (['2', '2.0', 'f', 'female', 'woman', 'girl'].includes(text)) return 'female';
  return 'unknown';
}

/** PED phenotype: 2 affected, 1 unaffected, 0 / -9 / missing unknown. */
export function parseStatus(value: Cell): AffectedStatus {
  const text = cellText(value).toLowerCase();
  if (['2', '2.0', 'affected', 'a', 'yes', 'y', 'true', 'case', 'proband'].includes(text)) {
    return 'affected';
  }
  if (['1', '1.0', 'unaffected', 'u', 'no', 'n', 'false', 'control', 'healthy'].includes(text)) {
    return 'unaffected';
  }
  return 'unknown';
}

/** A deceased flag: 1, true, yes or a word. Anything else is alive. */
export function parseDeceased(value: Cell): boolean {
  const text = cellText(value).toLowerCase();
  return ['1', '1.0', 'true', 'yes', 'y', 'dead', 'deceased', 'died'].includes(text);
}

/** The columns the layout reads; null leaves an optional role unbound. */
export interface PedigreeColumns {
  individual: string;
  father: string;
  mother: string;
  sex: string;
  status: string;
  family?: string | null;
  label?: string | null;
  deceased?: string | null;
}

export interface Person {
  /** Unique across families: `family` + separator + `id`. */
  key: string;
  id: string;
  family: string;
  fatherKey: string | null;
  motherKey: string | null;
  sex: Sex;
  status: AffectedStatus;
  deceased: boolean;
  /** Text under the symbol. */
  label: string;
  /** The table row the person came from; empty for a placeholder. */
  row: Record<string, unknown>;
  /** A parent named by another row but absent from the table. */
  placeholder: boolean;
}

export interface PedigreeFamily {
  id: string;
  people: Person[];
}

export interface PedigreeInput {
  families: PedigreeFamily[];
  /** Repeated (family, individual) rows that were dropped. */
  duplicates: number;
  /** Whole families left out by the guards. */
  hiddenFamilies: number;
  hiddenIndividuals: number;
}

export interface PedigreeLimits {
  maxIndividuals: number;
  maxFamilies: number;
}

const KEY_SEPARATOR = '\u0001';

export function personKey(family: string, id: string): string {
  return `${family}${KEY_SEPARATOR}${id}`;
}

/** Column values by name, as `fetchAdvancedVizData` returns them. */
export type ColumnarRows = Record<string, unknown[]>;

function columnLength(rows: ColumnarRows): number {
  let n = 0;
  for (const col of Object.values(rows)) n = Math.max(n, col.length);
  return n;
}

/**
 * Rows to families of people.
 *
 * Rows without an identifier are skipped. A repeated (family, individual) keeps
 * its first row. Families keep table order, and so do the people in them.
 * `limits` drops whole families (never part of one): beyond `maxFamilies`, and
 * while the symbols drawn would pass `maxIndividuals` (the first family is
 * always kept).
 */
export function buildPedigree(
  rows: ColumnarRows,
  columns: PedigreeColumns,
  limits: PedigreeLimits,
): PedigreeInput {
  const n = columnLength(rows);
  const cell = (col: string | null | undefined, i: number): unknown =>
    col ? rows[col]?.[i] : undefined;

  const families = new Map<string, Map<string, Person>>();
  let duplicates = 0;

  for (let i = 0; i < n; i += 1) {
    const id = parseIndividualId(cell(columns.individual, i));
    if (!id) continue;
    const family = columns.family ? cellText(cell(columns.family, i)) : '';
    let members = families.get(family);
    if (!members) {
      members = new Map();
      families.set(family, members);
    }
    if (members.has(id)) {
      duplicates += 1;
      continue;
    }
    const father = parseParentId(cell(columns.father, i));
    const mother = parseParentId(cell(columns.mother, i));
    const row: Record<string, unknown> = {};
    for (const col of Object.keys(rows)) row[col] = rows[col][i];
    const label = columns.label ? cellText(cell(columns.label, i)) : '';
    members.set(id, {
      key: personKey(family, id),
      id,
      family,
      fatherKey: father === null ? null : personKey(family, father),
      motherKey: mother === null ? null : personKey(family, mother),
      sex: parseSex(cell(columns.sex, i)),
      status: parseStatus(cell(columns.status, i)),
      deceased: columns.deceased ? parseDeceased(cell(columns.deceased, i)) : false,
      label: label || id,
      row,
      placeholder: false,
    });
  }

  const all: PedigreeFamily[] = [];
  for (const [family, members] of families) {
    const people = [...members.values()];
    // A parent the table does not hold: a placeholder of the sex its role
    // implies and of unknown status, so the child still hangs under a couple.
    const known = new Set(people.map((p) => p.key));
    const extra: Person[] = [];
    const placeholderFor = (key: string | null, sex: Sex) => {
      if (key === null || known.has(key)) return;
      known.add(key);
      const id = key.slice(family.length + KEY_SEPARATOR.length);
      extra.push({
        key,
        id,
        family,
        fatherKey: null,
        motherKey: null,
        sex,
        status: 'unknown',
        deceased: false,
        label: id,
        row: {},
        placeholder: true,
      });
    };
    for (const p of people) {
      placeholderFor(p.fatherKey, 'male');
      placeholderFor(p.motherKey, 'female');
    }
    all.push({ id: family, people: [...people, ...extra] });
  }

  const kept: PedigreeFamily[] = [];
  let shown = 0;
  let hiddenIndividuals = 0;
  for (const fam of all) {
    const size = fam.people.filter((p) => !p.placeholder).length;
    const fits = kept.length < limits.maxFamilies && shown + size <= limits.maxIndividuals;
    if (kept.length === 0 || fits) {
      kept.push(fam);
      shown += size;
    } else {
      hiddenIndividuals += size;
    }
  }
  return {
    families: kept,
    duplicates,
    hiddenFamilies: all.length - kept.length,
    hiddenIndividuals,
  };
}

// ---------------------------------------------------------------------------
// Generations
// ---------------------------------------------------------------------------

interface Couple {
  key: string;
  father: string | null;
  mother: string | null;
  children: string[];
}

/** Cut the parent links that close a loop, so a malformed table still draws. */
function cutCycles(byKey: Map<string, Person>): Map<string, { f: string | null; m: string | null }> {
  const links = new Map<string, { f: string | null; m: string | null }>();
  for (const p of byKey.values()) {
    links.set(p.key, {
      f: p.fatherKey && p.fatherKey !== p.key && byKey.has(p.fatherKey) ? p.fatherKey : null,
      m: p.motherKey && p.motherKey !== p.key && byKey.has(p.motherKey) ? p.motherKey : null,
    });
  }
  const state = new Map<string, 1 | 2>();
  const visit = (key: string) => {
    state.set(key, 1);
    const l = links.get(key)!;
    for (const side of ['f', 'm'] as const) {
      const parent = l[side];
      if (!parent) continue;
      const s = state.get(parent);
      if (s === 1) l[side] = null;
      else if (s === undefined) visit(parent);
    }
    state.set(key, 2);
  };
  for (const key of byKey.keys()) if (!state.has(key)) visit(key);
  return links;
}

function couplesOf(
  people: Person[],
  links: Map<string, { f: string | null; m: string | null }>,
): Couple[] {
  const couples = new Map<string, Couple>();
  for (const p of people) {
    const l = links.get(p.key)!;
    if (!l.f && !l.m) continue;
    const key = `${l.f ?? ''}|${l.m ?? ''}`;
    let c = couples.get(key);
    if (!c) {
      c = { key, father: l.f, mother: l.m, children: [] };
      couples.set(key, c);
    }
    c.children.push(p.key);
  }
  return [...couples.values()];
}

/** Generation per person: founders 0, a child under its later parent, and the
 *  two members of a couple on one row. */
function assignGenerations(
  people: Person[],
  links: Map<string, { f: string | null; m: string | null }>,
  couples: Couple[],
): Map<string, number> {
  const floor = new Map<string, number>();
  const compute = () => {
    const out = new Map<string, number>();
    const walk = (key: string): number => {
      const known = out.get(key);
      if (known !== undefined) return known;
      const l = links.get(key)!;
      let g = floor.get(key) ?? 0;
      for (const parent of [l.f, l.m]) if (parent) g = Math.max(g, walk(parent) + 1);
      out.set(key, g);
      return g;
    };
    for (const p of people) walk(p.key);
    return out;
  };
  let gen = compute();
  for (let round = 0; round <= people.length; round += 1) {
    let changed = false;
    for (const c of couples) {
      if (!c.father || !c.mother) continue;
      const g = Math.max(gen.get(c.father) ?? 0, gen.get(c.mother) ?? 0);
      for (const k of [c.father, c.mother]) {
        if ((gen.get(k) ?? 0) < g) {
          floor.set(k, g);
          changed = true;
        }
      }
    }
    if (!changed) break;
    gen = compute();
  }
  return gen;
}

// ---------------------------------------------------------------------------
// Tree layout
// ---------------------------------------------------------------------------

interface LaidOutNode {
  /** Persons in the row, left to right. */
  row: string[];
  /** Child nodes in drawing order, with the couple each belongs to. */
  groups: { couple: Couple; nodes: { anchor: string; node: LaidOutNode }[] }[];
  width: number;
}

export interface LayoutOptions {
  /** Horizontal pitch of one person, px. */
  slot: number;
  /** Vertical pitch of one generation, px. */
  rowHeight: number;
  /** Symbol edge, px: lines stop at its border. */
  symbol: number;
  /** Space above the first generation (family caption), px. */
  top: number;
  /** Space between families, in slots. */
  familyGap: number;
  /** Room under a symbol for its label, px: a lone parent's drop starts below it. */
  labelSpace: number;
}

export const DEFAULT_LAYOUT: LayoutOptions = {
  slot: 64,
  rowHeight: 96,
  symbol: 28,
  top: 28,
  familyGap: 1.5,
  labelSpace: 18,
};

export interface PlacedPerson {
  person: Person;
  /** Symbol centre, px. */
  x: number;
  y: number;
  generation: number;
}

export interface PedigreeLine {
  kind: 'couple' | 'drop' | 'sibship' | 'child';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface PlacedFamily {
  id: string;
  /** Left edge and width of the family's band, px. */
  x: number;
  width: number;
  people: PlacedPerson[];
  lines: PedigreeLine[];
  generations: number;
}

export interface PedigreeLayout {
  families: PlacedFamily[];
  width: number;
  height: number;
}

function layoutFamily(family: PedigreeFamily, opts: LayoutOptions): {
  people: { person: Person; slotX: number; generation: number }[];
  couples: Couple[];
  width: number;
  generations: number;
} {
  const byKey = new Map(family.people.map((p) => [p.key, p]));
  const links = cutCycles(byKey);
  const couples = couplesOf(family.people, links);
  const gen = assignGenerations(family.people, links, couples);

  const couplesByPerson = new Map<string, Couple[]>();
  for (const c of couples) {
    for (const k of [c.father, c.mother]) {
      if (!k) continue;
      const list = couplesByPerson.get(k) ?? [];
      list.push(c);
      couplesByPerson.set(k, list);
    }
  }
  const isFounder = (key: string) => {
    const l = links.get(key)!;
    return !l.f && !l.m;
  };

  const placed = new Set<string>();

  const build = (anchor: string): LaidOutNode => {
    placed.add(anchor);
    // The row: the anchor, and the founders who married into it. A father sits
    // left of his partner, a mother right of hers.
    const left: string[] = [];
    const right: string[] = [];
    const inRow = new Set([anchor]);
    const queue = [anchor];
    while (queue.length > 0) {
      const q = queue.shift()!;
      for (const c of couplesByPerson.get(q) ?? []) {
        const s = c.father === q ? c.mother : c.father;
        if (!s || placed.has(s) || inRow.has(s) || !isFounder(s)) continue;
        placed.add(s);
        inRow.add(s);
        queue.push(s);
        if (c.father === s) left.push(s);
        else right.push(s);
      }
    }
    let row = [...left.reverse(), anchor, ...right];
    // One person with several partners (a star) sits between them, so no
    // couple line runs across another partner's symbol.
    if (row.length > 2) {
      const partnersIn = (key: string) =>
        (couplesByPerson.get(key) ?? []).filter((c) => {
          const s = c.father === key ? c.mother : c.father;
          return s !== null && inRow.has(s);
        }).length;
      const hub = row.find((k) => partnersIn(k) === row.length - 1);
      if (hub) {
        const others = row.filter((k) => k !== hub);
        const cut = Math.ceil(others.length / 2);
        row = [...others.slice(0, cut), hub, ...others.slice(cut)];
      }
    }

    const taken = new Set<string>();
    const groups: LaidOutNode['groups'] = [];
    for (const member of row) {
      for (const c of couplesByPerson.get(member) ?? []) {
        if (taken.has(c.key)) continue;
        taken.add(c.key);
        const nodes: { anchor: string; node: LaidOutNode }[] = [];
        for (const child of c.children) {
          if (placed.has(child)) continue;
          nodes.push({ anchor: child, node: build(child) });
        }
        groups.push({ couple: c, nodes });
      }
    }
    let childrenWidth = 0;
    for (const g of groups) for (const n of g.nodes) childrenWidth += n.node.width;
    return { row, groups, width: Math.max(row.length, childrenWidth) };
  };

  const slotX = new Map<string, number>();
  const assign = (node: LaidOutNode, leftEdge: number) => {
    const center = leftEdge + node.width / 2;
    const rowStart = center - node.row.length / 2;
    node.row.forEach((key, i) => slotX.set(key, rowStart + i + 0.5));
    let childrenWidth = 0;
    for (const g of node.groups) for (const n of g.nodes) childrenWidth += n.node.width;
    let cursor = center - childrenWidth / 2;
    for (const g of node.groups) {
      for (const n of g.nodes) {
        assign(n.node, cursor);
        cursor += n.node.width;
      }
    }
  };

  const roots: LaidOutNode[] = [];
  // Founders first, in table order. A founder whose partner descends from
  // someone is placed through that partner, not as a tree of its own.
  const hasBloodPartner = (key: string) =>
    (couplesByPerson.get(key) ?? []).some((c) => {
      const s = c.father === key ? c.mother : c.father;
      return s !== null && !isFounder(s);
    });
  for (const p of family.people) {
    if (placed.has(p.key) || !isFounder(p.key) || hasBloodPartner(p.key)) continue;
    roots.push(build(p.key));
  }
  // Whatever is left (a loop that was cut, a couple linking two lines of
  // descent) still gets a place.
  for (const p of family.people) {
    if (!placed.has(p.key)) roots.push(build(p.key));
  }

  let cursor = 0;
  for (const root of roots) {
    assign(root, cursor);
    cursor += root.width;
  }

  return {
    people: family.people.map((person) => ({
      person,
      slotX: slotX.get(person.key) ?? 0.5,
      generation: gen.get(person.key) ?? 0,
    })),
    couples,
    width: Math.max(cursor, 1),
    generations: family.people.reduce((m, p) => Math.max(m, (gen.get(p.key) ?? 0) + 1), 0),
  };
}

/** Lay out every family side by side. */
export function layoutPedigree(
  input: PedigreeInput | PedigreeFamily[],
  options: Partial<LayoutOptions> = {},
): PedigreeLayout {
  const opts = { ...DEFAULT_LAYOUT, ...options };
  const families = Array.isArray(input) ? input : input.families;
  const half = opts.symbol / 2;
  const out: PlacedFamily[] = [];
  let cursor = 0;
  let maxGenerations = 0;

  for (const family of families) {
    const laid = layoutFamily(family, opts);
    const xOf = new Map<string, number>();
    const yOf = new Map<string, number>();
    const people: PlacedPerson[] = laid.people.map(({ person, slotX, generation }) => {
      const x = (cursor + slotX) * opts.slot;
      const y = opts.top + generation * opts.rowHeight + half;
      xOf.set(person.key, x);
      yOf.set(person.key, y);
      return { person, x, y, generation };
    });

    const lines: PedigreeLine[] = [];
    for (const c of laid.couples) {
      const fx = c.father ? xOf.get(c.father) : undefined;
      const mx = c.mother ? xOf.get(c.mother) : undefined;
      const parentY = yOf.get((c.father ?? c.mother)!) ?? 0;
      let dropX: number;
      let dropY: number;
      if (fx !== undefined && mx !== undefined) {
        const [a, b] = fx <= mx ? [fx, mx] : [mx, fx];
        lines.push({ kind: 'couple', x1: a + half, y1: parentY, x2: b - half, y2: parentY });
        dropX = (fx + mx) / 2;
        dropY = parentY;
      } else {
        dropX = (fx ?? mx)!;
        dropY = parentY + half + opts.labelSpace;
      }
      const kids = c.children
        .map((k) => ({ x: xOf.get(k)!, y: yOf.get(k)! }))
        .filter((k) => k.x !== undefined);
      if (kids.length === 0) continue;
      const top = Math.min(...kids.map((k) => k.y)) - half;
      const barY = top - (opts.rowHeight - opts.symbol) / 3;
      lines.push({ kind: 'drop', x1: dropX, y1: dropY, x2: dropX, y2: barY });
      const xs = [dropX, ...kids.map((k) => k.x)];
      lines.push({
        kind: 'sibship',
        x1: Math.min(...xs),
        y1: barY,
        x2: Math.max(...xs),
        y2: barY,
      });
      for (const k of kids) {
        lines.push({ kind: 'child', x1: k.x, y1: barY, x2: k.x, y2: k.y - half });
      }
    }

    out.push({
      id: family.id,
      x: cursor * opts.slot,
      width: laid.width * opts.slot,
      people,
      lines,
      generations: laid.generations,
    });
    maxGenerations = Math.max(maxGenerations, laid.generations);
    cursor += laid.width + opts.familyGap;
  }

  const width = out.length > 0 ? (cursor - opts.familyGap) * opts.slot : 0;
  const height = out.length > 0 ? opts.top + maxGenerations * opts.rowHeight : 0;
  return { families: out, width, height };
}

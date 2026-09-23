/**
 * Which columns a record card shows, and under which heading.
 *
 * Two layouts meet here. An author-declared `sections` map is the explicit
 * one: it names the headings and the columns under each, in reading order.
 * With no map the card falls back to the collection's own
 * `columns_description` metadata, where a description of the form
 * `"FastQC: percent duplicates"` names the group the column belongs to. That
 * convention is what lets a well-described collection lay itself out with no
 * per-dashboard layout at all, and a collection whose descriptions carry no
 * prefix (or that has no descriptions) collapses to a single section, which
 * is the honest answer rather than forty one-field headings.
 *
 * Kept out of the renderer because the grouping and the field cap are the
 * part worth testing; the Mantine `Card` around them is not.
 */

export interface RecordSection {
  /** Heading rendered above the fields. */
  title: string;
  /** Columns under that heading, in reading order. */
  columns: string[];
}

/** Heading for the fields the collection groups under nothing. */
export const DEFAULT_SECTION_TITLE = 'Fields';

/** Longest prefix still readable as a group name rather than as a sentence
 *  that happens to contain a colon ("Mean coverage: only primary alignments
 *  are counted" is a description, not a heading). */
const MAX_GROUP_TITLE_CHARS = 32;

/**
 * The group a `columns_description` entry names, or null when it names none.
 *
 * Deliberately strict: a prefix counts only when it is short and something
 * follows the colon, so free prose stays prose and the card falls back to one
 * section instead of inventing headings out of half-sentences.
 */
export function descriptionGroup(description?: string | null): string | null {
  if (!description) return null;
  const at = description.indexOf(':');
  if (at <= 0 || at > MAX_GROUP_TITLE_CHARS) return null;
  if (!description.slice(at + 1).trim()) return null;
  return description.slice(0, at).trim() || null;
}

export interface RecordSectionInput {
  /** Every column the card may show, in the collection's own order. */
  columns: readonly string[];
  /** Author-declared layout: heading to the columns under it. */
  sections?: Record<string, string[]> | null;
  /** The collection's `columns_description` entries, keyed by column. */
  descriptions?: Record<string, string | null | undefined> | null;
  /** Columns already shown in the card's heading, so a field does not repeat
   *  what the reader has just read. */
  headingColumns?: readonly string[];
  /** How many fields to lay out before the card truncates. */
  maxFields: number;
}

export interface RecordSectionLayout {
  sections: RecordSection[];
  /** Fields the cap dropped, so the card can say how many it is not showing. */
  truncated: number;
}

/** Lay a record's columns out as titled sections, capped at `maxFields`. */
export function buildRecordSections(input: RecordSectionInput): RecordSectionLayout {
  const heading = new Set(input.headingColumns ?? []);
  // A Set keyed by the collection's own column order: dedupes a column named
  // twice by the author without reordering anything.
  const available = new Set<string>();
  for (const column of input.columns) {
    if (column && !heading.has(column)) available.add(column);
  }

  const sections = input.sections
    ? Object.entries(input.sections).map(([title, columns]) => ({
        title,
        // The author named these columns; anything the frame did not bring
        // back (a renamed column, a pruned one) drops out silently rather
        // than rendering an empty field a reader would take for a null.
        columns: (columns ?? []).filter((column) => available.has(column)),
      }))
    : groupByDescription(Array.from(available), input.descriptions);

  return capFields(
    sections.filter((section) => section.columns.length > 0),
    input.maxFields,
  );
}

function groupByDescription(
  columns: readonly string[],
  descriptions?: Record<string, string | null | undefined> | null,
): RecordSection[] {
  const byTitle = new Map<string, string[]>();
  for (const column of columns) {
    const title = descriptionGroup(descriptions?.[column]) ?? DEFAULT_SECTION_TITLE;
    const bucket = byTitle.get(title);
    if (bucket) bucket.push(column);
    else byTitle.set(title, [column]);
  }

  const sections = Array.from(byTitle, ([title, cols]) => ({ title, columns: cols }));
  // The ungrouped remainder reads as a remainder, so it goes last whenever
  // there is something it is the remainder of.
  if (sections.length > 1) {
    const at = sections.findIndex((section) => section.title === DEFAULT_SECTION_TITLE);
    if (at >= 0) sections.push(...sections.splice(at, 1));
  }
  return sections;
}

function capFields(sections: RecordSection[], maxFields: number): RecordSectionLayout {
  const cap = Math.max(1, Math.floor(maxFields) || 1);
  const out: RecordSection[] = [];
  let used = 0;
  let truncated = 0;
  for (const section of sections) {
    const kept = section.columns.slice(0, Math.max(0, cap - used));
    truncated += section.columns.length - kept.length;
    used += kept.length;
    if (kept.length) out.push({ title: section.title, columns: kept });
  }
  return { sections: out, truncated };
}

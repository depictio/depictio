/**
 * Shared reading rules for run-provenance entries.
 *
 * The collector is deliberately complete — it writes down every key it found,
 * including the ones the pipeline never set — so it is the READER that decides
 * what is worth showing. Both surfaces (the ingestion report's card and the
 * dashboard's Settings drawer) use the same rule so a count in one place
 * matches the count in the other.
 */

export interface ProvenanceEntryLike {
  key: string;
  value: string;
  highlight?: boolean;
  group?: string;
  source?: string;
}

/** Values the CLI stringifies for "the pipeline left this alone". */
const UNSET_VALUES = new Set(['null', 'false', '', '[]', '{}', 'none', 'NA']);

/**
 * True when the entry carries no decision — an unset parameter.
 *
 * On a typical nf-core run this is about half of what the params file holds
 * (176 keys, 80 of them set), which is the difference between a readable list
 * and a wall of `null`.
 */
export function isUnsetProvenanceValue(value: string | null | undefined): boolean {
  return UNSET_VALUES.has((value ?? '').trim());
}

/** Case-insensitive match over both the key and the value. */
export function matchesProvenanceQuery(entry: ProvenanceEntryLike, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return entry.key.toLowerCase().includes(q) || entry.value.toLowerCase().includes(q);
}

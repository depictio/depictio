/**
 * The reader's view of a built pedigree: which families are drawn and what
 * text sits under a symbol. Kept out of the renderer so it is tested without a
 * DOM; the layout itself stays in `pedigreeLayout.ts`.
 */
import type { PedigreeFamily, Person } from './pedigreeLayout';

export type LabelMode = 'label' | 'id';

/** Whether anyone in the family is affected (a placeholder never is). */
export function hasAffected(family: PedigreeFamily): boolean {
  return family.people.some((p) => !p.placeholder && p.status === 'affected');
}

/**
 * The families a view shows, in table order: only `focus` when it names one of
 * them (a stale name, say after a filter removed that family, shows all), and
 * with `affectedOnly`, only those with an affected member.
 */
export function visibleFamilies(
  families: readonly PedigreeFamily[],
  options: { focus?: string | null; affectedOnly?: boolean },
): PedigreeFamily[] {
  const focus =
    options.focus !== null && options.focus !== undefined && families.some((f) => f.id === options.focus)
      ? options.focus
      : null;
  return families.filter((f) => (focus === null || f.id === focus) && (!options.affectedOnly || hasAffected(f)));
}

/** The text under a symbol: the label column's value, or the identifier. */
export function personLabel(person: Pick<Person, 'id' | 'label'>, mode: LabelMode): string {
  return mode === 'id' ? person.id : person.label;
}

/**
 * Edge of a symbol and distance between generations, kept apart enough that a
 * symbol and the label under it never reach the next generation.
 */
export function spacedLayout(
  symbol: number,
  generationSpacing: number,
  labelSpace: number,
): { symbol: number; rowHeight: number } {
  return { symbol, rowHeight: Math.max(generationSpacing, symbol + labelSpace + 24) };
}

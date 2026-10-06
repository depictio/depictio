/**
 * Which style a metric card is drawn in.
 *
 * A card can set its own `variant`, and the grid section it sits in can set a
 * `card_variant` that every card in it takes unless the card says otherwise.
 * The two are resolved here, in one place, so the dashboard grid, the editor
 * and the card builder's hint can never disagree about what a card looks like.
 *
 * Mirrors `CardVariant` in depictio/models/components/types.py.
 */
import type { FilterSectionSpec, StoredMetadata } from '../api';

export const CARD_VARIANTS = ['default', 'headline', 'compact', 'minimal'] as const;
export type CardVariant = (typeof CARD_VARIANTS)[number];

/** A known style, or null for anything else. Stored metadata is not validated
 *  on the way back from the server (a card's `display` block passes through
 *  untouched), so a value written by a newer release or by hand must read as
 *  "unset" here rather than reach the renderer as a style it cannot draw. */
export function normalizeCardVariant(value: unknown): CardVariant | null {
  return typeof value === 'string' && (CARD_VARIANTS as readonly string[]).includes(value)
    ? (value as CardVariant)
    : null;
}

/** The style a card is drawn in: its own when it sets one, else its section's,
 *  else `default`. An explicit `default` on the card counts as its own choice,
 *  which is how a card opts out of its section's style. */
export function resolveCardVariant(cardVariant: unknown, sectionVariant?: unknown): CardVariant {
  return normalizeCardVariant(cardVariant) ?? normalizeCardVariant(sectionVariant) ?? 'default';
}

/**
 * The metadata a grid cell hands its renderer: the card's own, with the
 * section's style filled in when the card sets none.
 *
 * Returns the same object when nothing changes, so a cell whose card already
 * sets its style (or that is not a card) keeps its identity and React can skip
 * re-rendering it.
 */
export function withSectionCardVariant(
  metadata: StoredMetadata,
  section: Pick<FilterSectionSpec, 'card_variant'> | null | undefined,
): StoredMetadata {
  if (metadata.component_type !== 'card') return metadata;
  if (normalizeCardVariant(metadata.variant)) return metadata;
  const fromSection = normalizeCardVariant(section?.card_variant);
  if (!fromSection) return metadata;
  return { ...metadata, variant: fromSection };
}

/**
 * What picking `picked` in the card builder stores in the card's `variant`,
 * given the style its section draws its cards in.
 *
 * Unset whenever the pick is what the card would get anyway: `default` with no
 * section style, or the section's own style. A card stored that way keeps
 * following its section when the section is restyled, and the YAML carries no
 * key that changes nothing. Any other pick is stored as the card's own, which
 * is how `default` comes to be written: to opt a card out of its section.
 */
export function variantForPick(
  picked: unknown,
  sectionVariant: CardVariant | null | undefined,
): CardVariant | null {
  const v = normalizeCardVariant(picked) ?? 'default';
  return v === (normalizeCardVariant(sectionVariant) ?? 'default') ? null : v;
}

/** Which secondary strips a compact card keeps. It is a strip of small numbers,
 *  so a chart under each would undo the point; a single bar (coverage, a
 *  composition cut to its bar) still fits in the height it has. */
const COMPACT_STRIPS = new Set(['coverage', 'composition']);

export function compactKeepsStrip(layout: string | null | undefined): boolean {
  return COMPACT_STRIPS.has(layout ?? '');
}

/**
 * The colours a dashboard pins for secondary-structure states
 * (`category_colors: {category: {Helix: ..., Strand: ..., Coil: ...}}`), turned
 * into the per-class colours the glyphs are drawn in. Pure, unit-tested in
 * `stateColours.test.ts`.
 */

import type { SecondaryStructure } from '../protein/residueColours';
import { secondaryStructureOf } from '../protein/sequence';

/** A colour per class; a class the dashboard does not pin keeps the tile's own. */
export type SsStateColours = Partial<Record<SecondaryStructure, string>>;

/**
 * Read each pin's value as a state (`Helix`, `H`, `Strand`, `E`...) through
 * `secondaryStructureOf`, so a column that holds codes and one that spells the
 * state out pin the same classes. Layers are given least specific first: a
 * later one wins class by class. A value that is not a state is ignored.
 */
export function pinnedStateColours(
  ...layers: ReadonlyArray<Record<string, string> | null | undefined>
): SsStateColours {
  const out: SsStateColours = {};
  for (const layer of layers) {
    if (!layer) continue;
    for (const [value, colour] of Object.entries(layer)) {
      const state = secondaryStructureOf(value);
      if (state && colour) out[state] = colour;
    }
  }
  return out;
}

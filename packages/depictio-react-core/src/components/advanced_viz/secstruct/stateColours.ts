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

/** A map of class (or state code) to a CSS colour, as stored in `state_colors`. */
export type StateColourMap = Record<string, string>;

/** The classes the tile draws and lets the user recolour, with the key each is stored under. */
export const SS_COLOUR_CLASSES: ReadonlyArray<{ state: SecondaryStructure; key: string; label: string }> = [
  { state: 'helix', key: 'Helix', label: 'Helix' },
  { state: 'strand', key: 'Strand', label: 'Strand' },
  { state: 'turn', key: 'Turn', label: 'Turn' },
  { state: 'coil', key: 'Coil', label: 'Coil' },
];

/**
 * The colour of each class the tile draws. Precedence, highest first: the
 * colours the user set on the tile, the config's `state_colors`, the colours
 * the dashboard pins for the state column, then (left to the caller, by the
 * class being absent from the result) the tile's defaults.
 */
export function effectiveStateColours(
  pinned: ReadonlyArray<StateColourMap | null | undefined>,
  configured: StateColourMap | null | undefined,
  user: StateColourMap | null | undefined,
): SsStateColours {
  return pinnedStateColours(...pinned, configured, user);
}

/**
 * `map` with `colour` set for `state`. Any key that reads as the same class
 * (`H`, `helix`...) is dropped so the new colour is the one that wins; an
 * empty colour clears the class.
 */
export function withStateColour(
  map: StateColourMap | null | undefined,
  state: SecondaryStructure,
  colour: string,
): StateColourMap {
  const out: StateColourMap = {};
  for (const [key, value] of Object.entries(map ?? {})) {
    if (secondaryStructureOf(key) !== state) out[key] = value;
  }
  const entry = SS_COLOUR_CLASSES.find((c) => c.state === state);
  if (colour && entry) out[entry.key] = colour;
  return out;
}

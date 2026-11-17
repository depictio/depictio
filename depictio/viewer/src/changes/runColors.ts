/**
 * The colour of a run, the same in the What's new panel, its run chips and the
 * toast (epic #1399).
 *
 *   1. A run that is one group of the dashboard's pinned colours (all its
 *      samples in one locality, and no other run in it) takes that group's
 *      colour: the server says which (`run_colors` of the change set or the
 *      inbox item).
 *   2. Else the colour the dashboard pins to the run itself
 *      (`category_colors.depictio_run_id`), like any category.
 *   3. Else a colour of the palette, picked from the run's name, so a run has
 *      the same colour on every page whatever other runs are listed.
 */
import { useCallback } from 'react';

import { categoryColor, useCategoryColorSource, useCategoryPalette } from 'depictio-react-core';

import { RUN_COLUMN } from './newsSplit';

/** A small, stable string hash (FNV-1a): the run's slot in the palette. */
export function runSlot(tag: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < tag.length; i += 1) {
    h ^= tag.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** `tag -> colour`, with the server's group colours first. */
export function useRunColor(
  serverColors: Record<string, string> | null | undefined,
): (tag: string) => string {
  const source = useCategoryColorSource();
  const palette = useCategoryPalette();
  return useCallback(
    (tag: string) =>
      serverColors?.[tag] ?? categoryColor(source, RUN_COLUMN, tag, runSlot(tag), palette),
    [serverColors, source, palette],
  );
}

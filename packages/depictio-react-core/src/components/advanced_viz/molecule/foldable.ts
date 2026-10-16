/**
 * Which proteins the structure resolver can draw, so a tile that opens on a
 * protein by itself does not start on one it cannot.
 *
 * The resolver tries AlphaFold DB for a UniProt accession or a gene, and
 * folds a bare sequence with ESMFold, which the public ESM Atlas service
 * limits to `ESMFOLD_MAX_RESIDUES`. A protein with no accession and no gene
 * and a longer sequence (or no sequence at all) has nothing the resolver can
 * ask. Left to the default order (most rows first, which on a residue table
 * is the longest protein) a tile would open on exactly that one.
 *
 * Pure, so vitest covers it in node. Only the automatic choice uses it: a
 * filter, a table row or the reader's own pick is never overridden (see
 * `chooseEntity`).
 */

import { chooseEntity, type ResidueRow } from './residueData';
import { ESMFOLD_MAX_RESIDUES } from './resolve';

/** Residues of a sequence the way the server counts them: whitespace dropped
 *  and a trailing stop `*` ignored (`_normalise` in structure_resolver.py). */
export function foldLength(sequence: string | null | undefined): number {
  return sequence ? sequence.replace(/\s+/g, '').replace(/\*+$/, '').length : 0;
}

/**
 * Entities of the rows the resolver cannot draw: no UniProt accession, no
 * gene and no sequence it can fold (none, or longer than `maxResidues`). An
 * entity with an accession or a gene is never listed, whatever its sequence
 * length: AlphaFold DB is tried first and has no such limit.
 *
 * Reads the first value of each identifier across an entity's rows, the same
 * rows `resolverQuery` reads. Rows with no entity are skipped.
 */
export function unfoldableEntities(
  rows: readonly ResidueRow[],
  maxResidues: number = ESMFOLD_MAX_RESIDUES,
): Set<string> {
  const seen = new Map<string, { named: boolean; sequence: string | null }>();
  for (const r of rows) {
    if (r.entity === null) continue;
    let entry = seen.get(r.entity);
    if (!entry) {
      entry = { named: false, sequence: null };
      seen.set(r.entity, entry);
    }
    if (r.uniprot || r.gene) entry.named = true;
    if (entry.sequence === null && r.sequence) entry.sequence = r.sequence;
  }
  const out = new Set<string>();
  for (const [entity, { named, sequence }] of seen) {
    if (named) continue;
    const length = foldLength(sequence);
    if (length === 0 || length > maxResidues) out.add(entity);
  }
  return out;
}

/**
 * The entity a tile opens on by itself, and whether the source's limits moved
 * it off the entity it would have opened on without them (the plain default
 * order of `chooseEntity`).
 *
 * It is the first entity in that order that the source can draw. When none
 * can, it is the plain default and `steered` is false, so the tile shows
 * today's pick with today's explanation.
 */
export function chooseDefaultEntity(args: {
  rowEntities: readonly string[];
  available: readonly string[];
  unrenderable: ReadonlySet<string>;
}): { entity: string | null; steered: boolean } {
  const { rowEntities, available, unrenderable } = args;
  const plain = chooseEntity({ fromFilters: null, picked: null, rowEntities, available });
  const entity = chooseEntity({
    fromFilters: null,
    picked: null,
    rowEntities,
    available,
    unrenderable,
  });
  return { entity, steered: entity !== plain };
}

/**
 * The entities of `available` a tile may adopt the dashboard's agreed opening
 * from: those the source can draw. When none can, all of them, so a tile that
 * can draw nothing keeps following the other tiles.
 */
export function renderableEntities(
  available: readonly string[],
  unrenderable: ReadonlySet<string>,
): readonly string[] {
  if (unrenderable.size === 0) return available;
  const ok = available.filter((e) => !unrenderable.has(e));
  return ok.length > 0 ? ok : available;
}

/**
 * Which chains a sequence track draws and which rows each strip gets. A complex
 * numbers every chain on its own (each restarts at 1), so chains cannot share a
 * residue axis: the track stacks one strip per chain. Pure, unit-tested in
 * `chainStrips.test.ts`.
 */

import { numberOrNull, rowIndicesWhere, stringOrNull } from './rendererData';
import type { ScrollSync, ScrollSyncTarget, StripResidue } from './types';

/** Columns a residue frame is read from; unset roles are left out. */
export interface ChainFrameColumns {
  entityCol: string | null | undefined;
  positionCol: string;
  chainCol: string;
  residueCol?: string | null;
  valueCol?: string | null;
  categoryCol?: string | null;
}

/** Widest residue width the sequence track offers, CSS px per residue. */
export const SEQUENCE_RESIDUE_WIDTH_MAX_PX = 24;

/**
 * Chains differ in length, so a peer may clamp to a smaller `scrollLeft` than
 * the one it was given. The scroll event that write raises would bounce the
 * clamped value back to its source, so the value each peer was left at is
 * remembered and its own event is not followed.
 */
export function createScrollSync(): ScrollSync {
  const peers = new Set<ScrollSyncTarget>();
  const written = new Map<ScrollSyncTarget, number>();
  return {
    register(el) {
      peers.add(el);
      return () => {
        peers.delete(el);
        written.delete(el);
      };
    },
    follow(el) {
      const echo = written.get(el) === el.scrollLeft;
      written.delete(el);
      if (echo) return;
      const x = el.scrollLeft;
      for (const peer of peers) {
        if (peer === el || peer.scrollLeft === x) continue;
        const before = peer.scrollLeft;
        peer.scrollLeft = x;
        if (peer.scrollLeft !== before) written.set(peer, peer.scrollLeft);
      }
    },
  };
}

export interface ChainStrip {
  /** Chain id; null when the table has no chain column. */
  chain: string | null;
  residues: StripResidue[];
}

type Frame = Record<string, unknown[]>;

/** Chains of `entity`, in table order (empty when the frame has no chain column). */
export function chainsOfEntity(
  frame: Frame | null | undefined,
  entityCol: string | null | undefined,
  chainCol: string,
  entity: string | null,
): string[] {
  const col = frame?.[chainCol];
  if (!frame || !col) return [];
  const seen = new Set<string>();
  for (const i of rowIndicesWhere(frame, entityCol, entity)) {
    const c = stringOrNull(col[i]);
    if (c != null) seen.add(c);
  }
  return Array.from(seen);
}

/**
 * The chains on screen: all of them by default, or the one the reader picked
 * (a pick that is not a chain of this entity falls back to all). An entity with
 * a single chain, or no chain column, is one strip.
 */
export function chainsShown(chains: readonly string[], picked: string | null | undefined): string[] {
  if (chains.length <= 1) return [...chains];
  return picked && chains.includes(picked) ? [picked] : [...chains];
}

/**
 * One strip per shown chain, each with its own residues. With at most one chain
 * the rows are not split by chain at all (the table may carry no chain id on
 * them), exactly as a single-chain entity always drew.
 */
export function residuesByChain(
  frame: Frame | null | undefined,
  columns: ChainFrameColumns,
  entity: string | null,
  chains: readonly string[],
  picked: string | null | undefined,
): ChainStrip[] {
  if (!frame) return [];
  const pos = frame[columns.positionCol] ?? [];
  const letters = columns.residueCol ? frame[columns.residueCol] : undefined;
  const values = columns.valueCol ? frame[columns.valueCol] : undefined;
  const cats = columns.categoryCol ? frame[columns.categoryCol] : undefined;
  const chainOf = chains.length > 1 ? frame[columns.chainCol] : undefined;
  const wanted = chains.length > 1 ? chainsShown(chains, picked) : [chains[0] ?? null];
  const strips = new Map<string | null, StripResidue[]>(wanted.map((c) => [c, []]));
  for (const i of rowIndicesWhere(frame, columns.entityCol, entity)) {
    const p = numberOrNull(pos[i]);
    if (p == null) continue;
    const c = chainOf ? stringOrNull(chainOf[i]) : (chains[0] ?? null);
    const out = strips.get(c);
    if (!out) continue;
    out.push({
      position: p,
      letter: letters ? stringOrNull(letters[i]) : null,
      value: values ? numberOrNull(values[i]) : null,
      category: cats ? stringOrNull(cats[i]) : null,
    });
  }
  return wanted.map((chain) => ({ chain, residues: strips.get(chain) ?? [] }));
}

/**
 * Whether a selection or highlight naming `eventChain` lands on the strip of
 * `chain`. On a single chain everything does; on a complex an event that names
 * another chain is on another axis, and one that names none lands everywhere.
 */
export function onChain(
  multiChain: boolean,
  eventChain: string | null | undefined,
  chain: string | null,
): boolean {
  return !multiChain || !eventChain || eventChain === chain;
}

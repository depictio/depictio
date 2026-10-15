/**
 * Pure logic of the written sequence (`layout: structure_text`): wrapping the
 * structure's residues into numbered lines of ten-letter blocks, and which
 * letters a pick, a hover or a variant marks. No React, no DOM, so vitest
 * covers it in node.
 */

import type { ResidueSpan } from './viewer';

/** One letter of the written sequence. */
export interface TextResidue {
  chain: string;
  /** Author residue number (structure numbering). */
  position: number;
  /** One-letter code, 'X' for anything non-standard. */
  letter: string;
}

/** One line: a run of residues of one chain, numbered by its first residue. */
export interface TextLine {
  chain: string;
  /** Index of the line's first residue in the flat residue list. */
  offset: number;
  residues: TextResidue[];
}

/** The lines of one chain, with its name when the structure has several. */
export interface TextChainBlock {
  chain: string;
  lines: TextLine[];
}

export const BLOCK_SIZE = 10;

/** Characters the line numbers need: the widest residue number, sign included. */
export function labelChars(residues: readonly TextResidue[]): number {
  let widest = 1;
  for (const r of residues) widest = Math.max(widest, String(r.position).length);
  return widest;
}

/**
 * Letters per line for a text area `width` px wide: whole blocks of
 * `blockSize` letters (each followed by a one-character gap) after the line
 * number and its gap. Never less than one block, so a narrow tile wraps
 * rather than overflows sideways only when even one block does not fit.
 */
export function lettersPerLine(
  width: number,
  charWidth: number,
  labelWidthChars: number,
  blockSize = BLOCK_SIZE,
): number {
  if (!(width > 0) || !(charWidth > 0)) return blockSize;
  const room = width - (labelWidthChars + 1) * charWidth;
  const blocks = Math.floor((room + charWidth) / ((blockSize + 1) * charWidth));
  return Math.max(1, blocks) * blockSize;
}

/**
 * Wrap residues into lines of `perLine` letters, one block of lines per chain
 * (a new chain starts a new line). The residues keep their file order; a gap
 * in the numbering does not break a line, the next line's number says where
 * it resumes.
 */
export function wrapResidues(
  residues: readonly TextResidue[],
  perLine: number,
): TextChainBlock[] {
  const step = Math.max(1, Math.floor(perLine));
  const out: TextChainBlock[] = [];
  let block: TextChainBlock | null = null;
  let line: TextLine | null = null;
  for (let i = 0; i < residues.length; i += 1) {
    const r = residues[i];
    if (block === null || block.chain !== r.chain) {
      block = { chain: r.chain, lines: [] };
      out.push(block);
      line = null;
    }
    if (line === null || line.residues.length >= step) {
      line = { chain: r.chain, offset: i, residues: [] };
      block.lines.push(line);
    }
    line.residues.push(r);
  }
  return out;
}

/** The residues of a line cut into blocks of `blockSize` letters. */
export function lineBlocks(line: TextLine, blockSize = BLOCK_SIZE): TextResidue[][] {
  const out: TextResidue[][] = [];
  for (let i = 0; i < line.residues.length; i += blockSize) {
    out.push(line.residues.slice(i, i + blockSize));
  }
  return out;
}

/** Whether a span covers a residue. A span naming no chain covers the
 *  positions on every chain, as the 3D view draws it. */
export function spanCovers(span: ResidueSpan | null, chain: string, position: number): boolean {
  if (!span) return false;
  if (span.chain && span.chain !== chain) return false;
  return position >= span.start && position <= span.end;
}

/**
 * The part of a span inside a line, as indices into the line's residues
 * (`[first, last]`), or null. Lines memoise on these two numbers, so a hover
 * re-renders the one or two lines it enters and leaves, not the whole text.
 */
export function spanInLine(span: ResidueSpan | null, line: TextLine): [number, number] | null {
  if (!span) return null;
  let first = -1;
  let last = -1;
  line.residues.forEach((r, i) => {
    if (spanCovers(span, r.chain, r.position)) {
      if (first === -1) first = i;
      last = i;
    }
  });
  return first === -1 ? null : [first, last];
}

/** Lookup key of a residue in the variant set. */
export function textKey(chain: string, position: number): string {
  return `${chain}:${position}`;
}

/**
 * Which letters of a line carry a variant, as a string of '1' and '0' (a
 * primitive, so the line's memo compares it by value).
 */
export function variantMask(line: TextLine, variants: ReadonlySet<string>): string {
  if (variants.size === 0) return '';
  let mask = '';
  let any = false;
  for (const r of line.residues) {
    const hit = variants.has(textKey(r.chain, r.position)) || variants.has(textKey('', r.position));
    mask += hit ? '1' : '0';
    any = any || hit;
  }
  return any ? mask : '';
}

/** The first residue a span covers, as an index into the flat list, or -1. */
export function firstCoveredIndex(
  residues: readonly TextResidue[],
  span: ResidueSpan | null,
): number {
  if (!span) return -1;
  return residues.findIndex((r) => spanCovers(span, r.chain, r.position));
}

/** The residue a letter element names through its `data-i` attribute. */
export function residueAtIndex(
  residues: readonly TextResidue[],
  raw: string | null | undefined,
): TextResidue | null {
  if (raw == null || raw === '') return null;
  const i = Number(raw);
  return Number.isInteger(i) && i >= 0 && i < residues.length ? residues[i] : null;
}

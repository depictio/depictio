import { describe, expect, it } from 'vitest';

import { clickRange } from './residueData';
import {
  firstCoveredIndex,
  labelChars,
  lettersPerLine,
  lineBlocks,
  residueAtIndex,
  spanCovers,
  spanInLine,
  textKey,
  variantMask,
  wrapResidues,
  type TextResidue,
} from './sequenceLines';

const chainOf = (chain: string, from: number, n: number): TextResidue[] =>
  Array.from({ length: n }, (_, i) => ({
    chain,
    position: from + i,
    letter: 'ACDEFGHIKLMNPQRSTVWY'[i % 20],
  }));

describe('wrapping and numbering', () => {
  it('fits whole blocks of ten after the line number', () => {
    // 3 label chars + 1 gap = 4 chars; a block is 10 letters + 1 gap.
    expect(lettersPerLine(4 * 7 + 11 * 7 * 3 - 7, 7, 3)).toBe(30);
    expect(lettersPerLine(4 * 7 + 11 * 7 * 3 - 8, 7, 3)).toBe(20);
    // A pane narrower than one block still holds one block.
    expect(lettersPerLine(40, 7, 3)).toBe(10);
    // Before the pane is measured.
    expect(lettersPerLine(0, 7, 3)).toBe(10);
  });

  it('sizes the line numbers on the widest residue number', () => {
    expect(labelChars(chainOf('A', 1, 9))).toBe(1);
    expect(labelChars(chainOf('A', 95, 10))).toBe(3);
    expect(labelChars([{ chain: 'A', position: -12, letter: 'M' }])).toBe(3);
  });

  it('numbers each line by its first residue, in structure numbering', () => {
    const residues = chainOf('A', 24, 45);
    const [block] = wrapResidues(residues, 20);
    expect(block.lines.map((l) => l.residues[0].position)).toEqual([24, 44, 64]);
    expect(block.lines.map((l) => l.offset)).toEqual([0, 20, 40]);
    expect(block.lines[2].residues).toHaveLength(5);
    expect(lineBlocks(block.lines[0]).map((b) => b.length)).toEqual([10, 10]);
    expect(lineBlocks(block.lines[2]).map((b) => b.length)).toEqual([5]);
  });

  it('keeps a numbering gap inside a line and starts a new block per chain', () => {
    const residues = [...chainOf('A', 1, 5), ...chainOf('A', 40, 5), ...chainOf('B', 1, 3)];
    const blocks = wrapResidues(residues, 10);
    expect(blocks.map((b) => b.chain)).toEqual(['A', 'B']);
    expect(blocks[0].lines).toHaveLength(1);
    expect(blocks[0].lines[0].residues.map((r) => r.position)).toEqual([1, 2, 3, 4, 5, 40, 41, 42, 43, 44]);
    expect(blocks[1].lines[0].offset).toBe(10);
  });
});

describe('marks', () => {
  const residues = [...chainOf('A', 1, 30), ...chainOf('B', 1, 30)];
  const [a, b] = wrapResidues(residues, 10);

  it('covers a span on its chain, or on every chain when it names none', () => {
    expect(spanCovers({ chain: 'A', start: 5, end: 7 }, 'A', 6)).toBe(true);
    expect(spanCovers({ chain: 'A', start: 5, end: 7 }, 'B', 6)).toBe(false);
    expect(spanCovers({ chain: null, start: 5, end: 7 }, 'B', 6)).toBe(true);
    expect(spanCovers(null, 'A', 6)).toBe(false);
  });

  it('cuts a range into the lines it crosses', () => {
    const span = { chain: 'A', start: 8, end: 13 };
    expect(spanInLine(span, a.lines[0])).toEqual([7, 9]);
    expect(spanInLine(span, a.lines[1])).toEqual([0, 2]);
    expect(spanInLine(span, a.lines[2])).toBeNull();
    expect(spanInLine(span, b.lines[0])).toBeNull();
    expect(firstCoveredIndex(residues, span)).toBe(7);
    expect(firstCoveredIndex(residues, { chain: 'B', start: 2, end: 2 })).toBe(31);
  });

  it('marks variant letters, by chain or by position alone', () => {
    const variants = new Set([textKey('A', 3), textKey('', 12)]);
    expect(variantMask(a.lines[0], variants)).toBe('0010000000');
    expect(variantMask(a.lines[1], variants)).toBe('0100000000');
    expect(variantMask(b.lines[1], variants)).toBe('0100000000');
    // A line without variants carries an empty mask, so it memoises as one.
    expect(variantMask(a.lines[2], variants)).toBe('');
    expect(variantMask(a.lines[0], new Set())).toBe('');
  });
});

describe('letter gestures', () => {
  const residues = chainOf('A', 101, 30);

  it('reads the residue a letter names, and nothing from a stray target', () => {
    expect(residueAtIndex(residues, '4')).toMatchObject({ chain: 'A', position: 105 });
    expect(residueAtIndex(residues, undefined)).toBeNull();
    expect(residueAtIndex(residues, '')).toBeNull();
    expect(residueAtIndex(residues, '30')).toBeNull();
    expect(residueAtIndex(residues, '1.5')).toBeNull();
  });

  it('turns a click into one residue and a shift-click into a range from the last pick', () => {
    const first = residueAtIndex(residues, '4');
    expect(first).not.toBeNull();
    const anchor = first!.position;
    expect(clickRange(null, anchor, false)).toEqual({ start: 105, end: 105 });
    const second = residueAtIndex(residues, '0')!;
    // Backwards is fine: the range is ordered.
    expect(clickRange(anchor, second.position, true)).toEqual({ start: 101, end: 105 });
    // Shift with no pick yet is a plain click.
    expect(clickRange(null, second.position, true)).toEqual({ start: 101, end: 101 });
  });
});

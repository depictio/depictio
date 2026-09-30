/**
 * The written sequence of `layout: structure_text`: the structure's residues as
 * plain monospace text, wrapped to the pane in numbered lines of ten-letter
 * blocks, one clickable letter per residue.
 *
 * Controlled and data-agnostic like the protein panels: the renderer passes
 * the residues, the picked span, the hovered span and the variant positions,
 * and gets gestures back in structure numbering. One listener per gesture on
 * the text area reads the letter's `data-i` (event delegation), so a long
 * protein does not carry a handler per letter.
 */

import React, { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Box, Text } from '@mantine/core';

import {
  firstCoveredIndex,
  labelChars,
  lettersPerLine,
  lineBlocks,
  residueAtIndex,
  spanInLine,
  variantMask,
  wrapResidues,
  type TextLine,
  type TextResidue,
} from './sequenceLines';
import { spanKey, type ResidueSpan } from './viewer';

export interface SequenceTextProps {
  residues: readonly TextResidue[];
  /** Picked residue or range: red, underlined, on a light red background. */
  selected: ResidueSpan | null;
  /** Hovered residue (here, in 3D or in another tile): outlined. */
  highlight: ResidueSpan | null;
  /** `chain:position` keys of the bound table's variants: red letters. */
  variants: ReadonlySet<string>;
  /** Scroll a pick made elsewhere into view. */
  followSelection: boolean;
  onHover(residue: TextResidue | null): void;
  /** Absent on read-only hosts: the letters are not clickable. */
  onPick?: (residue: TextResidue, extend: boolean) => void;
}

const FONT: React.CSSProperties = {
  fontFamily: 'var(--mantine-font-family-monospace)',
  fontSize: 'var(--mantine-font-size-xs)',
  lineHeight: 1.7,
};

const PICKED: React.CSSProperties = {
  color: 'var(--mantine-color-red-text)',
  background: 'var(--mantine-color-red-light)',
  textDecoration: 'underline',
  fontWeight: 700,
};
const VARIANT: React.CSSProperties = {
  color: 'var(--mantine-color-red-text)',
  fontWeight: 700,
};
const HOVERED: React.CSSProperties = {
  outline: '1px solid var(--mantine-color-pink-filled)',
  outlineOffset: -1,
};

interface LineProps {
  line: TextLine;
  labelWidth: number;
  picked: [number, number] | null;
  hovered: [number, number] | null;
  mask: string;
  clickable: boolean;
}

/** One numbered line. Memoised on primitives: a hover re-renders the lines it
 *  enters and leaves, not the whole text. */
const Line = memo(
  function Line({ line, labelWidth, picked, hovered, mask, clickable }: LineProps) {
    let k = -1;
    return (
      <div style={{ display: 'flex', whiteSpace: 'pre' }}>
        <span
          style={{
            width: `${labelWidth}ch`,
            flex: '0 0 auto',
            textAlign: 'right',
            marginRight: '1ch',
            color: 'var(--mantine-color-dimmed)',
            userSelect: 'none',
          }}
        >
          {line.residues[0]?.position}
        </span>
        {lineBlocks(line).map((block, b) => (
          <span key={b} style={{ marginRight: '1ch' }}>
            {block.map((r) => {
              k += 1;
              const isPicked = picked !== null && k >= picked[0] && k <= picked[1];
              const isHovered = hovered !== null && k >= hovered[0] && k <= hovered[1];
              const isVariant = mask[k] === '1';
              return (
                <span
                  key={k}
                  data-i={line.offset + k}
                  style={{
                    cursor: clickable ? 'pointer' : 'default',
                    ...(isVariant ? VARIANT : null),
                    ...(isPicked ? PICKED : null),
                    ...(isHovered ? HOVERED : null),
                  }}
                >
                  {r.letter}
                </span>
              );
            })}
          </span>
        ))}
      </div>
    );
  },
  (a, b) =>
    a.line === b.line &&
    a.labelWidth === b.labelWidth &&
    a.mask === b.mask &&
    a.clickable === b.clickable &&
    a.picked?.[0] === b.picked?.[0] &&
    a.picked?.[1] === b.picked?.[1] &&
    a.hovered?.[0] === b.hovered?.[0] &&
    a.hovered?.[1] === b.hovered?.[1],
);

/** Width of one monospace character in the text's font, measured once. */
function useCharWidth(probe: React.RefObject<HTMLSpanElement>): number {
  const [width, setWidth] = useState(7.2);
  useLayoutEffect(() => {
    const el = probe.current;
    if (!el) return;
    const w = el.getBoundingClientRect().width / 10;
    if (w > 0) setWidth(w);
  }, [probe]);
  return width;
}

const SequenceText: React.FC<SequenceTextProps> = ({
  residues,
  selected,
  highlight,
  variants,
  followSelection,
  onHover,
  onPick,
}) => {
  const scroller = useRef<HTMLDivElement | null>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const charWidth = useCharWidth(probe);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      setWidth((prev) => (prev === w ? prev : w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const labelWidth = useMemo(() => labelChars(residues), [residues]);
  const perLine = lettersPerLine(width, charWidth, labelWidth);
  const blocks = useMemo(() => wrapResidues(residues, perLine), [residues, perLine]);
  const multiChain = blocks.length > 1;
  const masks = useMemo(
    () => new Map(blocks.flatMap((b) => b.lines.map((l) => [l, variantMask(l, variants)] as const))),
    [blocks, variants],
  );

  // A pick made elsewhere scrolls into view when it is out of sight.
  const selectedKey = spanKey(selected);
  useEffect(() => {
    if (!followSelection || !selected) return;
    const box = scroller.current;
    const i = firstCoveredIndex(residues, selected);
    const el = i >= 0 ? box?.querySelector<HTMLElement>(`[data-i="${i}"]`) : null;
    if (!box || !el) return;
    // The text area is positioned, so it is the letters' offset parent.
    const top = el.offsetTop;
    if (top < box.scrollTop || top + el.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTop = Math.max(0, top - box.clientHeight / 3);
    }
    // `selectedKey` carries `selected`'s content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, followSelection, residues, perLine]);

  // The residue of the letter under an event, read from its `data-i`.
  const residueOfEvent = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const el = (e.target as HTMLElement).closest<HTMLElement>('[data-i]');
      return residueAtIndex(residues, el?.dataset.i);
    },
    [residues],
  );
  const lastHover = useRef<TextResidue | null>(null);
  const onMouseOver = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const r = residueOfEvent(e);
      if (r === lastHover.current) return;
      lastHover.current = r;
      onHover(r);
    },
    [residueOfEvent, onHover],
  );
  const onMouseLeave = useCallback(() => {
    if (lastHover.current === null) return;
    lastHover.current = null;
    onHover(null);
  }, [onHover]);
  const onClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!onPick) return;
      const r = residueOfEvent(e);
      if (r) onPick(r, e.shiftKey);
    },
    [residueOfEvent, onPick],
  );

  return (
    <div
      ref={scroller}
      className="depictio-molecule-sequence-text"
      onMouseOver={onMouseOver}
      onMouseLeave={onMouseLeave}
      onClick={onClick}
      // Shift-click extends a pick; it must not start a text selection.
      onMouseDown={(e) => {
        if (e.shiftKey) e.preventDefault();
      }}
      style={{
        ...FONT,
        position: 'absolute',
        inset: 0,
        overflowY: 'auto',
        overflowX: 'hidden',
        padding: '4px 8px',
      }}
    >
      <span ref={probe} aria-hidden style={{ position: 'absolute', visibility: 'hidden' }}>
        0000000000
      </span>
      {blocks.map((block) => (
        <Box key={block.chain || '-'} mb={multiChain ? 4 : 0}>
          {multiChain ? (
            <Text size="xs" c="dimmed" fw={600} style={{ userSelect: 'none' }}>
              {`Chain ${block.chain || '-'}`}
            </Text>
          ) : null}
          {block.lines.map((line) => (
            <Line
              key={line.offset}
              line={line}
              labelWidth={labelWidth}
              picked={spanInLine(selected, line)}
              hovered={spanInLine(highlight, line)}
              mask={masks.get(line) ?? ''}
              clickable={Boolean(onPick)}
            />
          ))}
        </Box>
      ))}
    </div>
  );
};

export default SequenceText;

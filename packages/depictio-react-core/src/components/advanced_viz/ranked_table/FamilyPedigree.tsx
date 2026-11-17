import React, { useId, useMemo } from 'react';

import {
  layoutPedigree,
  type AffectedStatus,
  type PedigreeFamily,
  type Sex,
} from '../pedigree/pedigreeLayout';
import {
  GENOTYPE_WORD,
  symbolFill,
  type GenotypeClass,
  type SymbolFill,
} from './familyData';
import { LABEL_OFFSET, labelBaseline, markerReach, probandMarker } from './probandMarker';

/**
 * A small pedigree for the ranked table's pinned popover, with the carriers of
 * one variant filled by genotype: hom-alt solid, het half, ref open, no call
 * grey. Affected status is a red ring, the proband an arrow and a "P" whose
 * geometry (`probandMarker.ts`) follows the symbol's outline and leaves the
 * label under it clear.
 *
 * Its own component, not a mode of `PedigreeRenderer`: that one draws status as
 * the fill, which this drawing gives to the genotype. The tree comes from the
 * shared `pedigree/pedigreeLayout.ts`. Colours are Mantine tokens set as CSS
 * variables, so both colour schemes follow the theme.
 */

const SYMBOL = 18;
/** Width of the red ring an affected symbol wears, around the symbol. */
const RING = 3.5;
const MINI_LAYOUT = {
  slot: 54,
  rowHeight: 62,
  symbol: SYMBOL,
  top: 6,
  // A lone parent's drop starts below its label.
  labelSpace: LABEL_OFFSET + 3,
} as const;
const PAD = 6;
const LABEL_CHARS = 8;
/** Room kept on the left of the tree for the proband's arrow and P, whichever
 *  symbol it points at. */
const MARKER_ROOM = markerReach(SYMBOL / 2, RING);
const MARGIN_LEFT = Math.ceil(MARKER_ROOM.left) - PAD;

const INK = 'var(--mantine-color-text)';
const BODY = 'var(--mantine-color-body)';
const CARRIER = 'var(--mantine-primary-color-filled)';
const AFFECTED = 'var(--mantine-color-red-filled)';
const NO_CALL = 'var(--mantine-color-gray-5)';

function shorten(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, Math.max(1, max - 1))}…` : text;
}

const diamond = (r: number) => `0,${-r} ${r},0 0,${r} ${-r},0`;

/** The outline of a symbol of `size`: square male, circle female, diamond unknown. */
const Outline: React.FC<{
  sex: Sex;
  size: number;
  style: React.CSSProperties;
  clipPath?: string;
  strokeDasharray?: string;
  strokeWidth?: number;
}> = ({ sex, size, style, clipPath, strokeDasharray, strokeWidth = 1.5 }) => {
  const half = size / 2;
  const common = { style, clipPath, strokeDasharray, strokeWidth };
  if (sex === 'female') return <circle r={half} {...common} />;
  if (sex === 'male') return <rect x={-half} y={-half} width={size} height={size} {...common} />;
  return <polygon points={diamond(half * 1.2)} {...common} />;
};

/** The ring around a symbol of `size`, which scales with it (3.5 at the popover's 18). */
const ringOf = (size: number): number => (RING * size) / SYMBOL;

/** The proband's arrow and "P" for a symbol of `size`, centred on (0, 0). It
 *  scales up with a larger symbol, and keeps its readable size on the small
 *  legend symbol. */
export const ProbandMark: React.FC<{
  sex: Sex;
  size: number;
  ring: boolean;
}> = ({ sex, size, ring }) => {
  const scale = Math.max(size / SYMBOL, 1);
  const m = probandMarker(sex, size / 2, { ring: ring ? ringOf(size) : 0, scale });
  return (
    <g style={{ stroke: INK, fill: INK }} aria-hidden="true">
      <line x1={m.tail.x} y1={m.tail.y} x2={m.tip.x} y2={m.tip.y} strokeWidth={1.5} strokeLinecap="round" />
      <polygon
        points={`${m.tip.x},${m.tip.y} ${m.head[0].x},${m.head[0].y} ${m.head[1].x},${m.head[1].y}`}
        strokeWidth={0.5}
        strokeLinejoin="round"
      />
      <text
        x={m.letter.x}
        y={m.letter.y}
        fontSize={9 * scale}
        fontWeight={700}
        stroke="none"
        textAnchor="middle"
        dominantBaseline="central"
      >
        P
      </text>
    </g>
  );
};

/** One symbol centred on (0, 0). `clipId` names the left-half clip for a het. */
export const FamilySymbol: React.FC<{
  sex: Sex;
  status: AffectedStatus;
  fill: SymbolFill;
  deceased?: boolean;
  proband?: boolean;
  size: number;
  clipId: string;
}> = ({ sex, status, fill, deceased, proband, size, clipId }) => {
  const half = size / 2;
  const grey = fill === 'grey';
  return (
    <>
      {status === 'affected' ? (
        <Outline
          sex={sex}
          size={size + 2 * ringOf(size)}
          style={{ fill: 'none', stroke: AFFECTED }}
          strokeWidth={2}
        />
      ) : null}
      <Outline
        sex={sex}
        size={size}
        style={{
          fill: grey ? NO_CALL : BODY,
          fillOpacity: grey ? 0.45 : 1,
          stroke: INK,
        }}
        strokeDasharray={grey ? '3 2' : undefined}
      />
      {fill === 'full' ? (
        <Outline sex={sex} size={size} style={{ fill: CARRIER, stroke: INK }} />
      ) : null}
      {fill === 'half' ? (
        <>
          <Outline
            sex={sex}
            size={size}
            style={{ fill: CARRIER, stroke: 'none' }}
            clipPath={`url(#${clipId})`}
          />
          <Outline sex={sex} size={size} style={{ fill: 'none', stroke: INK }} />
        </>
      ) : null}
      {deceased ? (
        <line
          x1={-half - 4}
          y1={half + 4}
          x2={half + 4}
          y2={-half - 4}
          style={{ stroke: INK }}
          strokeWidth={1.5}
        />
      ) : null}
      {proband ? <ProbandMark sex={sex} size={size} ring={status === 'affected'} /> : null}
    </>
  );
};

/** The left half of any symbol, in the symbol's own coordinates. */
export const LeftHalfClip: React.FC<{ id: string }> = ({ id }) => (
  <defs>
    <clipPath id={id}>
      <rect x={-200} y={-200} width={200} height={400} />
    </clipPath>
  </defs>
);

const LEGEND: { label: string; fill: SymbolFill }[] = [
  { label: 'Hom alt', fill: 'full' },
  { label: 'Het', fill: 'half' },
  { label: 'Ref', fill: 'empty' },
  { label: 'No call', fill: 'grey' },
];

interface Props {
  family: PedigreeFamily;
  /** Class per person key. Null: no genotypes bound, symbols are drawn open. */
  carriers: ReadonlyMap<string, GenotypeClass> | null;
  probandKey: string | null;
}

/** The family tree with carriers, scaled to the width it is given. */
const FamilyPedigree: React.FC<Props> = ({ family, carriers, probandKey }) => {
  const clipId = `rt-clip-${useId().replace(/:/g, '')}`;
  const layout = useMemo(() => layoutPedigree([family], MINI_LAYOUT), [family]);
  const placed = layout.families[0]?.people ?? [];
  if (placed.length === 0) return null;
  const width = layout.width + 2 * PAD + MARGIN_LEFT;
  const height = layout.height + 14;

  return (
    <div>
      <svg
        viewBox={`${-MARGIN_LEFT} 0 ${width} ${height}`}
        width="100%"
        style={{ display: 'block', maxHeight: 200 }}
        role="img"
        aria-label={`Family of ${placed.filter((p) => !p.person.placeholder).length} individuals`}
      >
        <LeftHalfClip id={clipId} />
        <g transform={`translate(${PAD} 0)`}>
          {layout.families[0].lines.map((l, i) => (
            <line
              key={`${l.kind}-${i}`}
              x1={l.x1}
              y1={l.y1}
              x2={l.x2}
              y2={l.y2}
              style={{ stroke: INK }}
              strokeWidth={1.2}
              strokeLinecap="square"
            />
          ))}
          {placed.map(({ person, x, y }) => {
            const cls = carriers ? (carriers.get(person.key) ?? 'missing') : 'ref';
            const fill = person.placeholder ? 'empty' : symbolFill(cls);
            return (
              <g key={person.key} transform={`translate(${x} ${y})`}>
                <title>
                  {person.placeholder
                    ? `${person.id}: named as a parent, not in the table`
                    : `${person.label}${carriers ? `: ${GENOTYPE_WORD[cls]}` : ''}${
                        person.status === 'affected' ? ', affected' : ''
                      }${person.key === probandKey ? ', proband' : ''}`}
                </title>
                <FamilySymbol
                  sex={person.sex}
                  status={person.status}
                  fill={fill}
                  deceased={person.deceased}
                  proband={person.key === probandKey}
                  size={MINI_LAYOUT.symbol}
                  clipId={clipId}
                />
                {!person.placeholder ? (
                  <text
                    y={labelBaseline(MINI_LAYOUT.symbol / 2)}
                    fontSize={9}
                    textAnchor="middle"
                    style={{ fill: INK }}
                    pointerEvents="none"
                  >
                    {shorten(person.label, LABEL_CHARS)}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
      </svg>
      {carriers ? (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '2px 10px',
            alignItems: 'center',
            marginTop: 4,
            color: 'var(--mantine-color-dimmed)',
            fontSize: 'var(--mantine-font-size-xs)',
          }}
        >
          <svg width={0} height={0} aria-hidden="true" style={{ position: 'absolute' }}>
            <LeftHalfClip id={`${clipId}-legend`} />
          </svg>
          {LEGEND.map((item) => (
            <span key={item.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <svg width={16} height={16} aria-hidden="true">
                <g transform="translate(8 8)">
                  <FamilySymbol
                    sex="female"
                    status="unaffected"
                    fill={item.fill}
                    size={10}
                    clipId={`${clipId}-legend`}
                  />
                </g>
              </svg>
              {item.label}
            </span>
          ))}
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <svg width={16} height={16} aria-hidden="true">
              <g transform="translate(8 8)">
                <FamilySymbol
                  sex="female"
                  status="affected"
                  fill="empty"
                  size={8}
                  clipId={`${clipId}-legend`}
                />
              </g>
            </svg>
            Affected
          </span>
          {probandKey ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <svg width={34} height={28} aria-hidden="true" style={{ overflow: 'visible' }}>
                <g transform="translate(25 6)">
                  <FamilySymbol
                    sex="female"
                    status="unaffected"
                    fill="empty"
                    size={10}
                    proband
                    clipId={`${clipId}-legend`}
                  />
                </g>
              </svg>
              Proband
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

export default FamilyPedigree;

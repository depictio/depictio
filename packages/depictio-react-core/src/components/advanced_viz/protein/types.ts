/**
 * Prop and data types of the protein panels (`MsaPanel`, `SequenceStrip`).
 *
 * Kept apart from the components so a consumer (the `msa` and
 * `sequence_track` renderers, and `molecule_3d`'s embedded layouts) can import
 * the shapes without pulling a canvas component in. Positions are always
 * 1-based residue numbers; an MSA speaks in its REFERENCE row's numbering,
 * with the reference's own gap columns mapping to no residue.
 */

/** Residue colouring schemes an MSA offers (mirrors `MsaConfig.color_scheme`). */
export type MsaColourScheme = 'clustal' | 'zappo' | 'hydrophobicity' | 'identity' | 'none';

/** An inclusive residue range, 1-based. `end` defaults to `start`. */
export interface ResidueRange {
  start: number;
  end?: number;
}

/**
 * A transient pointer highlight passed down to a panel: residues to mark and,
 * for an MSA, sequence ids to ring. The highlight bus event
 * (`highlight/bus.ts::HighlightEvent`) maps onto it field for field.
 */
export interface ProteinHighlight {
  start: number;
  end?: number;
  rowKeys?: string[];
}

/**
 * One chain of a multi-chain reference, in its own residue numbering. The
 * reference row of a complex is its chains concatenated in this order; the
 * residue and structure tables number each chain on its own (not always from
 * 1). See `alignment.ts::parseChainLayout`.
 */
export interface ChainSegment {
  chain: string;
  /** First residue number of the chain in its own numbering. */
  first: number;
  /** Last residue number, inclusive. */
  last: number;
}

/** One aligned sequence of an MSA. */
export interface MsaRow {
  seqId: string;
  /** Aligned sequence, gaps as `-` or `.`, every row of one alignment the same length. */
  sequence: string;
  /** Row order; rank 0 is the query / reference row. */
  rank?: number | null;
  /** Identity to the reference, 0 to 1. Computed by the panel when absent. */
  identity?: number | null;
  /** Fraction of the reference the row covers, 0 to 1 (optional, shown in the tooltip). */
  coverage?: number | null;
}

/** What the pointer is over in an MSA. */
export interface MsaHover {
  /** 0-based alignment column. */
  column: number;
  /** Reference residue number under the column (concatenated numbering on a
   *  multi-chain reference), or null on a reference gap. */
  residue: number | null;
  /** With `chains`: the chain under the column and the residue's own number in it. */
  chain?: string | null;
  chainPosition?: number | null;
  /** Sequence under the pointer, null over the ruler / consensus / conservation rows. */
  seqId: string | null;
  /** Letter of that sequence at the column (a gap reads `-`). */
  letter: string | null;
}

export interface MsaPanelProps {
  /** Aligned rows in display order (the renderer sorts and caps them). */
  rows: MsaRow[];
  /** Index in `rows` of the reference row whose numbering the ruler and the
   *  selection use. Defaults to the row with rank 0, else the first row. */
  referenceIndex?: number;
  colourScheme?: MsaColourScheme;
  /** Chain layout of a multi-chain reference (concatenation order). The ruler
   *  and the tooltip then speak each chain's own numbering; ranges and hover
   *  residues passed in and out stay in concatenated reference numbering
   *  (convert with `concatRangeToChain` / `chainRangeToConcat`). */
  chains?: ChainSegment[] | null;
  /** Residue range to shade, in reference numbering. */
  selectedRange?: ResidueRange | null;
  /** Transient highlight (hover elsewhere), in reference numbering. */
  highlight?: ProteinHighlight | null;
  /** Sequence ids to mark as selected (a row click, another tile's pick). */
  selectedRowKeys?: string[];
  /** Pointer over a cell or a header column; null when it leaves. */
  onHoverColumn?: (hover: MsaHover | null) => void;
  /** Column brush released: the reference residue range it covers (reference
   *  gap columns skipped), or null for a click that clears. Omit to disable. */
  onBrushColumns?: (range: ResidueRange | null) => void;
  /** Click on a row (its id cell or any of its cells, without dragging). */
  onClickRow?: (seqId: string, modifiers: { shiftKey: boolean; metaKey: boolean }) => void;
  /** CSS height of the panel; defaults to filling its parent. */
  height?: number | string;
  /** Pixels per alignment column; defaults to fitting the width (min 1 px). */
  cellWidth?: number;
  showConsensus?: boolean;
  showConservation?: boolean;
  /** Scroll an incoming `selectedRange` / `highlight` into view. Default true. */
  followSelection?: boolean;
  /** Called once the first frame with data has been drawn. */
  onDrawn?: () => void;
}

/** One residue of a linear sequence, with its optional per-residue lanes. */
export interface StripResidue {
  position: number;
  /** One-letter amino acid. */
  letter?: string | null;
  /** Numeric lane value (pLDDT or any per-residue score). */
  value?: number | null;
  /** Categorical lane value (secondary structure, domain, consequence). */
  category?: string | null;
}

/** A span drawn on the domains lane. */
export interface StripDomain {
  start: number;
  end: number;
  label?: string | null;
  source?: string | null;
}

/** A variant drawn on the variants lane (a mini lollipop). */
export interface StripVariant {
  position: number;
  label?: string | null;
  category?: string | null;
  value?: number | null;
}

/** How the value lane is painted: AlphaFold pLDDT bands or a named colour scale. */
export type StripValueScale = 'plddt' | string;

/** What the pointer is over in a sequence strip. */
export interface StripHover {
  position: number;
  residue: StripResidue | null;
  domains: StripDomain[];
  variants: StripVariant[];
}

export interface SequenceStripProps {
  /** Residues by position (any order; duplicates keep the first). */
  residues: StripResidue[];
  domains?: StripDomain[];
  variants?: StripVariant[];
  /** Title of the value lane (`pLDDT` switches to AlphaFold confidence bands). */
  valueLabel?: string | null;
  /** Value lane colouring: `plddt` or a scale name from `utils/colorScale`. */
  valueScale?: StripValueScale;
  /** Category value to colour, for categorical lanes and variant heads. When
   *  absent the strip derives a stable map from the theme palette. */
  categoryColours?: Record<string, string>;
  selectedRange?: ResidueRange | null;
  highlight?: ProteinHighlight | null;
  onHover?: (hover: StripHover | null) => void;
  /** Brush released: the residue range, or null for a click that clears. Omit
   *  to disable brushing. A plain click selects one residue. */
  onBrush?: (range: ResidueRange | null) => void;
  /** Click on a variant head. */
  onClickVariant?: (variant: StripVariant) => void;
  /** CSS height of the strip; defaults to its natural lane height. */
  height?: number | string;
  /** Pixels per residue; defaults to fitting the width. */
  cellWidth?: number;
  showLetters?: boolean;
  /** Scroll an incoming `selectedRange` / `highlight` into view. Default true. */
  followSelection?: boolean;
  /** Called once the first frame with data has been drawn. */
  onDrawn?: () => void;
}

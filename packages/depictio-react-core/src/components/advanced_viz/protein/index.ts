/**
 * The protein panel library: canvas components shared by the `msa` and
 * `sequence_track` renderers and embedded by `molecule_3d`'s
 * `structure_msa` / `structure_sequence` layouts, and the canvas glyphs of
 * secondary structure (`ssGlyphs`) any panel can draw along a residue axis.
 *
 * Both panels are controlled and data-agnostic: the caller fetches rows,
 * resolves the selection and the highlight bus, and passes plain props. They
 * report gestures back through callbacks (`onHover*`, `onBrush*`,
 * `onClickRow`) in residue numbers (an MSA in its reference row's numbering),
 * so a consumer maps them straight onto `residueRangeFilters` and
 * `publishHighlight`.
 */
export { default as MsaPanel } from './MsaPanel';
export { default as SequenceStrip } from './SequenceStrip';
export type {
  ChainSegment,
  MsaColourScheme,
  MsaHover,
  MsaPanelProps,
  MsaRow,
  ProteinHighlight,
  ResidueRange,
  SequenceStripProps,
  StripDomain,
  StripHover,
  StripResidue,
  StripValueScale,
  StripVariant,
} from './types';
export {
  PLDDT_BANDS,
  plddtBand,
  plddtColour,
  plddtIsFractional,
  schemeColour,
  rgbCss,
} from './residueColours';
export type { PlddtBand, RGB, SecondaryStructure } from './residueColours';
export type { Run } from './sequence';
export {
  drawCoil,
  drawHelix,
  drawSecondaryStructureRuns,
  drawStrand,
  drawTurn,
  SS_GLYPH_FILLS,
  TURN_THICKNESS,
} from './ssGlyphs';
export type { SsDrawColours, SsFills, SsGeometry } from './ssGlyphs';
export {
  chainRangeToConcat,
  chainToConcat,
  concatRangeToChain,
  concatToChain,
  parseChainLayout,
  percentIdentity,
  referenceColumnMap,
} from './alignment';

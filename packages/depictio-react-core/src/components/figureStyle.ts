/**
 * Which style a figure tile is drawn in.
 *
 * Same rule as a card's `variant` (see cardVariant.ts): a figure can set its
 * own `figure_style`, and the grid section it sits in can set a
 * `figure_style` every figure in it takes unless the figure says otherwise.
 *
 * The server resolves the same rule for the plot itself (the layout overlay in
 * depictio/api/v1/services/figure/style_presets.py); the viewer resolves it
 * for what it draws around the plot: the card header, the card frame and the
 * toolbar. Mirrors `FigureStyle` in depictio/models/components/types.py.
 */
import type { Config, ModeBarDefaultButtons } from 'plotly.js';

import type { FilterSectionSpec, StoredMetadata } from '../api';
import { withSectionCardVariant } from './cardVariant';

export const FIGURE_STYLES = ['default', 'minimal'] as const;
export type FigureStyle = (typeof FIGURE_STYLES)[number];

/** A known style, or null for anything else (unset, a newer release's name,
 *  a hand-written typo): stored metadata is not validated on read. */
export function normalizeFigureStyle(value: unknown): FigureStyle | null {
  return typeof value === 'string' && (FIGURE_STYLES as readonly string[]).includes(value)
    ? (value as FigureStyle)
    : null;
}

/** The figure's own style, else its section's, else `default`. */
export function resolveFigureStyle(own: unknown, sectionStyle?: unknown): FigureStyle {
  return normalizeFigureStyle(own) ?? normalizeFigureStyle(sectionStyle) ?? 'default';
}

/** Component types a section's `figure_style` reaches. An advanced
 *  visualisation takes the style's frame and card header, not the server's
 *  plot overlay (see advanced_viz/advancedVizShowcase.ts). */
const STYLED_TYPES: ReadonlySet<string> = new Set(['figure', 'advanced_viz']);

/**
 * The metadata a grid cell hands a figure: its own, with the section's style
 * filled in when it sets none. The same object when nothing changes, so React
 * can skip the cell.
 */
export function withSectionFigureStyle(
  metadata: StoredMetadata,
  section: Pick<FilterSectionSpec, 'figure_style'> | null | undefined,
): StoredMetadata {
  if (!STYLED_TYPES.has(String(metadata.component_type))) return metadata;
  if (normalizeFigureStyle(metadata.figure_style)) return metadata;
  const fromSection = normalizeFigureStyle(section?.figure_style);
  if (!fromSection) return metadata;
  return { ...metadata, figure_style: fromSection };
}

/** Both section styles a grid cell can take: a card's and a figure's. */
export function withSectionStyles(
  metadata: StoredMetadata,
  section: Pick<FilterSectionSpec, 'card_variant' | 'figure_style'> | null | undefined,
): StoredMetadata {
  return withSectionFigureStyle(withSectionCardVariant(metadata, section), section);
}

/**
 * What picking `picked` in the figure builder stores in `figure_style`, given
 * the section's style: unset whenever the pick is what the figure would get
 * anyway, so it keeps following its section. Any other pick is stored, which
 * is how `default` comes to be written: to opt a figure out of its section.
 */
export function figureStyleForPick(
  picked: unknown,
  sectionStyle: FigureStyle | null | undefined,
): FigureStyle | null {
  const v = normalizeFigureStyle(picked) ?? 'default';
  return v === (normalizeFigureStyle(sectionStyle) ?? 'default') ? null : v;
}

/** Toolbar buttons a minimal tile does without: zoom, pan, reset and
 *  download stay; the hover-mode toggles and spike lines are noise there. */
export const MINIMAL_MODEBAR_REMOVE: ModeBarDefaultButtons[] = [
  'autoScale2d',
  'toggleSpikelines',
  'hoverClosestCartesian',
  'hoverCompareCartesian',
];

/** The Plotly `config` a figure in `style` is drawn with. A minimal tile shows
 *  its toolbar only while the pointer is over it, as a landing page's tiles do. */
export function figurePlotConfig(style: FigureStyle): Partial<Config> {
  if (style !== 'minimal') return { displaylogo: false, responsive: true };
  return {
    displaylogo: false,
    responsive: true,
    displayModeBar: 'hover',
    modeBarButtonsToRemove: [...MINIMAL_MODEBAR_REMOVE],
  };
}

/**
 * The one component-type palette: icon, label and accent per component type.
 *
 * These are the values the "new component" type grid has always used, and that
 * grid is what a user meets first, so it is the reference every other surface
 * has to agree with. It had drifted into five hand-maintained copies (the grid,
 * the catalog list, the catalog preview header, the standalone gallery, the
 * metadata inspector), three of them on stock Mantine colour names, which are
 * not the brand hexes: Mantine `violet` is #7950f2, depictio's is #7A5DC7. So a
 * "violet" badge and a brand-violet tile never actually matched.
 *
 * Colours are hex on purpose. The Mantine theme does not register the brand
 * palette (see `theme.ts`), and Mantine 7 accepts any CSS colour in `color`, so
 * the hex is both the honest value and a usable prop.
 */
import { brandColors } from './brandColors';

// Two accents the type grid uses that predate the brand palette. Kept exactly as
// the grid has them rather than snapped to a neighbour: the point of this module
// is that every surface shows the same colour, not a tidier one.
const TEXT_ACCENT = '#E91E63';
const ADVANCED_VIZ_ACCENT = '#D6336C';

export interface ComponentTypeVisual {
  /** Human label, e.g. "Advanced viz". */
  label: string;
  /** Iconify id. Written as a literal so the bundled icon subset picks it up. */
  icon: string;
  /** Accent colour (brand hex). */
  color: string;
}

export const COMPONENT_TYPE_VISUALS: Record<string, ComponentTypeVisual> = {
  figure:       { label: 'Figure',       icon: 'mdi:graph-box',                 color: brandColors.purple },
  card:         { label: 'Card',         icon: 'formkit:number',                color: brandColors.teal },
  interactive:  { label: 'Interactive',  icon: 'bx:slider-alt',                 color: brandColors.green },
  table:        { label: 'Table',        icon: 'octicon:table-24',              color: brandColors.blue },
  // The type grid draws the MultiQC logo on a transparent tile, so it has no
  // colour of its own there. Everywhere it is a dot or a badge it needs one, and
  // orange is what every copy of this map already used.
  multiqc:      { label: 'MultiQC',      icon: 'mdi:chart-line',                color: brandColors.orange },
  image:        { label: 'Image',        icon: 'mdi:image-area',                color: brandColors.pink },
  map:          { label: 'Map',          icon: 'mdi:map-marker-multiple',       color: brandColors.violet },
  text:         { label: 'Text',         icon: 'mdi:text-box-edit',             color: TEXT_ACCENT },
  advanced_viz: { label: 'Advanced viz', icon: 'mdi:chart-scatter-plot-hexbin', color: ADVANCED_VIZ_ACCENT },
};

const UNKNOWN: ComponentTypeVisual = {
  label: 'Component',
  icon: 'mdi:puzzle',
  color: '#868E96',
};

/** Visuals for a component type, falling back to a neutral placeholder.
 *  An unknown type keeps its own name as the label rather than "Component". */
export function componentTypeVisual(type: string): ComponentTypeVisual {
  return COMPONENT_TYPE_VISUALS[type] ?? { ...UNKNOWN, label: type || UNKNOWN.label };
}

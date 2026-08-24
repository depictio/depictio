/**
 * Component type registry for the stepper grid + builder dispatch.
 *
 * Order, wording and the MultiQC routing flag live here; the icon and the accent
 * come from `componentTypeVisual` in depictio-react-core, which is the one place
 * every surface (this grid, the catalog picker, the gallery, the metadata
 * inspector) reads them from.
 */
import { componentTypeVisual } from 'depictio-react-core';

import type { ComponentType } from './store/useBuilderStore';

export interface ComponentTypeMeta {
  type: ComponentType;
  label: string;
  description: string;
  icon: string;
  iconBg: string; // background color for icon tile
  /** Background for the step-2 "Selected Component" badge. Defaults to
   *  `iconBg`; set it where `iconBg` is transparent because the tile shows an
   *  SVG that carries its own colours — a transparent badge leaves the filled
   *  Badge's white label on the white page, i.e. invisible. */
  badgeBg?: string;
  /** Whether MultiQC routing applies (figure on a multiqc DC switches to multiqc). */
  multiqcAware?: boolean;
}

/** Grid entry: shared icon + accent, with this file's own order and wording. */
function entry(
  type: ComponentType,
  description: string,
  extra: { iconBg?: string; badgeBg?: string; multiqcAware?: boolean } = {},
): ComponentTypeMeta {
  const visual = componentTypeVisual(type);
  const { iconBg, ...rest } = extra;
  return {
    type,
    label: visual.label,
    description,
    icon: visual.icon,
    iconBg: iconBg ?? visual.color,
    ...rest,
  };
}

export const COMPONENT_TYPES: ComponentTypeMeta[] = [
  entry('figure', 'Interactive data visualizations', { multiqcAware: true }),
  entry('card', 'Statistical summary cards'),
  entry('interactive', 'Interactive data controls'),
  entry('table', 'Data tables and grids'),
  // The MultiQC tile draws the themed logo, not an icon on an accent tile.
  entry('multiqc', 'MultiQC quality control reports and visualizations', {
    iconBg: 'transparent',
    badgeBg: '#201637', // MultiQC brand purple, from multiqc_icon_color.svg
  }),
  entry('image', 'Interactive image grid with modal viewer'),
  entry('map', 'Geospatial map visualization with markers'),
  entry('text', 'Section headings and notes to document the dashboard'),
  entry(
    'advanced_viz',
    'Composite analysis viz: volcano, clustering, Manhattan, taxonomy bar',
  ),
];

export function getComponentTypeMeta(t: ComponentType): ComponentTypeMeta {
  return COMPONENT_TYPES.find((c) => c.type === t) || entry(t, '');
}

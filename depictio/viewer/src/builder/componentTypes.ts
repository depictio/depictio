/**
 * Component type registry for the stepper grid + builder dispatch.
 * Mirrors depictio/dash/layouts/stepper_parts/part_two.py and
 * depictio/dash/component_metadata.py so the grid order/icons/colors stay
 * visually identical to the Dash editor.
 */
import type { ComponentType } from './store/useBuilderStore';

export interface ComponentTypeMeta {
  type: ComponentType;
  label: string;
  description: string;
  icon: string;
  iconBg: string; // background color for icon tile
  /** Whether MultiQC routing applies (figure on a multiqc DC switches to multiqc). */
  multiqcAware?: boolean;
}

export const COMPONENT_TYPES: ComponentTypeMeta[] = [
  {
    type: 'figure',
    label: 'Figure',
    description: 'Interactive data visualizations',
    icon: 'mdi:graph-box',
    iconBg: '#9966cc',
    multiqcAware: true,
  },
  {
    type: 'card',
    label: 'Card',
    description: 'Statistical summary cards',
    icon: 'formkit:number',
    iconBg: '#45b8ac',
  },
  {
    type: 'interactive',
    label: 'Interactive',
    description: 'Interactive data controls',
    icon: 'bx:slider-alt',
    iconBg: '#8bc34a',
  },
  {
    type: 'table',
    label: 'Table',
    description: 'Data tables and grids',
    icon: 'octicon:table-24',
    iconBg: '#6495ed',
  },
  {
    type: 'multiqc',
    label: 'MultiQC',
    description: 'MultiQC quality control reports and visualizations',
    // For MultiQC the Dash editor uses an SVG image — we use the same
    // multiqc icon class to honor light/dark theming.
    icon: 'mdi:chart-line',
    iconBg: 'transparent',
  },
  {
    type: 'image',
    label: 'Image',
    description: 'Interactive image grid with modal viewer',
    icon: 'mdi:image-area',
    iconBg: '#e6779f',
  },
  {
    type: 'map',
    label: 'Map',
    description: 'Geospatial map visualization with markers',
    icon: 'mdi:map-marker-multiple',
    iconBg: '#7A5DC7',
  },
];

export function getComponentTypeMeta(t: ComponentType): ComponentTypeMeta {
  return (
    COMPONENT_TYPES.find((c) => c.type === t) || {
      type: t,
      label: t,
      description: '',
      icon: 'mdi:help-circle',
      iconBg: '#999',
    }
  );
}

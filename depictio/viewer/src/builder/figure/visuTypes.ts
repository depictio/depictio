/**
 * Visualization types supported by the figure UI builder.
 *
 * Source of truth is the backend's `figure_component/definitions.py`
 * (`ALLOWED_VISUALIZATIONS` + `VIZ_LABELS_DESCRIPTIONS`). At runtime the
 * builder fetches the list via `GET /figure/visualizations`. This module
 * keeps a small static fallback so the UI never blanks if the fetch fails,
 * plus the helpers that drive the Dash-style grouped flat dropdown.
 */

import type { FigureVisualizationSummary } from 'depictio-react-core';

export type VisuGroup = 'core' | 'advanced' | '3d' | 'clustering' | 'specialized';

export interface VisuTypeMeta {
  type: string;
  label: string;
  description: string;
  icon: string;
  group: VisuGroup;
}

const GROUP_ORDER: VisuGroup[] = [
  'core',
  'advanced',
  'specialized',
  '3d',
  'clustering',
];

const GROUP_LABEL: Record<VisuGroup, string> = {
  core: 'Core',
  advanced: 'Advanced',
  specialized: 'Specialized',
  '3d': '3D',
  clustering: 'Clustering',
};

const KNOWN_GROUPS = new Set<VisuGroup>([
  'core',
  'advanced',
  'specialized',
  '3d',
  'clustering',
]);

/** Static fallback list — only used if `GET /figure/visualizations` errors. */
export const VISU_TYPES_FALLBACK: VisuTypeMeta[] = [
  {
    type: 'scatter',
    label: 'Scatter Plot',
    description: 'Compare two numeric variables.',
    icon: 'mdi:chart-scatter-plot',
    group: 'core',
  },
  {
    type: 'line',
    label: 'Line Chart',
    description: 'Show a value over an ordered axis.',
    icon: 'mdi:chart-line',
    group: 'core',
  },
  {
    type: 'bar',
    label: 'Bar Chart',
    description: 'Compare a numeric value across categories.',
    icon: 'mdi:chart-bar',
    group: 'core',
  },
  {
    type: 'box',
    label: 'Box Plot',
    description: 'Distribution summary for one numeric variable.',
    icon: 'mdi:chart-box-outline',
    group: 'core',
  },
  {
    type: 'histogram',
    label: 'Histogram',
    description: 'Frequency distribution of a single numeric variable.',
    icon: 'mdi:chart-histogram',
    group: 'core',
  },
  // The rest of the curated set (`ALLOWED_VISUALIZATIONS`), so a failed fetch
  // does not hide a chart type a YAML dashboard may already declare. Labels,
  // icons and groups mirror `VIZ_LABELS_DESCRIPTIONS`, `_VISUALIZATION_ICONS`
  // and `get_visualization_group` on the backend.
  {
    type: 'violin',
    label: 'Violin Plot',
    description: 'Distribution shape with kernel density.',
    icon: 'mdi:violin',
    group: 'core',
  },
  {
    type: 'area',
    label: 'Area Chart',
    description: 'Filled line chart for cumulative quantities or composition.',
    icon: 'mdi:chart-areaspline',
    group: 'core',
  },
  {
    type: 'ecdf',
    label: 'ECDF',
    description: 'Fraction of values at or below each point.',
    icon: 'mdi:chart-bell-curve-cumulative',
    group: 'advanced',
  },
  {
    type: 'strip',
    label: 'Strip Plot',
    description: 'Every observation as a tick along a numeric axis.',
    icon: 'mdi:chart-scatter-plot',
    group: 'advanced',
  },
  {
    type: 'funnel',
    label: 'Funnel',
    description: 'Stage-by-stage drop-off (e.g. conversion).',
    icon: 'mdi:filter',
    group: 'advanced',
  },
  {
    type: 'density_heatmap',
    label: 'Density Heatmap',
    description: '2D bin counts as a heatmap.',
    icon: 'mdi:grid',
    group: 'advanced',
  },
  {
    type: 'density_contour',
    label: 'Density Contour',
    description: '2D bin counts as contour lines.',
    icon: 'mdi:chart-scatter-plot',
    group: 'advanced',
  },
  {
    type: 'heatmap',
    label: 'Heatmap',
    description: '2D grid of values, often clustered.',
    icon: 'mdi:grid-large',
    group: 'specialized',
  },
];

export function summariesToVisuMeta(
  summaries: FigureVisualizationSummary[],
): VisuTypeMeta[] {
  return summaries.map((s) => ({
    type: s.name,
    label: s.label,
    description: s.description,
    icon: s.icon,
    group: (KNOWN_GROUPS.has(s.group as VisuGroup)
      ? (s.group as VisuGroup)
      : 'specialized') as VisuGroup,
  }));
}

export function getVisuTypeMeta(
  type: string,
  list: VisuTypeMeta[] = VISU_TYPES_FALLBACK,
): VisuTypeMeta {
  return (
    list.find((v) => v.type === type) || {
      type,
      label: type,
      description: '',
      icon: 'mdi:chart-line',
      group: 'core',
    }
  );
}

export interface VisuSelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

/**
 * Produce the flat Select.data array Dash uses for the visu picker: disabled
 * `─── Group ───` headers between visualization rows. Mantine's Select
 * doesn't ship a true group primitive, so headers are rendered as disabled
 * rows just like Dash's `dmc.Select` workaround in
 * figure_component/utils.py:design_figure.
 */
export function buildVisuSelectOptions(
  items: VisuTypeMeta[],
): VisuSelectOption[] {
  const grouped: Record<VisuGroup, VisuTypeMeta[]> = {
    core: [],
    advanced: [],
    specialized: [],
    '3d': [],
    clustering: [],
  };
  for (const v of items) {
    const g = KNOWN_GROUPS.has(v.group) ? v.group : 'specialized';
    grouped[g].push(v);
  }

  const opts: VisuSelectOption[] = [];
  for (const g of GROUP_ORDER) {
    const groupItems = grouped[g];
    if (!groupItems.length) continue;
    opts.push({
      value: `__group__${g}`,
      label: `─── ${GROUP_LABEL[g]} ───`,
      disabled: true,
    });
    for (const v of groupItems.slice().sort((a, b) => a.label.localeCompare(b.label))) {
      opts.push({
        value: v.type,
        label: `  ${v.label}`,
        description: v.description,
      });
    }
  }
  return opts;
}

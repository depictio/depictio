import React from 'react';
import { ColorSwatch, Divider, Drawer, Group, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData, DashboardThemeSpec } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';

/** Plotly template choices offered at the dashboard level. Mirrors the
 *  component-level "Theme" picker options (figure/models.py), minus the
 *  mantine sentinels — "Default" already means "follow the UI theme". */
const TEMPLATE_OPTIONS = [
  { value: '', label: 'Default (follow UI theme)' },
  { value: 'plotly', label: 'Plotly' },
  { value: 'plotly_white', label: 'Plotly White' },
  { value: 'plotly_dark', label: 'Plotly Dark' },
  { value: 'ggplot2', label: 'ggplot2' },
  { value: 'seaborn', label: 'Seaborn' },
  { value: 'simple_white', label: 'Simple White' },
  { value: 'presentation', label: 'Presentation' },
];

/** Preset categorical palettes (hex, what the server hands to Plotly). */
const COLORWAY_PRESETS: { value: string; label: string; colors: string[] }[] = [
  {
    value: 'plotly',
    label: 'Plotly',
    colors: ['#636efa', '#EF553B', '#00cc96', '#ab63fa', '#FFA15A', '#19d3f3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52'],
  },
  {
    value: 'tab10',
    label: 'Tab10',
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'],
  },
  {
    value: 'set2',
    label: 'Set2',
    colors: ['#66c2a5', '#fc8d62', '#8da0cb', '#e78ac3', '#a6d854', '#ffd92f', '#e5c494', '#b3b3b3'],
  },
  {
    value: 'dark2',
    label: 'Dark2',
    colors: ['#1b9e77', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d', '#666666'],
  },
  {
    value: 'vivid',
    label: 'Vivid',
    colors: ['#E58606', '#5D69B1', '#52BCA3', '#99C945', '#CC61B0', '#24796C', '#DAA51B', '#2F8AC4', '#764E9F', '#ED645A'],
  },
];

function presetForColorway(colorway: string[] | null | undefined): string {
  if (!colorway || colorway.length === 0) return '';
  const key = JSON.stringify(colorway);
  const match = COLORWAY_PRESETS.find((preset) => JSON.stringify(preset.colors) === key);
  // A colorway written by hand in YAML that matches no preset still renders —
  // it just shows as "Custom" here.
  return match ? match.value : 'custom';
}

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Editor only: makes the "Plot theme" section editable. The viewer leaves
   *  this unset and the drawer stays read-only metadata. */
  onChangePlotTheme?: (spec: DashboardThemeSpec | null) => void;
}

/**
 * Right-side drawer with metadata about the current dashboard, plus — in the
 * editor — the dashboard-level plot theme (#397): a Plotly template and/or
 * colorway applied as the default for every figure component.
 *
 * The metadata content lives in `DashboardInfoBody`, shared with the
 * inspector's Info tab — which is what the inspector replaces this drawer
 * with when enabled.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  onChangePlotTheme,
}) => {
  const plotTheme = dashboard?.plot_theme ?? null;
  const colorwayValue = presetForColorway(plotTheme?.colorway);

  const emit = (template: string | null, colorway: string[] | null) => {
    if (!onChangePlotTheme) return;
    onChangePlotTheme(template || colorway ? { template, colorway } : null);
  };

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title={
        <Group gap="xs">
          <Icon icon="mdi:cog" width={20} />
          <Text fw={600}>Dashboard settings</Text>
        </Group>
      }
    >
      <Stack gap="md">
        {onChangePlotTheme && (
          <>
            <Stack gap="xs" data-testid="plot-theme-section">
              <Group gap="xs">
                <Icon icon="mdi:palette-outline" width={18} />
                <Text fw={600} size="sm">
                  Plot theme
                </Text>
              </Group>
              <Text size="xs" c="dimmed">
                Default template and color palette for every figure on this dashboard.
                Options set on an individual figure still win.
              </Text>
              <Select
                label="Template"
                data={TEMPLATE_OPTIONS}
                value={plotTheme?.template ?? ''}
                onChange={(value) => emit(value || null, plotTheme?.colorway ?? null)}
                allowDeselect={false}
                data-testid="plot-theme-template"
              />
              <Select
                label="Color palette"
                data={[
                  { value: '', label: 'Default (theme palette)' },
                  ...COLORWAY_PRESETS.map(({ value, label }) => ({ value, label })),
                  ...(colorwayValue === 'custom'
                    ? [{ value: 'custom', label: 'Custom (from YAML)', disabled: true }]
                    : []),
                ]}
                value={colorwayValue}
                onChange={(value) => {
                  const preset = COLORWAY_PRESETS.find((p) => p.value === value);
                  emit(plotTheme?.template ?? null, preset ? preset.colors : null);
                }}
                allowDeselect={false}
                data-testid="plot-theme-colorway"
              />
              {colorwayValue && colorwayValue !== 'custom' && (
                <Group gap={4}>
                  {(COLORWAY_PRESETS.find((p) => p.value === colorwayValue)?.colors ?? []).map(
                    (color) => (
                      <ColorSwatch key={color} color={color} size={16} radius="sm" />
                    ),
                  )}
                </Group>
              )}
            </Stack>
            <Divider />
          </>
        )}
        <DashboardInfoBody dashboard={dashboard} active={opened} />
      </Stack>
    </Drawer>
  );
};

export default SettingsDrawer;

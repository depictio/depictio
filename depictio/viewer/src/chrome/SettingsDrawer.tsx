import React from 'react';
import {
  ActionIcon,
  Button,
  ColorInput,
  ColorSwatch,
  Divider,
  Drawer,
  FileButton,
  Grid,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData, DashboardThemeSpec } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';
import { useUiScalePref } from '../hooks/useUiScalePref';

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

const HEX_RE = /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/;

/** Client-side mirror of the server's upload cap (routes.py). */
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

/** Mini bar chart previewing how the selected palette cycles over series. */
const PREVIEW_BAR_HEIGHTS = [34, 52, 26, 44, 20, 48, 30, 40];

const PalettePreview: React.FC<{ colors: string[]; caption: string }> = ({ colors, caption }) => (
  <Paper withBorder radius="md" p="xs" data-testid="plot-theme-preview">
    <svg
      viewBox="0 0 168 64"
      style={{ width: '100%', display: 'block' }}
      role="img"
      aria-label="Palette preview"
    >
      {PREVIEW_BAR_HEIGHTS.map((height, idx) => (
        <rect
          // eslint-disable-next-line react/no-array-index-key
          key={idx}
          x={4 + idx * 20}
          y={58 - height}
          width={14}
          height={height}
          rx={2}
          fill={colors[idx % colors.length]}
        />
      ))}
      <line
        x1={2}
        y1={58.5}
        x2={166}
        y2={58.5}
        stroke="var(--mantine-color-default-border)"
        strokeWidth={1}
      />
    </svg>
    <Group gap={4} mt={6}>
      {colors.map((color, idx) => (
        // eslint-disable-next-line react/no-array-index-key
        <ColorSwatch key={idx} color={color} size={12} radius="sm" />
      ))}
    </Group>
    <Text size="xs" c="dimmed" mt={4}>
      {caption}
    </Text>
  </Paper>
);

function presetForColorway(colorway: string[] | null | undefined): string {
  if (!colorway || colorway.length === 0) return '';
  const key = JSON.stringify(colorway);
  const match = COLORWAY_PRESETS.find((preset) => JSON.stringify(preset.colors) === key);
  // A colorway written by hand (YAML or the Custom editor) that matches no
  // preset still renders — it shows as "Custom" here.
  return match ? match.value : 'custom';
}

/** A− / percent / A+ control for the dashboard content font-size preference
 *  (#854). Scales figures, tables and the other dashboard tiles — never the
 *  app chrome — and is a per-browser preference, so it renders in both the
 *  viewer and the editor. */
const FontSizeBlock: React.FC = () => {
  const { scale, increase, decrease, reset, canIncrease, canDecrease } = useUiScalePref();

  return (
    <Stack gap={6} data-testid="font-size-section">
      <Text fw={500} size="sm">
        Font size
      </Text>
      <Text size="xs" c="dimmed">
        Scales the dashboard components (figures, tables, cards…). Saved in this browser.
        Each figure can also carry its own font size from its tile menu while editing.
      </Text>
      <Group gap="xs">
        <ActionIcon.Group data-testid="font-size-control">
          <Tooltip label="Decrease font size" withArrow>
            <ActionIcon
              variant="default"
              size="input-xs"
              onClick={decrease}
              disabled={!canDecrease}
              data-testid="font-size-decrease"
              aria-label="Decrease font size"
            >
              <Icon icon="mdi:format-font-size-decrease" width={14} />
            </ActionIcon>
          </Tooltip>
          <Button
            variant="default"
            size="compact-xs"
            h="var(--input-height-xs)"
            style={{ pointerEvents: 'none' }}
            data-testid="font-size-value"
            tabIndex={-1}
          >
            {Math.round(scale * 100)}%
          </Button>
          <Tooltip label="Increase font size" withArrow>
            <ActionIcon
              variant="default"
              size="input-xs"
              onClick={increase}
              disabled={!canIncrease}
              data-testid="font-size-increase"
              aria-label="Increase font size"
            >
              <Icon icon="mdi:format-font-size-increase" width={14} />
            </ActionIcon>
          </Tooltip>
        </ActionIcon.Group>
        {scale !== 1 && (
          <Button variant="subtle" size="compact-xs" onClick={reset} data-testid="font-size-reset">
            Reset
          </Button>
        )}
      </Group>
    </Stack>
  );
};

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Editor only: makes the "Plot theme" section editable. The viewer leaves
   *  this unset and the drawer stays read-only metadata. */
  onChangePlotTheme?: (spec: DashboardThemeSpec | null) => void;
  /** Editor only: enables the "Logo" section. Uploads the file (the server
   *  persists `logo_url` on the dashboard) — reject to surface an error. */
  onUploadLogo?: (file: File) => Promise<void>;
  /** Editor only: clears the dashboard logo (saves `logo_url: null`). */
  onRemoveLogo?: () => void;
}

/**
 * Right-side drawer for the current dashboard: metadata on top, then an
 * "Appearance" section grouping the content font-size preference (#854), the
 * dashboard logo (editor only) and the dashboard-level plot theme (#397 —
 * template plus a preset or fully custom colorway applied as the default for
 * every figure component).
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
  onUploadLogo,
  onRemoveLogo,
}) => {
  const plotTheme = dashboard?.plot_theme ?? null;
  const savedColorway = plotTheme?.colorway ?? null;
  const colorwayValue = presetForColorway(savedColorway);

  // Custom-palette editor draft. Non-null while the user is editing — the
  // palette only reaches the dashboard (and a save) on "Apply". Discarded on
  // close so a half-edited palette never lingers into the next open.
  const [customDraft, setCustomDraft] = React.useState<string[] | null>(null);
  React.useEffect(() => {
    if (!opened) setCustomDraft(null);
  }, [opened]);

  const [logoUploading, setLogoUploading] = React.useState(false);
  const [logoError, setLogoError] = React.useState<string | null>(null);

  const emit = (template: string | null, colorway: string[] | null) => {
    if (!onChangePlotTheme) return;
    onChangePlotTheme(template || colorway ? { template, colorway } : null);
  };

  const selectValue = customDraft ? 'custom' : colorwayValue;
  const customEditorOpen = customDraft !== null || colorwayValue === 'custom';
  // What the custom editor rows show: the in-flight draft, else the saved
  // custom palette (editing it lazily forks a draft).
  const editingColors = customDraft ?? (colorwayValue === 'custom' ? (savedColorway ?? []) : []);

  const updateDraft = (mutate: (colors: string[]) => string[]) => {
    setCustomDraft(mutate([...editingColors]));
  };

  const draftValid = editingColors.length > 0 && editingColors.every((c) => HEX_RE.test(c));
  const draftDirty =
    customDraft !== null && JSON.stringify(customDraft) !== JSON.stringify(savedColorway);

  // Right-column result preview. While editing a custom palette it follows
  // the draft live (invalid/incomplete hex entries are skipped); otherwise it
  // shows the saved colorway, falling back to the theme's default palette.
  const validEditing = editingColors.filter((c) => HEX_RE.test(c));
  const previewColors = customEditorOpen
    ? validEditing.length
      ? validEditing
      : COLORWAY_PRESETS[0].colors
    : savedColorway?.length
      ? savedColorway
      : COLORWAY_PRESETS[0].colors;
  const templateLabel =
    TEMPLATE_OPTIONS.find((o) => o.value === (plotTheme?.template ?? ''))?.label ??
    plotTheme?.template ??
    'Default';
  const paletteLabel = customEditorOpen
    ? 'Custom palette'
    : colorwayValue
      ? (COLORWAY_PRESETS.find((p) => p.value === colorwayValue)?.label ?? 'Custom palette')
      : 'Theme default palette';
  const previewCaption = `${templateLabel} · ${paletteLabel}`;

  const handleColorwaySelect = (value: string | null) => {
    if (value === 'custom') {
      if (customEditorOpen) return;
      // Seed from the saved palette when there is one, else the Plotly default.
      setCustomDraft(savedColorway?.length ? [...savedColorway] : [...COLORWAY_PRESETS[0].colors]);
      return;
    }
    setCustomDraft(null);
    const preset = COLORWAY_PRESETS.find((p) => p.value === value);
    emit(plotTheme?.template ?? null, preset ? preset.colors : null);
  };

  const handleLogoFile = async (file: File | null) => {
    if (!file || !onUploadLogo) return;
    if (file.size > LOGO_MAX_BYTES) {
      setLogoError('File is too large (max 2MB).');
      return;
    }
    setLogoError(null);
    setLogoUploading(true);
    try {
      await onUploadLogo(file);
    } catch (err) {
      setLogoError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setLogoUploading(false);
    }
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
        <DashboardInfoBody dashboard={dashboard} active={opened} />
        <Divider />
        <Stack gap="sm" data-testid="appearance-section">
          <Group gap="xs">
            <Icon icon="mdi:palette-outline" width={18} />
            <Text fw={600} size="sm">
              Appearance
            </Text>
          </Group>
          <FontSizeBlock />
          {onUploadLogo && (
            <Stack gap={6} data-testid="dashboard-logo-section">
              <Text fw={500} size="sm">
                Logo
              </Text>
              <Text size="xs" c="dimmed">
                Shown at the bottom of the dashboard sidebar. PNG, JPEG or WebP, up to 2MB.
              </Text>
              <Group gap="xs">
                <FileButton onChange={handleLogoFile} accept="image/png,image/jpeg,image/webp">
                  {(props) => (
                    <Button
                      {...props}
                      variant="default"
                      size="xs"
                      loading={logoUploading}
                      leftSection={<Icon icon="mdi:upload" width={14} />}
                      data-testid="dashboard-logo-upload"
                    >
                      {dashboard?.logo_url ? 'Replace logo' : 'Upload logo'}
                    </Button>
                  )}
                </FileButton>
                {dashboard?.logo_url && onRemoveLogo && (
                  <Button
                    variant="subtle"
                    color="red"
                    size="xs"
                    onClick={onRemoveLogo}
                    data-testid="dashboard-logo-remove"
                  >
                    Remove
                  </Button>
                )}
              </Group>
              {logoError && (
                <Text size="xs" c="red">
                  {logoError}
                </Text>
              )}
              {/* Preview last, centered — it sits right above the divider that
                  introduces the plot theme below. */}
              {dashboard?.logo_url && (
                <img
                  src={dashboard.logo_url}
                  alt="Dashboard logo"
                  style={{
                    height: 40,
                    maxWidth: 220,
                    objectFit: 'contain',
                    alignSelf: 'center',
                  }}
                />
              )}
            </Stack>
          )}
          {onChangePlotTheme && (
            <>
              <Divider />
              <Stack gap={6} data-testid="plot-theme-section">
                <Text fw={500} size="sm">
                  Default plot theme
                </Text>
                <Text size="xs" c="dimmed">
                  Default template and color palette for every figure on this dashboard.
                  Options set on an individual figure still win.
                </Text>
                <Grid gutter="sm" align="stretch">
                  {/* Left third: the pickers. Right two thirds: the result. */}
                  <Grid.Col span={4}>
                    <Stack gap="xs">
                      <Select
                        label="Template"
                        size="xs"
                        data={TEMPLATE_OPTIONS}
                        value={plotTheme?.template ?? ''}
                        onChange={(value) => emit(value || null, savedColorway)}
                        allowDeselect={false}
                        comboboxProps={{ withinPortal: true }}
                        data-testid="plot-theme-template"
                      />
                      <Select
                        label="Palette"
                        size="xs"
                        data={[
                          { value: '', label: 'Default (theme palette)' },
                          ...COLORWAY_PRESETS.map(({ value, label }) => ({ value, label })),
                          { value: 'custom', label: 'Custom' },
                        ]}
                        value={selectValue}
                        onChange={handleColorwaySelect}
                        allowDeselect={false}
                        comboboxProps={{ withinPortal: true }}
                        data-testid="plot-theme-colorway"
                      />
                    </Stack>
                  </Grid.Col>
                  <Grid.Col span={8}>
                    <PalettePreview colors={previewColors} caption={previewCaption} />
                  </Grid.Col>
                </Grid>
                {customEditorOpen && (
                  <Stack gap={6} data-testid="custom-colorway-editor">
                    {editingColors.map((color, idx) => (
                      // eslint-disable-next-line react/no-array-index-key
                      <Group key={idx} gap="xs" wrap="nowrap">
                        <ColorInput
                          size="xs"
                          value={color}
                          onChange={(value) =>
                            updateDraft((colors) => {
                              colors[idx] = value;
                              return colors;
                            })
                          }
                          format="hex"
                          popoverProps={{ withinPortal: true }}
                          style={{ flex: 1 }}
                          data-testid={`custom-color-${idx}`}
                        />
                        <Tooltip label="Remove color" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            size="sm"
                            disabled={editingColors.length <= 1}
                            onClick={() =>
                              updateDraft((colors) => colors.filter((_, i) => i !== idx))
                            }
                            aria-label="Remove color"
                          >
                            <Icon icon="mdi:close" width={14} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    ))}
                    <Group gap="xs">
                      <Button
                        variant="default"
                        size="compact-xs"
                        leftSection={<Icon icon="mdi:plus" width={14} />}
                        onClick={() =>
                          updateDraft((colors) => [
                            ...colors,
                            colors[colors.length - 1] ?? '#636efa',
                          ])
                        }
                        data-testid="custom-color-add"
                      >
                        Add color
                      </Button>
                      <Button
                        size="compact-xs"
                        disabled={!draftDirty || !draftValid}
                        onClick={() => {
                          if (!customDraft) return;
                          emit(plotTheme?.template ?? null, customDraft);
                          setCustomDraft(null);
                        }}
                        data-testid="custom-color-apply"
                      >
                        Apply palette
                      </Button>
                    </Group>
                  </Stack>
                )}
              </Stack>
            </>
          )}
        </Stack>
      </Stack>
    </Drawer>
  );
};

export default SettingsDrawer;

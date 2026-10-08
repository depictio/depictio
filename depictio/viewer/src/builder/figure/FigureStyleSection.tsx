/**
 * The figure builder's "Card header & style" section: the style the tile is
 * drawn in, and the header a `minimal` tile shows above its plot (title,
 * subtitle, icon badge).
 *
 * Shared by both modes: UI mode lists it with the parameter sections, code
 * mode under the preview, since the editor takes the controls column. The
 * fields live on the figure's metadata (`figure_style`, `title`, `subtitle`,
 * `icon_name`, `icon_color`, `hide_legend`), not in its Plotly kwargs, so they
 * work the same for a figure written as code.
 *
 * A highlight's builder uses it too (`highlight`): there an unset style means
 * minimal rather than the section's, and an unset field takes the figure's
 * own, which `inherited` shows as the placeholder.
 */
import React, { useMemo } from 'react';
import {
  ColorSwatch,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { figureStyleForPick, normalizeFigureStyle } from 'depictio-react-core';
import type { FigureStyle } from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { BuilderSection, Field, SwitchField } from '../shared/BuilderSections';
import { useSectionFigureStyle } from '../shared/useSectionCardVariant';
import { tabLinkOptions, useTabFamily } from '../shared/useTabFamily';
import {
  SECTION_COLOR_OPTIONS,
  iconOptionsWith,
} from '../../components/sections/sectionIcons';

const STYLE_LABEL: Record<FigureStyle, string> = {
  default: 'Default',
  minimal: 'Minimal',
};

const STYLE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'minimal', label: 'Minimal' },
];

interface FigureStyleConfig {
  figure_style?: string | null;
  title?: string;
  subtitle?: string;
  icon_name?: string | null;
  icon_color?: string | null;
  hide_legend?: boolean | null;
  link?: string | null;
  caption?: string | null;
}

const FigureStyleSection: React.FC<{
  highlight?: boolean;
  /** What an unset title and subtitle show: the highlighted figure's. */
  inherited?: { title?: string; subtitle?: string };
}> = ({ highlight = false, inherited }) => {
  const config = useBuilderStore((s) => s.config) as FigureStyleConfig;
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const fromSection = useSectionFigureStyle();
  // What the tile is drawn in when it sets no style of its own.
  const sectionStyle: FigureStyle | null = highlight ? null : fromSection;
  const implicit: FigureStyle = highlight ? 'minimal' : (sectionStyle ?? 'default');
  const ownStyle = normalizeFigureStyle(config.figure_style);
  const shown = ownStyle ?? implicit;
  const tabs = useTabFamily();
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const link = config.link?.trim() || undefined;
  const linkData = useMemo(
    () => tabLinkOptions(tabs.filter((t) => t.dashboard_id !== dashboardId), link),
    [tabs, dashboardId, link],
  );

  return (
    <BuilderSection
      value="showcase"
      icon="mdi:card-text-outline"
      title="Card header & style"
      subtitle="Minimal look, title, subtitle and icon"
    >
      <Stack gap="md">
        <Field
          label="Style"
          description="Minimal: the showcase look of a landing page. The title moves to the card header beside an icon, the plot gets a faint dashed grid, large markers, the legend under it and a toolbar only on hover."
        >
          {sectionStyle && (
            <Text size="xs" c="grape" data-testid="figure-style-section-hint">
              {ownStyle && ownStyle !== sectionStyle
                ? `This section draws its figures as ${STYLE_LABEL[sectionStyle]}; this figure overrides it. Pick ${STYLE_LABEL[sectionStyle]} to follow the section again.`
                : `This section draws its figures as ${STYLE_LABEL[sectionStyle]}; pick a style here to override.`}
            </Text>
          )}
          <SegmentedControl
            value={shown}
            onChange={(val) => patchConfig({ figure_style: figureStyleForPick(val, implicit) })}
            data={STYLE_OPTIONS}
            fullWidth
            data-testid="figure-style-control"
          />
        </Field>

        <TextInput
          label="Title"
          description="The card's heading. In the minimal style it replaces the plot's own title."
          placeholder={inherited?.title || 'e.g. Phylum composition'}
          value={config.title ?? ''}
          onChange={(e) => patchConfig({ title: e.currentTarget.value })}
          leftSection={<Icon icon="mdi:format-title" width={14} />}
        />

        <TextInput
          label="Subtitle"
          description="A dimmed line beside the title, shown in the minimal style."
          placeholder={inherited?.subtitle || 'e.g. relative abundance per sample'}
          value={config.subtitle ?? ''}
          onChange={(e) => patchConfig({ subtitle: e.currentTarget.value })}
          leftSection={<Icon icon="mdi:text-short" width={14} />}
        />

        <Textarea
          label="Caption"
          description="A line or two under the plot on how to read it: what a mark is, what the filters do to it."
          placeholder="e.g. One dot per sample; the grey tick is the city's median."
          value={config.caption ?? ''}
          onChange={(e) => patchConfig({ caption: e.currentTarget.value })}
          autosize
          minRows={1}
          maxRows={4}
          data-testid="figure-caption-input"
        />

        <Group grow align="flex-start">
          <Select
            label="Icon"
            placeholder="No icon"
            data={iconOptionsWith(config.icon_name)}
            value={config.icon_name || null}
            onChange={(v) => patchConfig({ icon_name: v })}
            searchable
            clearable
            comboboxProps={{ withinPortal: false }}
            leftSection={<Icon icon={config.icon_name || 'mdi:shape-outline'} width={14} />}
            renderOption={({ option }) => (
              <Group gap="xs" wrap="nowrap">
                <Icon icon={option.value} width={16} />
                <Text size="sm">{option.label}</Text>
              </Group>
            )}
          />
          <Select
            label="Icon colour"
            data={SECTION_COLOR_OPTIONS}
            value={config.icon_color ?? ''}
            onChange={(v) => patchConfig({ icon_color: v || null })}
            allowDeselect={false}
            comboboxProps={{ withinPortal: false }}
            leftSection={<Icon icon="mdi:palette" width={14} />}
            renderOption={({ option }) => (
              <Group gap="xs" wrap="nowrap">
                <ColorSwatch
                  size={14}
                  color={option.value ? `var(--mantine-color-${option.value}-6)` : 'transparent'}
                  withShadow={false}
                />
                <Text size="sm">{option.label}</Text>
              </Group>
            )}
          />
        </Group>

        <SwitchField
          label="Hide the legend"
          description="For a tile whose colours the page explains already, such as a highlight next to its legend."
          checked={Boolean(config.hide_legend)}
          onChange={(checked) => patchConfig({ hide_legend: checked || null })}
          testId="figure-hide-legend"
        />

        {!highlight && (
          <Select
            label="Links to a tab"
            description="The tab this figure summarises, e.g. a landing page's figure drawn from an analysis tab's data. Its icon, at the end of the card header, opens that tab."
            placeholder={linkData.length ? 'No link' : 'This dashboard has no other tabs'}
            data={linkData}
            value={link ?? null}
            onChange={(val) => patchConfig({ link: val })}
            clearable
            searchable
            comboboxProps={{ withinPortal: false }}
            leftSection={<Icon icon="mdi:link-variant" width={14} />}
            data-testid="figure-link"
          />
        )}
      </Stack>
    </BuilderSection>
  );
};

export default FigureStyleSection;

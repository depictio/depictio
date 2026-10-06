/**
 * Text builder form. No data binding — text components document and organize
 * the dashboard. Mirrors design_text() in depictio/dash/modules/text_component
 * but trimmed to the essentials: title + heading level + alignment + body,
 * plus the frame and accent a landing-page tile wears.
 */
import React, { useMemo } from 'react';
import {
  ColorSwatch,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { glyphColorVar, tabDisplayName } from 'depictio-react-core';
import type { DashboardSummary } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import DesignShell from '../shared/DesignShell';
import { useTabFamily } from '../shared/useTabFamily';
import { SECTION_COLOR_OPTIONS } from '../../components/sections/sectionIcons';
import MarkdownHelp from './MarkdownHelp';
import TextPreview from './TextPreview';

const ORDER_OPTIONS = [
  { value: '1', label: 'H1 — Largest' },
  { value: '2', label: 'H2' },
  { value: '3', label: 'H3' },
  { value: '4', label: 'H4' },
  { value: '5', label: 'H5' },
  { value: '6', label: 'H6 — Smallest' },
];

const ALIGNMENT_OPTIONS = [
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Center' },
  { value: 'right', label: 'Right' },
];

const VERTICAL_ALIGNMENT_OPTIONS = [
  { value: 'top', label: 'Top' },
  { value: 'center', label: 'Center' },
  { value: 'bottom', label: 'Bottom' },
];

/** `surface` in the model: none / card / tinted. */
const FRAME_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'card', label: 'Card' },
  { value: 'tinted', label: 'Tinted' },
];

/**
 * Accent choices: the palette, then each tab's colour as `tab:<name>`. A value
 * neither offers (a CSS colour, a tab since renamed) is kept as its own entry,
 * so opening the form never blanks what the YAML set.
 */
function accentOptions(tabs: DashboardSummary[], current: string | undefined) {
  const palette = SECTION_COLOR_OPTIONS.filter((o) => o.value);
  const tabItems = tabs.map((t) => {
    const name = tabDisplayName(t);
    return { value: `tab:${name}`, label: name };
  });
  const known = new Set([...palette, ...tabItems].map((o) => o.value));
  const groups: { group: string; items: { value: string; label: string }[] }[] = [];
  if (current && !known.has(current)) {
    groups.push({ group: 'Current', items: [{ value: current, label: `${current} (custom)` }] });
  }
  groups.push({ group: 'Colour', items: palette });
  if (tabItems.length) groups.push({ group: "A tab's colour", items: tabItems });
  return groups;
}

const TextBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    order?: number | string;
    alignment?: string;
    vertical_alignment?: string;
    body?: string;
    surface?: string;
    accent?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const tabs = useTabFamily();

  const orderStr = String(config.order ?? 1);
  const alignment = config.alignment ?? 'left';
  const verticalAlignment = config.vertical_alignment ?? 'center';
  const surface =
    config.surface === 'card' || config.surface === 'tinted' ? config.surface : 'none';
  const accent = config.accent?.trim() || undefined;
  const accentData = useMemo(() => accentOptions(tabs, accent), [tabs, accent]);

  const form = (
    <Stack gap="md">
      <Title order={6} fw={700}>
        Text component configuration
      </Title>

      <TextInput
        label="Title"
        description="Heading text shown at the top of the block."
        placeholder="Section title"
        value={config.title ?? ''}
        onChange={(e) => patchConfig({ title: e.currentTarget.value })}
      />

      <Select
        label="Heading level"
        description="H1 is the largest; H6 the smallest."
        data={ORDER_OPTIONS}
        value={orderStr}
        onChange={(val) => patchConfig({ order: val ? Number(val) : 1 })}
        allowDeselect={false}
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Horizontal alignment
        </Text>
        <SegmentedControl
          value={alignment}
          onChange={(val) => patchConfig({ alignment: val })}
          data={ALIGNMENT_OPTIONS}
          fullWidth
        />
      </Stack>

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Vertical alignment
        </Text>
        <Text size="xs" c="dimmed">
          Where the text sits when the tile is taller than the text.
        </Text>
        <SegmentedControl
          value={verticalAlignment}
          onChange={(val) => patchConfig({ vertical_alignment: val })}
          data={VERTICAL_ALIGNMENT_OPTIONS}
          fullWidth
        />
      </Stack>

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Frame
        </Text>
        <Text size="xs" c="dimmed">
          None for prose between figures. Card frames the tile like a metric card, for a
          finding or a fact box on a landing page; Tinted lays it on a wash of its accent.
        </Text>
        <SegmentedControl
          value={surface}
          onChange={(val) => patchConfig({ surface: val })}
          data={FRAME_OPTIONS}
          fullWidth
        />
      </Stack>

      {/* Without a frame the renderer draws no accent at all, so the field
          would set nothing visible. */}
      {surface !== 'none' && (
        <Select
          label="Accent"
          description="Tints the tile's ground (Tinted) and the marks of a numbered fact list. A tab's colour also rests that tab's icon in a Card's corner."
          placeholder={surface === 'tinted' ? 'Grey' : 'No accent'}
          data={accentData}
          value={accent ?? null}
          onChange={(val) => patchConfig({ accent: val ?? undefined })}
          clearable
          searchable
          leftSection={<Icon icon="mdi:palette" width={16} />}
          renderOption={({ option }) => (
            <Group gap="xs" wrap="nowrap">
              <ColorSwatch
                size={14}
                withShadow={false}
                color={option.value.startsWith('tab:') ? 'transparent' : glyphColorVar(option.value)}
              />
              <Text size="sm">{option.label}</Text>
            </Group>
          )}
        />
      )}

      <Stack gap={4}>
        <Textarea
          label="Body"
          description="Optional markdown rendered below the title: headings, lists, links to tabs, icons, tables."
          autosize
          minRows={3}
          value={config.body ?? ''}
          onChange={(e) => patchConfig({ body: e.currentTarget.value })}
        />
        <MarkdownHelp />
      </Stack>
    </Stack>
  );

  return (
    <DesignShell formSlot={form} previewSlot={<TextPreview tabs={tabs} />} hideColumns />
  );
};

export default TextBuilder;

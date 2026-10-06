/**
 * The fields of one section's presentation — no chrome, no buttons.
 *
 * Add and edit are the same form, so it lives in one place and `SectionModal`
 * supplies the surface, the title and the actions. It keeps its own field state
 * and reports the spec upwards on every change (`null` while the name is empty
 * or already taken), which is what lets the modal's submit button reflect
 * validity without reaching into the form.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ColorSwatch,
  Group,
  MultiSelect,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { normalizeCardVariant, normalizeFigureStyle, SectionIcon } from 'depictio-react-core';
import type { CardVariant, FigureStyle, FilterSectionSpec } from 'depictio-react-core';

import { SECTION_COLOR_OPTIONS, iconOptionsWith } from './sectionIcons';
import type { SectionKind } from './sectionMutations';

/** `inherit` is "each card keeps its own style": the field left unset. A
 *  named sentinel rather than an empty string, which a Select cannot tell
 *  apart from no selection. */
const INHERIT = 'inherit';
const CARD_STYLE_OPTIONS: { value: CardVariant | typeof INHERIT; label: string }[] = [
  { value: INHERIT, label: 'Each card’s own style' },
  { value: 'default', label: 'Default' },
  { value: 'headline', label: 'Headline' },
  { value: 'compact', label: 'Compact' },
  { value: 'minimal', label: 'Minimal' },
  { value: 'accent', label: 'Accent' },
  { value: 'split', label: 'Split' },
];

const FIGURE_STYLE_OPTIONS: { value: FigureStyle | typeof INHERIT; label: string }[] = [
  { value: INHERIT, label: 'Each figure’s own style' },
  { value: 'default', label: 'Default' },
  { value: 'minimal', label: 'Minimal (showcase)' },
];

export interface SectionFormProps {
  /** null = a new section. */
  initial: FilterSectionSpec | null;
  /** Which list the section belongs to. Offered as a field only while
   *  creating: moving a section between the panel and the grid is not an
   *  operation the reducer has, and its components would have to move with it. */
  kind: SectionKind;
  onKindChange?: (kind: SectionKind) => void;
  /** Lower-cased names already used in `kind`'s namespace, excluding this
   *  section. Recomputed by the modal when the namespace changes. */
  taken: string[];
  /** The spec as it currently stands, or null while it cannot be submitted. */
  onChange: (spec: FilterSectionSpec | null) => void;
  /** Displayed names of the dashboard's tabs, offered for `exclude_tabs`. */
  tabNames?: string[];
  /** The name of the tab being edited, marked as such in that list. */
  currentTabName?: string;
}

const SectionForm: React.FC<SectionFormProps> = ({
  initial,
  kind,
  onKindChange,
  taken,
  onChange,
  tabNames = [],
  currentTabName,
}) => {
  const [name, setName] = useState(initial?.name ?? '');
  const [icon, setIcon] = useState(initial?.icon ?? '');
  const [color, setColor] = useState(initial?.color ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [collapsed, setCollapsed] = useState(initial?.collapsed ?? false);
  const [persistent, setPersistent] = useState(initial?.persistent ?? false);
  const [pin, setPin] = useState<'top' | 'bottom'>(
    initial?.pin === 'bottom' ? 'bottom' : 'top',
  );
  const [plain, setPlain] = useState(initial?.appearance === 'plain');
  const [excludeTabs, setExcludeTabs] = useState<string[]>(initial?.exclude_tabs ?? []);
  const [cardVariant, setCardVariant] = useState<CardVariant | null>(
    normalizeCardVariant(initial?.card_variant),
  );
  // Grid sections only: tiles on the grid, or one compact filter bar.
  const [strip, setStrip] = useState(initial?.display === 'strip');
  const isStrip = kind === 'grid' && strip;
  const [figureStyle, setFigureStyle] = useState<FigureStyle | null>(
    normalizeFigureStyle(initial?.figure_style),
  );

  // Names already excluded stay on offer even when no tab carries them any
  // more (renamed, or written in YAML for another run), so editing an
  // unrelated field never drops them.
  const tabOptions = useMemo(() => {
    // A Set, as two tabs may share a name and Mantine rejects duplicate options.
    const names = [...new Set([...tabNames, ...(initial?.exclude_tabs ?? [])])];
    return names.map((name) => ({
      value: name,
      label: name === currentTabName ? `${name} (this tab)` : name,
    }));
  }, [tabNames, currentTabName, initial?.exclude_tabs]);

  const trimmed = name.trim();
  const duplicate = taken.includes(trimmed.toLowerCase());
  const valid = trimmed.length > 0 && !duplicate;

  useEffect(() => {
    onChange(
      valid
        ? {
            name: trimmed,
            // Empty strings are dropped rather than persisted: the models treat
            // an absent icon/colour/description as "no override", and an empty
            // string would round-trip into the YAML as a key that means nothing.
            icon: icon || undefined,
            color: color || undefined,
            description: description.trim() || undefined,
            collapsed,
            persistent,
            // Meaningless on a section that shows on one tab only — left out so
            // it does not round-trip into the YAML as a setting that does
            // nothing.
            pin: persistent ? pin : undefined,
            // Grid sections only; `box` is the default and goes unwritten. A
            // filter bar has no heading to make plain.
            appearance: kind === 'grid' && plain && !isStrip ? 'plain' : undefined,
            // Same rule as `pin`: only a persistent section shows on other tabs.
            exclude_tabs: persistent && excludeTabs.length ? excludeTabs : undefined,
            // Grid sections only, and unwritten when each card keeps its own.
            card_variant: kind === 'grid' && cardVariant && !isStrip ? cardVariant : undefined,
            // Unwritten for the default grid, so a section saved from this
            // form stays readable by a server that predates filter bars.
            display: isStrip ? 'strip' : undefined,
            // A bar never folds.
            ...(isStrip ? { collapsed: false } : {}),
            figure_style: kind === 'grid' && figureStyle && !isStrip ? figureStyle : undefined,
          }
        : null,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    valid,
    trimmed,
    icon,
    color,
    description,
    collapsed,
    persistent,
    pin,
    kind,
    plain,
    excludeTabs,
    cardVariant,
    isStrip,
    figureStyle,
  ]);

  return (
    <Stack gap="md">
      {onKindChange && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Where it lives
          </Text>
          <SegmentedControl
            fullWidth
            color="grape"
            value={kind}
            onChange={(v) => onKindChange(v as SectionKind)}
            data={[
              {
                value: 'grid',
                label: (
                  <Group gap={6} justify="center" wrap="nowrap">
                    <Icon icon="mdi:view-grid-outline" width={14} />
                    <span>Dashboard grid</span>
                  </Group>
                ),
              },
              {
                value: 'filter',
                label: (
                  <Group gap={6} justify="center" wrap="nowrap">
                    <Icon icon="mdi:filter-variant" width={14} />
                    <span>Filter panel</span>
                  </Group>
                ),
              },
            ]}
          />
          <Text size="xs" c="dimmed">
            The two keep separate lists, so the same name can mean a different
            section in each.
          </Text>
        </Stack>
      )}

      <Group align="flex-end" gap="sm" wrap="nowrap">
        {/* Live preview of exactly what the section header will draw. */}
        <SectionIcon spec={{ icon, color }} size={20} fallbackIcon="mdi:shape-outline" />
        <TextInput
          label="Name"
          description="Components join a section by this name"
          placeholder="e.g. Quality"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          error={duplicate ? 'A section with this name already exists here' : undefined}
          style={{ flex: 1 }}
          data-autofocus
        />
      </Group>

      <Group grow align="flex-start">
        <Select
          label="Icon"
          placeholder="No icon"
          data={iconOptionsWith(initial?.icon)}
          value={icon || null}
          onChange={(v) => setIcon(v ?? '')}
          searchable
          clearable
          comboboxProps={{ withinPortal: false }}
          leftSection={
            icon ? <Icon icon={icon} width={16} /> : <Icon icon="mdi:shape-outline" width={16} />
          }
          renderOption={({ option }) => (
            <Group gap="xs" wrap="nowrap">
              <Icon icon={option.value} width={16} />
              <Text size="sm">{option.label}</Text>
            </Group>
          )}
        />
        <Select
          label="Colour"
          data={SECTION_COLOR_OPTIONS}
          value={color}
          onChange={(v) => setColor(v ?? '')}
          allowDeselect={false}
          comboboxProps={{ withinPortal: false }}
          leftSection={<Icon icon="mdi:palette" width={16} />}
          renderOption={({ option }) => (
            <Group gap="xs" wrap="nowrap">
              <ColorSwatch
                size={14}
                color={
                  option.value ? `var(--mantine-color-${option.value}-6)` : 'transparent'
                }
                withShadow={false}
              />
              <Text size="sm">{option.label}</Text>
            </Group>
          )}
        />
      </Group>

      <TextInput
        label="Description"
        description="Optional one-liner shown under the section title"
        placeholder="What this section covers"
        value={description}
        onChange={(e) => setDescription(e.currentTarget.value)}
      />

      {kind === 'grid' && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Display
          </Text>
          <SegmentedControl
            fullWidth
            color="grape"
            value={strip ? 'strip' : 'grid'}
            onChange={(v) => setStrip(v === 'strip')}
            data={[
              {
                value: 'grid',
                label: (
                  <Group gap={6} justify="center" wrap="nowrap">
                    <Icon icon="mdi:view-grid-outline" width={14} />
                    <span>Grid</span>
                  </Group>
                ),
              },
              {
                value: 'strip',
                label: (
                  <Group gap={6} justify="center" wrap="nowrap">
                    <Icon icon="mdi:tune-variant" width={14} />
                    <span>Filter bar</span>
                  </Group>
                ),
              },
            ]}
          />
          <Text size="xs" c="dimmed">
            {strip
              ? 'Filters placed in this section leave the filter panel and sit here in one compact row.'
              : 'Each component is a tile on the dashboard grid.'}
          </Text>
        </Stack>
      )}

      {kind === 'grid' && !isStrip && (
        <Switch
          label="Plain heading"
          description="A light heading over the tiles: no frame, no fold, always open. For a section whose tiles are already cards, like a landing page's key figures."
          checked={plain}
          onChange={(e) => setPlain(e.currentTarget.checked)}
        />
      )}

      {kind === 'grid' && !isStrip && (
        <Select
          label="Card style"
          description="How the section's metric cards are drawn. A card that picks its own style in its builder keeps it. Headline: large figures for a landing page. Compact: low cards, title and value on one line. Minimal: no frame, for cards on a tinted section. Accent: a coloured rail that singles cards out. Split: a stat tile, icon block beside the figure."
          data={CARD_STYLE_OPTIONS}
          value={cardVariant ?? INHERIT}
          onChange={(v) => setCardVariant(normalizeCardVariant(v))}
          allowDeselect={false}
          comboboxProps={{ withinPortal: false }}
          leftSection={<Icon icon="mdi:card-text-outline" width={16} />}
        />
      )}

      {kind === 'grid' && !isStrip && (
        <Select
          label="Figure style"
          description="How the section's figures are drawn. A figure that picks its own style in its builder keeps it. Minimal: the showcase look of a landing page, the title and an icon in the card header, a faint grid and the legend under the plot."
          data={FIGURE_STYLE_OPTIONS}
          value={figureStyle ?? INHERIT}
          onChange={(v) => setFigureStyle(normalizeFigureStyle(v))}
          allowDeselect={false}
          comboboxProps={{ withinPortal: false }}
          leftSection={<Icon icon="mdi:chart-scatter-plot" width={16} />}
          data-testid="section-figure-style"
        />
      )}

      {/* A plain section never folds, nor does a filter bar, so there is
          nothing to start collapsed. */}
      {!(kind === 'grid' && (plain || isStrip)) && (
        <Switch
          label="Start collapsed"
          description="Applies to first-time visitors. Anyone who has already opened this dashboard keeps the state they left it in."
          checked={collapsed}
          onChange={(e) => setCollapsed(e.currentTarget.checked)}
        />
      )}

      <Switch
        label="Show on every tab"
        description="Renders this section on all of this dashboard's tabs; filter values set in it survive tab switches. Only affects dashboards with tabs."
        checked={persistent}
        onChange={(e) => setPersistent(e.currentTarget.checked)}
      />

      {persistent && (
        <Select
          label="Position on every tab"
          description="Where the section sits relative to each tab's own content, this one included."
          data={[
            { value: 'top', label: 'Before the tab’s own sections' },
            { value: 'bottom', label: 'After the tab’s own sections' },
          ]}
          value={pin}
          onChange={(v) => setPin(v === 'bottom' ? 'bottom' : 'top')}
          allowDeselect={false}
          comboboxProps={{ withinPortal: false }}
        />
      )}

      {persistent && (
        <MultiSelect
          label="Hide on these tabs"
          description="Tabs this section is left off; the tab that owns it can be picked too. A landing tab that already sums up the same data does not need it pinned under its own figures."
          placeholder={excludeTabs.length ? undefined : 'Shown on every tab'}
          data={tabOptions}
          value={excludeTabs}
          onChange={setExcludeTabs}
          searchable
          clearable
          comboboxProps={{ withinPortal: false }}
          leftSection={<Icon icon="mdi:tab-remove" width={16} />}
        />
      )}
    </Stack>
  );
};

export default SectionForm;

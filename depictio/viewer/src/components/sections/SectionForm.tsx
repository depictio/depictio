/**
 * The fields of one section's presentation — no chrome, no buttons.
 *
 * Add and edit are the same form, so it lives in one place and `SectionModal`
 * supplies the surface, the title and the actions. It keeps its own field state
 * and reports the spec upwards on every change (`null` while the name is empty
 * or already taken), which is what lets the modal's submit button reflect
 * validity without reaching into the form.
 *
 * Laid out as the builders and the settings drawer are (`SettingsSections`):
 * the name on top, then collapsible groups, each headed by what it decides.
 * The one choice that changes what a section *is* — tiles, or a filter bar —
 * is a pair of cards with a thumbnail each, and every filter option says where
 * the filters go and what they filter, in so many words.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ColorSwatch,
  Group,
  MultiSelect,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  normalizeCardVariant,
  normalizeFigureStyle,
  SECTION_BAR_DEFAULT_VISIBLE,
  SectionIcon,
} from 'depictio-react-core';
import type { CardVariant, FigureStyle, FilterSectionSpec } from 'depictio-react-core';

import {
  Field,
  SectionAccordion,
  SettingsSection,
  SwitchField,
  useOpenSections,
} from '../settings/SettingsSections';
import { SECTION_COLOR_OPTIONS, iconOptionsWith } from './sectionIcons';
import type { SectionKind } from './sectionMutations';
import { BarPreview, LayoutChoice, SectionBarPreview, TilesPreview } from './SectionLayoutChoice';

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

type Layout = 'tiles' | 'bar';

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
  /** Labels of the filters naming this section today: what a bar on it would
   *  hold. Grid sections only. */
  filterLabels?: string[];
}

/** "City, Size fraction and Season", or how to get a first one. */
const MembersLine: React.FC<{ labels: string[]; what: string }> = ({ labels, what }) => (
  <Text size="xs" c="dimmed" lh={1.4}>
    {labels.length === 0 ? (
      <>
        No filter is placed in this section yet. Pick it as the section in a filter’s
        Placement, or use “Move to section” in a filter’s ⋮ menu.
      </>
    ) : (
      <>
        {what}:{' '}
        <Text span size="xs" fw={600} c="var(--mantine-color-text)">
          {labels.length <= 1
            ? labels[0]
            : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`}
        </Text>
        .
      </>
    )}
  </Text>
);

/** A short block saying where the filters go and what they filter. */
const ScopeNote: React.FC<{ icon: string; children: React.ReactNode }> = ({ icon, children }) => (
  <Paper
    radius="md"
    p="sm"
    bg="light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))"
    style={{ border: '1px solid var(--mantine-color-default-border)' }}
  >
    <Group gap="sm" wrap="nowrap" align="flex-start">
      <Icon icon={icon} width={18} style={{ flexShrink: 0, marginTop: 1 }} color="var(--mantine-color-grape-6)" />
      <Text size="xs" lh={1.45}>
        {children}
      </Text>
    </Group>
  </Paper>
);

const SectionForm: React.FC<SectionFormProps> = ({
  initial,
  kind,
  onKindChange,
  taken,
  onChange,
  tabNames = [],
  currentTabName,
  filterLabels = [],
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
  // Grid sections only: tiles on the grid, or the section as one filter bar.
  const [layout, setLayout] = useState<Layout>(initial?.display === 'strip' ? 'bar' : 'tiles');
  const isStrip = kind === 'grid' && layout === 'bar';
  // Grid sections of tiles only: a bar of the section's own filters.
  const [filterBar, setFilterBar] = useState(Boolean(initial?.filter_bar));
  const hasOwnBar = kind === 'grid' && !isStrip && filterBar;
  const [visibleFilters, setVisibleFilters] = useState<number | null>(
    typeof initial?.visible_filters === 'number' ? initial.visible_filters : null,
  );
  const [figureStyle, setFigureStyle] = useState<FigureStyle | null>(
    normalizeFigureStyle(initial?.figure_style),
  );

  // The layout and the section's filters are what an author opens this form
  // to decide, so they start open whatever was folded last time.
  const [open, setOpen] = useOpenSections(
    'depictio-section-form-open',
    ['look', 'layout', 'section-filters', 'behaviour'],
    ['layout', 'section-filters'],
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
            // Same: unwritten unless on.
            filter_bar: hasOwnBar ? true : undefined,
            // Only for a section with a bar, and only when the author set it.
            visible_filters: (isStrip || hasOwnBar) && visibleFilters ? visibleFilters : undefined,
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
    hasOwnBar,
    visibleFilters,
    figureStyle,
  ]);

  /** How many filters a bar shows before "More filters"; empty = the default. */
  const visibleField = (fallback: string) => (
    <NumberInput
      label="Filters shown before “More filters”"
      description={`The others wait behind a “More filters” button that unfolds them in place and says how many are hidden, and how many of those are active. Empty: ${fallback}.`}
      placeholder={fallback}
      min={1}
      max={20}
      allowDecimal={false}
      allowNegative={false}
      clampBehavior="strict"
      value={visibleFilters ?? ''}
      onChange={(v) => setVisibleFilters(typeof v === 'number' && v >= 1 ? v : null)}
      leftSection={<Icon icon="mdi:eye-outline" width={16} />}
      data-testid="section-visible-filters"
    />
  );

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

      <SectionAccordion value={open} onChange={setOpen} testId="section-form-sections">
        <SettingsSection
          value="look"
          icon="mdi:palette-outline"
          title="Look"
          subtitle="Icon, colour and the line under the name"
          testId="section-form-look"
        >
          <Stack gap="md">
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
          </Stack>
        </SettingsSection>

        {kind === 'grid' && (
          <SettingsSection
            value="layout"
            icon="mdi:view-dashboard-outline"
            title="Layout"
            subtitle="A grid of tiles, or one compact row of filters"
            testId="section-form-layout"
          >
            <Stack gap="md">
              <LayoutChoice<Layout>
                label="Layout"
                value={layout}
                onChange={setLayout}
                options={[
                  {
                    value: 'tiles',
                    title: 'Tiles',
                    icon: 'mdi:view-grid-outline',
                    description:
                      'Cards, figures, tables and text as tiles under the section’s heading.',
                    preview: <TilesPreview />,
                  },
                  {
                    value: 'bar',
                    title: 'Filter bar',
                    icon: 'mdi:tune-variant',
                    description:
                      'The section is one row of filters, standing on its own. It filters the whole tab.',
                    preview: <BarPreview />,
                  },
                ]}
              />

              {isStrip ? (
                <>
                  <ScopeNote icon="mdi:filter-variant">
                    The filters placed in this section leave the left filter panel and appear in
                    this bar, in one row. Their values filter the <b>whole tab</b>, as the
                    panel’s do: every card, figure, table and map on it whose data has the
                    filtered column (directly or through a link). They reset when the reader
                    changes tab, unless the bar shows on every tab (below).
                  </ScopeNote>
                  <MembersLine labels={filterLabels} what="In this bar" />
                  {visibleField('all of them')}
                </>
              ) : (
                <>
                  <SwitchField
                    label="Plain heading"
                    description="A light heading over the tiles: no frame, no fold, always open. For a section whose tiles are already cards, like a landing page’s key figures."
                    checked={plain}
                    onChange={setPlain}
                  />
                  {!plain && (
                    <SwitchField
                      label="Start collapsed"
                      description="Applies to first-time visitors. Anyone who has already opened this dashboard keeps the state they left it in."
                      checked={collapsed}
                      onChange={setCollapsed}
                    />
                  )}
                </>
              )}
            </Stack>
          </SettingsSection>
        )}

        {kind === 'grid' && !isStrip && (
          <SettingsSection
            value="section-filters"
            icon="mdi:filter-variant"
            title="Section filters"
            subtitle={
              hasOwnBar
                ? 'On: a row of filters under the heading, for this section only'
                : 'Off: the section follows the tab’s filters'
            }
            testId="section-form-filters"
          >
            <Stack gap="md">
              <Group gap="md" wrap="nowrap" align="flex-start">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SwitchField
                    label="Own filter bar"
                    description="Filters placed in this section appear in a compact row under its heading, and narrow only its tiles."
                    checked={filterBar}
                    onChange={setFilterBar}
                    testId="section-own-filter-bar"
                  />
                </div>
                <div
                  aria-hidden
                  style={{
                    width: 150,
                    flexShrink: 0,
                    padding: 8,
                    borderRadius: 'var(--mantine-radius-sm)',
                    background: 'light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))',
                    opacity: filterBar ? 1 : 0.5,
                  }}
                >
                  <SectionBarPreview />
                </div>
              </Group>
              {hasOwnBar && (
                <>
                  <ScopeNote icon="mdi:target">
                    The filters placed in this section leave the left filter panel and appear in
                    its bar. Their values narrow <b>only this section’s</b> cards, figures,
                    tables and maps; the rest of the tab, the filter panel and the other tabs
                    ignore them. The tab’s own filters still apply here too. While one is set,
                    the heading says “Filtered”, and the bar offers a Reset.
                  </ScopeNote>
                  <MembersLine labels={filterLabels} what="In this section’s bar" />
                  {visibleField(`${SECTION_BAR_DEFAULT_VISIBLE}`)}
                </>
              )}
              {!hasOwnBar && filterLabels.length > 0 && (
                <Text size="xs" c="dimmed">
                  Off, the filters naming this section ({filterLabels.join(', ')}) sit in the
                  filter panel, under a section of the same name, and filter the whole tab.
                </Text>
              )}
            </Stack>
          </SettingsSection>
        )}

        {kind === 'grid' && !isStrip && (
          <SettingsSection
            value="styles"
            icon="mdi:card-text-outline"
            title="Card and figure style"
            subtitle="How the section’s cards and figures are drawn"
            testId="section-form-styles"
          >
            <Stack gap="md">
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
            </Stack>
          </SettingsSection>
        )}

        {kind === 'filter' && (
          <SettingsSection
            value="behaviour"
            icon="mdi:arrow-collapse-vertical"
            title="Behaviour"
            subtitle="How the section opens"
            testId="section-form-behaviour"
          >
            <SwitchField
              label="Start collapsed"
              description="Applies to first-time visitors. Anyone who has already opened this dashboard keeps the state they left it in."
              checked={collapsed}
              onChange={setCollapsed}
            />
          </SettingsSection>
        )}

        <SettingsSection
          value="every-tab"
          icon="mdi:pin-outline"
          title="Every tab"
          subtitle={persistent ? 'Shown on all of this dashboard’s tabs' : 'Shown on this tab only'}
          testId="section-form-every-tab"
        >
          <Stack gap="md">
            <SwitchField
              label="Show on every tab"
              description={
                isStrip || hasOwnBar
                  ? 'Renders this section, its bar included, on all of this dashboard’s tabs; the bar’s values survive tab switches. Only affects dashboards with tabs.'
                  : 'Renders this section on all of this dashboard’s tabs; filter values set in it survive tab switches. Only affects dashboards with tabs.'
              }
              checked={persistent}
              onChange={setPersistent}
            />

            {persistent && (
              <Field
                label="Position on every tab"
                description="Where the section sits relative to each tab's own content, this one included."
              >
                <Select
                  data={[
                    { value: 'top', label: 'Before the tab’s own sections' },
                    { value: 'bottom', label: 'After the tab’s own sections' },
                  ]}
                  value={pin}
                  onChange={(v) => setPin(v === 'bottom' ? 'bottom' : 'top')}
                  allowDeselect={false}
                  comboboxProps={{ withinPortal: false }}
                />
              </Field>
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
        </SettingsSection>
      </SectionAccordion>
    </Stack>
  );
};

export default SectionForm;

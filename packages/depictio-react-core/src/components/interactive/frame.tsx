import React from 'react';
import { Group, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { StoredMetadata } from '../../api';

/**
 * The one frame every interactive control renders inside.
 *
 * The Filters panel stacks six or seven of these on top of each other in a
 * ~280px column, so any per-renderer variation reads as noise rather than as
 * emphasis. Before this module each renderer picked its own padding (xs / sm /
 * md), its own title size (sm hard-coded in three of them, ``md`` resolved from
 * metadata in the other three), its own stack gap (4 / 6 / 10 / 16) and its own
 * truncation policy — so titles started at different x positions, sat at
 * different sizes and wrapped in some controls but not others.
 *
 * Everything visual about the frame is decided here and nowhere else.
 */

export type TitleSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

/** Shared geometry. Compact values apply inside an `InteractiveGroupCard`,
 *  where the group's own Paper is the visible frame and each member only
 *  contributes a title line + its control. */
export const INTERACTIVE_FRAME = {
  /** Paper padding. The Filters panel gives each control a fixed 88px row, and
   *  a title line plus a `sm` input already spends 64px of it, so the roomier
   *  `md` the sliders and toggles used to carry pushed their control past the
   *  row's clipping edge. */
  padding: 'xs',
  /** Gap between the title row and the control. */
  gap: 6,
  compactGap: 2,
  /** Interactive titles are a fixed size on purpose — see `titleSize()`. */
  titleSize: 'sm' as TitleSize,
  compactTitleSize: 'xs' as TitleSize,
  iconSize: 16,
  compactIconSize: 14,
  /** Size token for the Mantine input each renderer wraps. */
  controlSize: 'sm',
} as const;

/**
 * Title size for an interactive control.
 *
 * Deliberately a constant rather than a read of ``metadata.title_size``. The
 * panel is a control surface: a filter whose title is two steps larger than its
 * neighbour's does not read as more important, it reads as misaligned, and the
 * per-component knob is what produced the mixed md/sm panel this replaces. The
 * knob still applies to cards, which are content and where size *is* hierarchy.
 */
export function titleSize(compact?: boolean): TitleSize {
  return compact ? INTERACTIVE_FRAME.compactTitleSize : INTERACTIVE_FRAME.titleSize;
}

/** Human label per control type, used to compose a default title. Each
 *  renderer used to spell its own ("MultiSelect on x", "Filter on x",
 *  "Slider on x", "Date range on x"), so four controls over the same kind of
 *  column announced themselves four different ways. */
const TYPE_LABELS: Record<string, string> = {
  MultiSelect: 'Select',
  Select: 'Select',
  SegmentedControl: 'Select',
  RangeSlider: 'Range',
  Slider: 'Value',
  DatePicker: 'Date range',
  DateRangePicker: 'Date range',
  Checkbox: 'Filter',
  Switch: 'Filter',
  Timeline: 'Timeline',
};

/** Fallback icon per control type. Every control gets one so the titles all
 *  start at the same x — an icon on some rows and not others is the most
 *  visible misalignment in a narrow column. */
const TYPE_ICONS: Record<string, string> = {
  MultiSelect: 'mdi:form-select',
  Select: 'mdi:form-select',
  SegmentedControl: 'mdi:toggle-switch',
  RangeSlider: 'bx:slider-alt',
  Slider: 'bx:slider-alt',
  DatePicker: 'mdi:calendar-range',
  DateRangePicker: 'mdi:calendar-range',
  Checkbox: 'mdi:checkbox-marked-outline',
  Switch: 'mdi:toggle-switch',
  Timeline: 'mdi:timeline-clock-outline',
};

/** ``{Type} on {column}`` in one consistent shape. Exported so the builder
 *  writes the same string it would have rendered had the author left the title
 *  empty. */
export function defaultInteractiveTitle(
  interactiveType: string | undefined,
  columnName: string | undefined,
): string {
  if (!columnName) return '';
  return `${TYPE_LABELS[interactiveType || ''] || 'Filter'} on ${columnName}`;
}

/** Author's title, else the default above. */
export function interactiveTitle(metadata: StoredMetadata): string {
  if (metadata.title) return metadata.title;
  return defaultInteractiveTitle(metadata.interactive_component_type, metadata.column_name);
}

export function interactiveIcon(metadata: StoredMetadata): string {
  return (
    metadata.icon_name || TYPE_ICONS[metadata.interactive_component_type || ''] || 'mdi:filter-variant'
  );
}

/** Resolve a metadata colour that can be a Mantine token name ("blue") or a raw
 *  CSS colour (#hex, rgb(...), var(...)). */
export function resolveColor(c?: string | null): string | undefined {
  if (!c) return undefined;
  if (c.startsWith('#') || c.startsWith('rgb') || c.startsWith('var(')) return c;
  return `var(--mantine-color-${c}-6)`;
}

/** The component's accent, as authored: `icon_color` first, then the two names
 *  the colour has carried across the Dash port (`color`, `custom_color`).
 *
 *  One accessor because the icon, the title and the control all have to read
 *  the same field. They used to read different ones — the sliders took
 *  `custom_color`, the icon took `icon_color` and fell back to a hard-coded
 *  blue, the title took nothing — so a filter authored in one colour rendered
 *  as an orange track under a blue icon and a black title. */
export function interactiveAccentRaw(metadata: StoredMetadata): string | undefined {
  const m = metadata as Record<string, unknown>;
  return (
    (metadata.icon_color as string | undefined) ||
    (m.color as string | undefined) ||
    (m.custom_color as string | undefined) ||
    undefined
  );
}

/** `interactiveAccentRaw` resolved to a CSS colour. */
export function interactiveAccent(metadata: StoredMetadata): string | undefined {
  return resolveColor(interactiveAccentRaw(metadata));
}

/** Tick labels under a slider track.
 *
 *  Mantine sizes them at `sm` regardless of the slider's own size, which put
 *  them at exactly the weight of the filter's title and a step above the value
 *  readout beside it — three type sizes in one 88px row. They are captions, so
 *  they take the caption size the readout and the cards' strips already use.
 *
 *  `DepictioRangeSlider` carries its own copy (it lives in another package and
 *  cannot import this one); the two have to stay in step, since the Filters
 *  panel stacks both. */
export const SLIDER_MARK_LABEL_STYLE = {
  fontSize: 'var(--mantine-font-size-xs)',
  lineHeight: 1.2,
} as const;

export interface InteractiveTitleProps {
  metadata: StoredMetadata;
  compact?: boolean;
  /** Optional trailing node (e.g. the Slider's current-value readout), pinned
   *  right of the truncating title. */
  right?: React.ReactNode;
}

/** Icon + title row. Always truncates: a long column name must cost width, not
 *  a second line, or it pushes the control out of the panel's fixed row. */
export const InteractiveTitle: React.FC<InteractiveTitleProps> = ({
  metadata,
  compact,
  right,
}) => {
  const title = interactiveTitle(metadata);
  if (!title) return null;
  const icon = interactiveIcon(metadata);
  const size = compact ? INTERACTIVE_FRAME.compactIconSize : INTERACTIVE_FRAME.iconSize;
  const accent = interactiveAccent(metadata);
  const iconColor = accent || 'var(--mantine-color-blue-6)';
  // The author's `title_color` wins; otherwise the title takes the accent, so a
  // filter reads as one coloured unit the way a card's title does. With no
  // accent at all it stays plain body text.
  const titleColor = resolveColor(metadata.title_color as string | undefined) || accent;

  return (
    <Group gap="xs" align="center" wrap="nowrap" justify="space-between">
      <Group gap="xs" align="center" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
        <Icon
          icon={icon}
          width={size}
          height={size}
          style={{ color: iconColor, flexShrink: 0 }}
        />
        <Text
          fw={600}
          size={titleSize(compact)}
          truncate
          c={titleColor}
          style={{ minWidth: 0 }}
        >
          {title}
        </Text>
      </Group>
      {right}
    </Group>
  );
};

export interface InteractiveFrameProps {
  compact?: boolean;
  children: React.ReactNode;
}

/** Bordered card around one control — or nothing at all in compact mode, where
 *  the parent `InteractiveGroupCard` already supplies the border. */
export const InteractiveFrame: React.FC<InteractiveFrameProps> = ({ compact, children }) => {
  if (compact) {
    return <Stack gap={INTERACTIVE_FRAME.compactGap}>{children}</Stack>;
  }
  return (
    <Paper
      p={INTERACTIVE_FRAME.padding}
      radius="md"
      shadow="xs"
      withBorder
      className="dashboard-component-hover"
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
      }}
    >
      <Stack gap={INTERACTIVE_FRAME.gap} style={{ flex: 1, minWidth: 0 }}>
        {children}
      </Stack>
    </Paper>
  );
};

import React from 'react';
import { Accordion, Group, Text } from '@mantine/core';

import type { FilterSectionSpec } from '../api';
import type { CollapseState } from '../hooks/useCollapseState';
import SectionIcon, { sectionColorVar } from './SectionIcon';
import './sectionAccordion.css';

/**
 * The accordion a dashboard's sections are rendered in, and the header row
 * inside each item.
 *
 * The grid and the left filter panel both group their components into sections
 * and both fold them the same way, so they render the same chrome — down to the
 * comment explaining why the icon can't go through `Accordion.Control`'s `icon`
 * prop. Keeping one component means the two can't drift on spacing, sizing or
 * on what a folded section still shows.
 */

export const SectionAccordion: React.FC<{
  /** Keys of the open sections. */
  value: string[];
  onChange: (value: string[]) => void;
  /** Tighter rows and a smaller header, for the narrow filter panel. */
  compact?: boolean;
  children: React.ReactNode;
}> = ({ value, onChange, compact = false, children }) => (
  <Accordion
    multiple
    variant="default"
    radius="md"
    chevronPosition="left"
    value={value}
    onChange={onChange}
    className={compact ? 'depictio-section-accordion is-compact' : 'depictio-section-accordion'}
    classNames={{
      item: 'depictio-section-item',
      control: 'depictio-section-control',
      panel: 'depictio-section-panel',
      // The content, not the panel, carries the body padding — Mantine collapses
      // the panel to `height: 0` and padding on it outlives the collapse. See
      // sectionAccordion.css.
      content: 'depictio-section-content',
    }}
  >
    {children}
  </Accordion>
);

export const SectionAccordionItem: React.FC<{
  value: string;
  /**
   * Mantine palette name from the section spec — tints the rail. Passed by the
   * grid only: a coloured rail in the filter panel too would put two colour
   * columns at the same heights on either side of the screen, which reads as
   * one paired set even though the panel's sections and the grid's are separate
   * lists. The panel's colour stays on the icon and the count badge, where it
   * identifies a section without claiming a region.
   */
  color?: string | null;
  children: React.ReactNode;
}> = ({ value, color, children }) => (
  <Accordion.Item
    value={value}
    style={
      color
        ? ({ '--section-accent': sectionColorVar(color) } as React.CSSProperties)
        : undefined
    }
  >
    {children}
  </Accordion.Item>
);

export const SectionHeader: React.FC<{
  spec?: FilterSectionSpec | null;
  /** Optional only because the section types leave the unsectioned bucket
   *  nameless — that bucket renders bare, never through this header. */
  name?: string;
  /** Sits next to the title — the active-filter count, typically. */
  badge?: React.ReactNode;
  /** Pushed to the far end of the row, e.g. a folded section's metrics. */
  trailing?: React.ReactNode;
}> = ({ spec, name, badge, trailing }) => (
  <Group justify="space-between" wrap="nowrap" gap="sm" pr="xs" style={{ minWidth: 0 }}>
    {/* The icon goes INSIDE the label, not in `Accordion.Control`'s `icon`
        prop: Mantine renders that prop's node after the label and gives it a
        `spacing-lg` inline-start margin, which puts a section's icon on the far
        side of its own title. */}
    {/* Type and icon are the same size wherever a section is drawn — a section
        heading is a section heading. The filter panel buys its room back on the
        header's height instead (see sectionAccordion.css). */}
    <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
      <SectionIcon spec={spec ?? undefined} />
      {/* Title over subtitle: the header carries the narration that dashboards
          used to spend a full-width text component on. In the header rather
          than the body because a folded section is exactly when its description
          is the only thing left to explain it. */}
      <div style={{ minWidth: 0 }}>
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Text size="md" fw={600} truncate>
            {name}
          </Text>
          {badge}
        </Group>
        {spec?.description && (
          <Text size="sm" c="dimmed" truncate>
            {spec.description}
          </Text>
        )}
      </div>
    </Group>
    {trailing}
  </Group>
);

/**
 * Translate Mantine's "here is the full open set" callback into the per-key
 * toggles the persisted collapse state is built from.
 */
export function applyAccordionValue(
  open: string[],
  keys: string[],
  collapse: CollapseState,
): void {
  const openSet = new Set(open);
  // Two calls rather than a diff: each only adds or only removes, which is what
  // `setAll`'s no-op check assumes.
  collapse.setAll(
    keys.filter((k) => openSet.has(k)),
    false,
  );
  collapse.setAll(
    keys.filter((k) => !openSet.has(k)),
    true,
  );
}

export default SectionAccordion;

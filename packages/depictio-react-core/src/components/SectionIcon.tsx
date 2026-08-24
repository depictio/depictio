import React from 'react';
import { Icon } from '@iconify/react';

import type { FilterSectionSpec } from '../api';

/**
 * A section's icon, tinted with the section's colour.
 *
 * Shared by the filter panel and the dashboard grid on purpose: a section named
 * "QC" should look the same wherever it is rendered, and the two headers used to
 * disagree on icon size *and* on which side of the title the icon landed on —
 * the grid passed it through `Accordion.Control`'s `icon` prop, which Mantine
 * renders *after* the label with a `spacing-lg` inline-start margin.
 *
 * A bare glyph rather than a `ThemeIcon`: the tinted square read as a button in
 * a header row that already holds a chevron, and shrank the icon to whatever fit
 * inside its box. The colour alone carries the section identity.
 *
 * Renders nothing when the section declares no icon, so a header without one
 * keeps its title flush against the chevron. Authoring UIs — where a row must
 * stay aligned whether or not an icon has been picked yet — pass `fallbackIcon`
 * to get a placeholder instead.
 */
export const SectionIcon: React.FC<{
  spec?: Pick<FilterSectionSpec, 'icon' | 'color'>;
  size?: number;
  fallbackIcon?: string;
}> = ({ spec, size = 22, fallbackIcon }) => {
  const icon = spec?.icon || fallbackIcon;
  if (!icon) return null;
  return (
    <Icon
      icon={icon}
      width={size}
      height={size}
      style={{ color: sectionColorVar(spec?.color), flexShrink: 0 }}
    />
  );
};

/**
 * A section's `color` is a Mantine palette *name* (`teal`), so it can't be used
 * as a CSS colour directly. Unset, sections stay neutral — the dimmed token
 * rather than a picked hue, so an undecorated dashboard doesn't look like every
 * section chose grey on purpose.
 */
export function sectionColorVar(color?: string | null): string {
  if (!color) return 'var(--mantine-color-dimmed)';
  return `var(--mantine-color-${color}-6)`;
}

export default SectionIcon;
